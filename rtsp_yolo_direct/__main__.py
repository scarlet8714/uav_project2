"""Run with: python -m rtsp_yolo_direct"""

from aiohttp import web

from .config import parse_args
from .server import create_app


def main():
    config = parse_args()
    app = create_app(config)
    print(f"Event log: {app['log'].directory}", flush=True)
    print(f"Open http://<device-ip>:{config.port}/", flush=True)
    web.run_app(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
