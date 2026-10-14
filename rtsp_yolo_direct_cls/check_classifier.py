"""Isolated GPU classifier check; does not open RTSP, GPS, or a server."""

import argparse
import json
from pathlib import Path

import numpy as np
from onnx.reference import ReferenceEvaluator

from .classification import TensorRTClassifier, load_settings, preprocess, probabilities


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--model-path", default=str(root/"classifier_fp16.engine"))
    parser.add_argument("--config", default=str(Path(__file__).with_name("classifier_config.json")))
    parser.add_argument("--onnx", default=str(root/"classifier.onnx"))
    parser.add_argument("--probability-tolerance", type=float,
                        help="Optional strict probability tolerance; FP16 may differ from FP32")
    args = parser.parse_args()
    settings = load_settings(args.config)
    runner = TensorRTClassifier(args.model_path, settings)
    engine = runner.engine
    tensors = [{"name": name, "shape": list(runner.context.get_tensor_shape(name)),
                "dtype": str(engine.get_tensor_dtype(name))}
               for name in (runner.input_name, runner.output_name)]
    reference = ReferenceEvaluator(args.onnx)
    rng = np.random.default_rng(20261013)
    samples = [np.full((80, 120, 3), [30, 60, 120], dtype=np.uint8),
               rng.integers(0, 256, (96, 160, 3), dtype=np.uint8),
               np.tile(np.arange(160, dtype=np.uint8)[None, :, None], (96, 1, 3))]
    comparisons = []
    for sample in samples:
        actual = runner.predict(sample)
        expected = probabilities(reference.run(None, {runner.input_name:
                                 preprocess(sample, settings)})[0], settings["output_kind"])
        difference = float(np.max(np.abs(actual-expected)))
        comparisons.append({"probabilities": actual.tolist(),
                            "onnx_probabilities": expected.tolist(),
                            "label": settings["labels"][int(actual.argmax())],
                            "onnx_label": settings["labels"][int(expected.argmax())],
                            "max_probability_difference": difference})
    passed = all(item["label"] == item["onnx_label"] and
                 (args.probability_tolerance is None or
                  item["max_probability_difference"] <= args.probability_tolerance)
                 for item in comparisons)
    print(json.dumps({"model_path": args.model_path, "tensors": tensors,
                      "labels": settings["labels"],
                      "preprocessing_verified": settings.get("preprocessing_verified", False),
                      "probability_tolerance": args.probability_tolerance,
                      "comparisons": comparisons, "passed": passed}, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
