"""Native TensorRT classifier and per-track, bounded classification history."""

from collections import deque
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np


def load_settings(path):
    settings = json.loads(Path(path).read_text(encoding="utf-8"))
    labels = settings.get("labels")
    if (not isinstance(labels, list) or len(labels) != 3 or
            any(not isinstance(label, str) or not label for label in labels) or
            len(set(labels)) != 3):
        raise ValueError("Classifier settings require three distinct ordered labels")
    if settings.get("color_order") not in ("RGB", "BGR"):
        raise ValueError("color_order must be RGB or BGR")
    if settings.get("resize_mode") not in ("stretch", "center_crop"):
        raise ValueError("resize_mode must be stretch or center_crop")
    if settings.get("output_kind") not in ("logits", "probabilities"):
        raise ValueError("output_kind must be logits or probabilities")
    if not isinstance(settings.get("input_size"), int) or settings["input_size"] <= 0:
        raise ValueError("input_size must be a positive integer")
    if (settings["resize_mode"] == "center_crop" and
            (not isinstance(settings.get("resize_shorter"), int) or
             settings["resize_shorter"] < settings["input_size"])):
        raise ValueError("resize_shorter must be at least input_size for center_crop")
    for name in ("mean", "std"):
        values = settings.get(name)
        if (not isinstance(values, list) or len(values) != 3 or
                any(not isinstance(value, (int, float)) or not math.isfinite(value)
                    for value in values)):
            raise ValueError(f"{name} must contain three finite numbers")
    if any(value <= 0 for value in settings["std"]):
        raise ValueError("std values must be positive")
    scale = settings.get("scale")
    if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be finite and positive")
    return settings


def preprocess(crop, settings):
    size = settings["input_size"]
    if settings["color_order"] == "RGB":
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    if settings["resize_mode"] == "center_crop":
        height, width = crop.shape[:2]
        ratio = settings["resize_shorter"] / min(height, width)
        crop = cv2.resize(crop, (round(width*ratio), round(height*ratio)),
                          interpolation=cv2.INTER_LINEAR)
        y = (crop.shape[0]-size)//2
        x = (crop.shape[1]-size)//2
        crop = crop[y:y+size, x:x+size]
    else:
        crop = cv2.resize(crop, (size, size), interpolation=cv2.INTER_LINEAR)
    image = crop.astype(np.float32) * settings["scale"]
    image = (image-np.array(settings["mean"], dtype=np.float32)) / np.array(
        settings["std"], dtype=np.float32)
    return np.ascontiguousarray(image.transpose(2, 0, 1)[None])


def probabilities(output, kind="logits"):
    values = np.asarray(output, dtype=np.float64).reshape(-1)
    if values.shape != (3,) or not np.isfinite(values).all():
        raise ValueError("Classifier must return three finite scores")
    if kind == "logits":
        values = np.exp(values-values.max())
    elif (values < 0).any():
        raise ValueError("Classifier probabilities must not be negative")
    total = values.sum()
    if total <= 0:
        raise ValueError("Classifier probabilities must have a positive sum")
    return values / total


class TensorRTClassifier:
    """Support raw trtexec engines, including fixed or dynamic batch sizes."""

    def __init__(self, path, settings):
        import tensorrt as trt
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("Classifier requires an accessible CUDA device")
        self.torch, self.trt, self.settings = torch, trt, settings
        self.logger = trt.Logger(trt.Logger.ERROR)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(Path(path).read_bytes())
        if self.engine is None:
            raise ValueError("Cannot deserialize classifier engine; check conversion/platform")
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("Cannot create classifier execution context")
        names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        inputs = [n for n in names if self.engine.get_tensor_mode(n) == trt.TensorIOMode.INPUT]
        outputs = [n for n in names if self.engine.get_tensor_mode(n) == trt.TensorIOMode.OUTPUT]
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError("Classifier engine requires one input and one output")
        self.input_name, self.output_name = inputs[0], outputs[0]
        for name in names:
            if (self.engine.get_tensor_format(name) != trt.TensorFormat.LINEAR or
                    self.engine.get_tensor_location(name) != trt.TensorLocation.DEVICE):
                raise ValueError("Classifier requires linear CUDA input/output tensors")
        shape = tuple(self.engine.get_tensor_shape(self.input_name))
        size = settings["input_size"]
        if len(shape) != 4:
            raise ValueError("Classifier input must be NCHW")
        if any(d < 0 for d in shape):
            minimum, _, maximum = self.engine.get_tensor_profile_shape(self.input_name, 0)
            self.batch_size = max(1, minimum[0])
            desired = (self.batch_size, 3, size, size)
            if any(not low <= d <= high for d, low, high in zip(desired, minimum, maximum)):
                raise ValueError("Classifier input profile does not support configured input_size")
            if not self.context.set_input_shape(self.input_name, desired):
                raise ValueError("Cannot set classifier input shape")
            shape = tuple(self.context.get_tensor_shape(self.input_name))
        self.batch_size = shape[0]
        if shape != (self.batch_size, 3, size, size) or self.batch_size <= 0:
            raise ValueError("Classifier input must match configured (batch, 3, size, size)")
        output_shape = tuple(self.context.get_tensor_shape(self.output_name))
        if output_shape != (self.batch_size, 3):
            raise ValueError("Classifier output must have shape (batch, 3)")
        dtype_map = {trt.float32: torch.float32, trt.float16: torch.float16}
        try:
            input_dtype = dtype_map[self.engine.get_tensor_dtype(self.input_name)]
            output_dtype = dtype_map[self.engine.get_tensor_dtype(self.output_name)]
        except KeyError as exc:
            raise ValueError("Classifier input/output must be FP16 or FP32") from exc
        self.stream = torch.cuda.Stream()
        with torch.cuda.stream(self.stream):
            self.input = torch.empty(shape, dtype=input_dtype, device="cuda")
            self.output = torch.empty(output_shape, dtype=output_dtype, device="cuda")
        if (not self.context.set_tensor_address(self.input_name, self.input.data_ptr()) or
                not self.context.set_tensor_address(self.output_name, self.output.data_ptr())):
            raise RuntimeError("Cannot bind classifier CUDA buffers")

    def predict(self, crop):
        image = preprocess(crop, self.settings)
        # A fixed-batch engine can still classify one crop by padding the batch.
        if self.batch_size > 1:
            image = np.repeat(image, self.batch_size, axis=0)
        with self.torch.cuda.stream(self.stream):
            self.input.copy_(self.torch.from_numpy(image), non_blocking=False)
            if not self.context.execute_async_v3(self.stream.cuda_stream):
                raise RuntimeError("Classifier TensorRT execution failed")
        self.stream.synchronize()
        return probabilities(self.output[0].float().cpu().numpy(), self.settings["output_kind"])


class ClassificationManager:
    def __init__(self, engine_path, config_path, history_size=7, enabled=True,
                 on_event=lambda *args, **kwargs: None, runner_factory=TensorRTClassifier):
        self.engine_path = Path(engine_path)
        self.config_path = Path(config_path)
        self.history_size = history_size
        self.enabled = enabled
        self.on_event = on_event
        self.runner_factory = runner_factory
        self.runner = None
        self.settings = None
        self.histories = {}
        self.selected_indices = {}
        self.state = "waiting_engine" if enabled else "disabled"
        self.last_error = None
        self.next_retry = 0.0
        self.classified_crops = 0
        self.last_inference_ms = None

    def reset(self):
        self.histories.clear()
        self.selected_indices.clear()

    def _state(self, state, error=None):
        if state != self.state or error != self.last_error:
            self.state, self.last_error = state, error
            self.on_event("classifier_state", state=state, error=error,
                          classifier_model_path=str(self.engine_path))

    def ensure_ready(self):
        if not self.enabled:
            return False
        if self.runner is not None:
            return True
        now = time.monotonic()
        if now < self.next_retry:
            return False
        self.next_retry = now+5.0
        try:
            if not self.engine_path.is_file():
                self._state("waiting_engine")
                return False
            if time.time()-self.engine_path.stat().st_mtime < 2.0:
                self._state("engine_building")
                return False
            self.settings = load_settings(self.config_path)
            self.runner = self.runner_factory(self.engine_path, self.settings)
            self.reset()
            self._state("ready")
        except Exception as exc:
            self.runner = None
            self._state("error", str(exc))
            return False
        return True

    def update(self, boxes, image, active_ids):
        self.histories = {key: history for key, history in self.histories.items()
                          if key in active_ids}
        self.selected_indices = {key: index for key, index in self.selected_indices.items()
                                 if key in active_ids}
        ready = self.ensure_ready()
        height, width = image.shape[:2]
        for box in boxes:
            if not box["observed"]:
                continue
            label = box.get("detector_label", box["label"])
            box["detector_label"] = label
            key = box["track_id"]
            if label != "military_car":
                self.histories.pop(key, None)
                self.selected_indices.pop(key, None)
                continue
            if not ready:
                continue
            x1, y1 = max(0, math.floor(box["x1"])), max(0, math.floor(box["y1"]))
            x2, y2 = min(width, math.ceil(box["x2"])), min(height, math.ceil(box["y2"]))
            if x2 <= x1 or y2 <= y1:
                continue
            started = time.monotonic()
            try:
                scores = probabilities(self.runner.predict(image[y1:y2, x1:x2]), "probabilities")
                history = self.histories.setdefault(key, deque(maxlen=self.history_size))
                history.append(scores)
                predictions = [int(item.argmax()) for item in history]
                votes = np.bincount(predictions, minlength=len(self.settings["labels"]))
                leaders = np.flatnonzero(votes == votes.max()).tolist()
                previous = self.selected_indices.get(key)
                # Prefer the displayed class only when it is tied for the most votes.
                # Otherwise, break a tie by the most recent prediction among leaders.
                index = (previous if previous in leaders else
                         next(item for item in reversed(predictions) if item in leaders))
                self.selected_indices[key] = index
                vote_shares = votes / len(history)
                box.update(label=self.settings["labels"][index],
                           classifier_index=index, classification_count=len(history),
                           classifier_confidence=float(vote_shares[index]),
                           classifier_probs=vote_shares.tolist(),
                           classifier_votes=votes.tolist(),
                           classifier_raw_index=int(scores.argmax()),
                           classifier_raw_probs=scores.tolist())
                self.classified_crops += 1
                self.last_inference_ms = round((time.monotonic()-started)*1000, 1)
            except Exception as exc:
                self.runner = None
                ready = False
                self.next_retry = time.monotonic()+5.0
                self.reset()
                self._state("error", str(exc))

    def status(self):
        return {"enabled": self.enabled, "state": self.state,
                "model_path": str(self.engine_path), "config_path": str(self.config_path),
                "labels": None if self.settings is None else self.settings["labels"],
                "preprocessing_verified": bool(self.settings and
                                                self.settings.get("preprocessing_verified")),
                "history_size": self.history_size, "classified_crops": self.classified_crops,
                "aggregation": "majority_vote",
                "inference_ms": self.last_inference_ms, "last_error": self.last_error}
