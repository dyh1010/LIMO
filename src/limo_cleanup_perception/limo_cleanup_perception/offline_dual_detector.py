"""Run bottle/bin perception on images without requiring ROS or hardware."""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
from ultralytics import YOLO

from limo_cleanup_perception.perception_core import (
    Detection2D,
    bin_opening_region,
    classify_bottles,
    select_target_bin,
    select_target_bottle,
)
from limo_cleanup_perception.target_contract import (
    EXPECTED_MODEL_SHA256,
    require_single_class_model,
)


IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp'}


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--image', type=Path)
    source.add_argument('--input-dir', type=Path)
    parser.add_argument('--bottle-model', type=Path, required=True)
    parser.add_argument('--bin-model', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--confidence', type=float, default=0.5)
    parser.add_argument('--iou', type=float, default=0.45)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--device', default='0')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--in-bin-overlap', type=float, default=0.30)
    parser.add_argument('--opening-height-ratio', type=float, default=0.62)
    parser.add_argument('--opening-margin-ratio', type=float, default=0.0)
    return parser.parse_args()


def to_detections(result, label, source):
    detections = []
    if result.boxes is None:
        return detections
    coordinates = result.boxes.xyxy.detach().cpu().tolist()
    confidences = result.boxes.conf.detach().cpu().tolist()
    for coordinates_row, confidence in zip(coordinates, confidences):
        detections.append(Detection2D(
            label=label,
            confidence=float(confidence),
            x1=float(coordinates_row[0]),
            y1=float(coordinates_row[1]),
            x2=float(coordinates_row[2]),
            y2=float(coordinates_row[3]),
            source=source,
        ))
    return detections


def detection_payload(detection):
    if detection is None:
        return None
    return {
        'label': detection.label,
        'confidence': detection.confidence,
        'box': [detection.x1, detection.y1, detection.x2, detection.y2],
    }


def draw_detection(image, detection, color, text):
    first = (round(detection.x1), round(detection.y1))
    second = (round(detection.x2), round(detection.y2))
    cv2.rectangle(image, first, second, color, 3)
    cv2.putText(
        image, text, (first[0], max(20, first[1] - 6)),
        cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2,
    )


def collect_images(cfg):
    if cfg.image is not None:
        return [cfg.image]
    images = [
        path for path in sorted(cfg.input_dir.iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    return images[:cfg.limit] if cfg.limit is not None else images


def main():
    cfg = parse_args()
    for label, path in (
            ('plastic_bottle', cfg.bottle_model),
            ('trash_bin', cfg.bin_model)):
        if _sha256_file(path) != EXPECTED_MODEL_SHA256[label]:
            raise SystemExit(label + ' model SHA-256 mismatch')
    images = collect_images(cfg)
    if not images:
        raise RuntimeError('No input images found')
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    bottle_model = YOLO(str(cfg.bottle_model))
    bin_model = YOLO(str(cfg.bin_model))
    try:
        require_single_class_model(
            bottle_model.names, 'plastic_bottle')
        require_single_class_model(bin_model.names, 'trash_bin')
    except ValueError as error:
        raise RuntimeError(str(error)) from error
    summary = []

    for index, image_path in enumerate(images, start=1):
        image = cv2.imread(str(image_path))
        if image is None:
            print(f'skip unreadable image: {image_path}', flush=True)
            continue
        bottle_result = bottle_model.predict(
            source=image, conf=cfg.confidence, iou=cfg.iou,
            imgsz=cfg.imgsz, device=cfg.device, verbose=False)[0]
        bin_result = bin_model.predict(
            source=image, conf=cfg.confidence, iou=cfg.iou,
            imgsz=cfg.imgsz, device=cfg.device, verbose=False)[0]
        bottles = to_detections(
            bottle_result, 'plastic_bottle', 'bottle_model')
        bins = to_detections(bin_result, 'trash_bin', 'bin_model')
        classified = classify_bottles(
            bottles, bins,
            overlap_threshold=cfg.in_bin_overlap,
            horizontal_margin_ratio=cfg.opening_margin_ratio,
            opening_height_ratio=cfg.opening_height_ratio,
        )
        target_bottle = select_target_bottle(classified.active)
        target_bin = select_target_bin(bins)

        annotated = image.copy()
        for bin_detection in bins:
            draw_detection(
                annotated, bin_detection, (0, 165, 255),
                f'bin {bin_detection.confidence:.2f}')
            opening = bin_opening_region(
                bin_detection, cfg.opening_margin_ratio,
                cfg.opening_height_ratio)
            draw_detection(
                annotated, opening, (255, 220, 0), 'bin opening ROI')
        for bottle in classified.already_in_bin:
            draw_detection(
                annotated, bottle, (140, 140, 140),
                f'ignored in-bin {bottle.confidence:.2f}')
        for bottle in classified.active:
            prefix = 'TARGET' if bottle == target_bottle else 'bottle'
            draw_detection(
                annotated, bottle, (40, 220, 40),
                f'{prefix} {bottle.confidence:.2f}')

        output_image = cfg.output_dir / image_path.name
        cv2.imwrite(str(output_image), annotated)
        record = {
            'image': str(image_path),
            'output_image': str(output_image),
            'state': (
                'bottle_target_ready' if target_bottle is not None
                else 'no_actionable_bottle'),
            'bottles_total': len(bottles),
            'bottles_active': len(classified.active),
            'bottles_already_in_bin': len(classified.already_in_bin),
            'bins': len(bins),
            'target_bottle': detection_payload(target_bottle),
            'target_bin': detection_payload(target_bin),
        }
        summary.append(record)
        (cfg.output_dir / f'{image_path.stem}.json').write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding='utf-8')
        print(
            f'[{index}/{len(images)}] {image_path.name}: '
            f'bottles={len(bottles)} active={len(classified.active)} '
            f'in_bin={len(classified.already_in_bin)} bins={len(bins)}',
            flush=True,
        )

    (cfg.output_dir / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding='utf-8')


if __name__ == '__main__':
    main()
