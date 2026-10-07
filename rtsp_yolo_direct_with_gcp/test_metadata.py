"""Run: python -m unittest rtsp_yolo_direct_with_gcp.test_metadata -v."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import web

from . import server


class FakeWebSocket:
    def __init__(self, **kwargs):
        self.closed = False
        self.messages = []
        self.incoming = asyncio.Queue()
        self.receiving = asyncio.Event()

    async def prepare(self, request):
        pass

    async def send_json(self, message):
        self.messages.append(message)

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.receiving.set()
        message = await self.incoming.get()
        if message == "disconnect":
            self.closed = True
            raise StopAsyncIteration
        return message


async def settle():
    for _ in range(15):
        await asyncio.sleep(0)


class MetadataReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.peer = {"origin": 123456, "queue": None, "closing": False,
                     "pc": SimpleNamespace(connectionState="connected"),
                     "track": SimpleNamespace(readyState="live")}
        self.app = {"peers": {"viewer": self.peer},
                    "log": SimpleNamespace(write=lambda *args, **kwargs: None)}
        self.request = SimpleNamespace(app=self.app, match_info={"peer_id": "viewer"}, remote="test")
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def connect(self):
        ws = FakeWebSocket()
        with patch.object(server.web, "WebSocketResponse", return_value=ws):
            task = asyncio.create_task(server.events(self.request))
            self.tasks.append(task)
            await ws.receiving.wait()
            await settle()
        return ws, task

    async def test_reconnected_socket_gets_same_origin_and_new_detections_without_closing_video(self):
        first, first_task = await self.connect()
        self.assertEqual(first.messages, [{"type": "origin", "rtpOrigin": 123456}])
        first.incoming.put_nowait("disconnect")
        await first_task
        self.assertIsNone(self.peer["queue"])
        second, _ = await self.connect()
        self.assertEqual(second.messages, first.messages)
        detection = {"type": "detection", "generation": 1, "ptsSeconds": 2}
        server.publish(self.app, detection)
        await settle()
        self.assertEqual(second.messages[-1], detection)
        self.assertEqual(self.peer["pc"].connectionState, "connected")
        self.assertEqual(self.peer["track"].readyState, "live")

    async def test_new_socket_replaces_old_queue_and_old_cleanup_keeps_new_queue(self):
        first, first_task = await self.connect()
        first_queue = self.peer["queue"]
        second, _ = await self.connect()
        second_queue = self.peer["queue"]
        self.assertIsNot(first_queue, second_queue)
        await first_task
        self.assertTrue(first.closed)
        self.assertIs(self.peer["queue"], second_queue)
        server.publish(self.app, {"type": "detection", "ptsSeconds": 3})
        await settle()
        self.assertEqual(len(first.messages), 1)
        self.assertEqual(second.messages[-1]["ptsSeconds"], 3)
        self.assertIn("viewer", self.app["peers"])

    async def test_receive_loop_processes_incoming_frames_and_idle_close(self):
        ws, task = await self.connect()
        ws.incoming.put_nowait("pong handled by aiohttp receive")
        await settle()
        self.assertFalse(task.done())
        ws.incoming.put_nowait("disconnect")
        await task
        self.assertIsNone(self.peer["queue"])
        self.assertEqual(self.peer["pc"].connectionState, "connected")

    async def test_end_closes_only_metadata_socket(self):
        ws, task = await self.connect()
        self.peer["queue"].put_nowait({"type": "end"})
        await task
        self.assertTrue(ws.closed)
        self.assertIsNone(self.peer["queue"])
        self.assertEqual(self.peer["pc"].connectionState, "connected")

    async def test_missing_or_closing_peer_does_not_accept_metadata_connection(self):
        for closing in (True, False):
            if closing:
                self.peer["closing"] = True
            else:
                self.app["peers"].clear()
            with self.assertRaises(web.HTTPNotFound):
                await server.events(self.request)


if __name__ == "__main__":
    unittest.main()
