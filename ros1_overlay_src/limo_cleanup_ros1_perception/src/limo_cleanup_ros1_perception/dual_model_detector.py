"""ROS-independent dual-model inference with immutable weight bindings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping, Optional, Sequence, Tuple

if TYPE_CHECKING:
    import numpy as np

from limo_cleanup_ros1_perception.perception_core import Detection2D
from limo_cleanup_ros1_perception.target_contract import (
    require_single_class_model,
)
from limo_cleanup_ros1_perception.model_binding_contract import (
    MODEL_CLASSES,
    ModelBinding,
    load_model_bindings,
    model_set_sha256,
    resolve_model_artifacts,
)


@dataclass(frozen=True)
class InferenceConfig:
    """Bounded Ultralytics inference parameters."""

    confidence: float = 0.35
    iou: float = 0.45
    image_size: int = 640
    device: str = ''


def _validate_config(config: InferenceConfig) -> None:
    if (
            not math.isfinite(config.confidence)
            or not 0.0 < config.confidence <= 1.0):
        raise ValueError('confidence must be within (0, 1]')
    if not math.isfinite(config.iou) or not 0.0 < config.iou <= 1.0:
        raise ValueError('iou must be within (0, 1]')
    if (
            not isinstance(config.image_size, int)
            or isinstance(config.image_size, bool)
            or config.image_size <= 0):
        raise ValueError('image_size must be a positive integer')
    if not isinstance(config.device, str):
        raise ValueError('device must be a string')


class DualModelInference:
    """Run two immutable single-class detectors without importing ROS."""

    def __init__(
            self, manifest_path: Path, model_root: Optional[Path] = None,
            config: InferenceConfig = InferenceConfig(),
            loader: Optional[Callable] = None):
        _validate_config(config)
        self.config = config
        self.bindings, self.manifest_sha256 = load_model_bindings(
            manifest_path)
        self.model_paths = resolve_model_artifacts(
            self.bindings, model_root=model_root)
        self.model_set_sha256 = model_set_sha256(self.bindings)
        if loader is None:
            try:
                from ultralytics import YOLO
            except ImportError as error:
                raise RuntimeError('ultralytics runtime is unavailable') from error
            loader = YOLO
        self.models = {}
        for class_name in MODEL_CLASSES:
            model = loader(str(self.model_paths[class_name]))
            require_single_class_model(model.names, class_name)
            self.models[class_name] = model

    def infer(
            self, image: np.ndarray
            ) -> Tuple[Tuple[Detection2D, ...], Tuple[Detection2D, ...]]:
        """Return bottle and bin detections in deterministic class order."""
        import numpy as np

        if (
                not isinstance(image, np.ndarray)
                or image.ndim != 3
                or image.shape[2] != 3
                or image.size == 0):
            raise ValueError('inference image must be a non-empty BGR array')
        outputs = {}
        for class_name in MODEL_CLASSES:
            result = self.models[class_name].predict(
                source=image,
                conf=self.config.confidence,
                iou=self.config.iou,
                imgsz=self.config.image_size,
                device=self.config.device,
                verbose=False,
            )[0]
            outputs[class_name] = tuple(self._detections(
                result, class_name, self.bindings[class_name].filename))
        return outputs['plastic_bottle'], outputs['trash_bin']

    @staticmethod
    def _detections(result, class_name: str, source: str) -> Sequence[Detection2D]:
        boxes = getattr(result, 'boxes', None)
        if boxes is None:
            return ()
        coordinates = boxes.xyxy.detach().cpu().tolist()
        confidences = boxes.conf.detach().cpu().tolist()
        class_ids = boxes.cls.detach().cpu().tolist()
        if not (
                len(coordinates) == len(confidences) == len(class_ids)):
            raise ValueError('model result arrays have inconsistent lengths')
        detections = []
        for box, confidence, class_id in zip(
                coordinates, confidences, class_ids):
            if int(class_id) != 0 or len(box) != 4:
                raise ValueError('single-class model emitted invalid class geometry')
            values = [float(value) for value in box]
            score = float(confidence)
            if (
                    not all(math.isfinite(value) for value in values)
                    or not math.isfinite(score)
                    or not 0.0 <= score <= 1.0):
                raise ValueError('model emitted non-finite detection')
            detections.append(Detection2D(
                class_name, score, values[0], values[1], values[2], values[3],
                source))
        return detections


def main(args=None):
    """Delegate the ROS1 process entrypoint to the read-only adapter."""
    from limo_cleanup_ros1_perception.ros1_adapter import main as adapter_main
    return adapter_main(args=args)


if __name__ == '__main__':
    raise SystemExit(main())
