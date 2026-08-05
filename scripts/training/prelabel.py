"""Auto-prelabel bottle photos with a COCO-pretrained YOLO model.

Runs a COCO-pretrained detector over a folder of photos and writes
YOLO-format labels (class 0 = plastic_bottle) next to them. Images
without a confident bottle detection are skipped and reported, so
they can be labeled by hand instead of silently becoming negatives.
"""
import argparse
from pathlib import Path

from ultralytics import YOLO

TARGET_CLASS_ID = 0
IMG_EXTENSIONS = ('.jpg', '.jpeg', '.png')


def resolve_source_class(model: YOLO, configured: int | None) -> int:
    """Choose the bottle class emitted by a COCO or fine-tuned model."""
    if configured is not None:
        return configured

    names = model.names
    if len(names) == 1:
        return next(iter(names))

    for class_id, name in names.items():
        if name in ('bottle', 'plastic_bottle'):
            return class_id

    raise SystemExit(
        'Cannot infer the source bottle class; pass --source-class explicitly')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--images', required=True,
                        help='Folder with the photos to label')
    parser.add_argument('--labels', required=True,
                        help='Output folder for YOLO .txt labels')
    parser.add_argument('--weights', default='yolov8n.pt',
                        help='Pretrained weights for prelabeling')
    parser.add_argument('--conf', type=float, default=0.25,
                        help='Minimum confidence for a prelabel box')
    parser.add_argument('--device', default='0')
    parser.add_argument(
        '--source-class', type=int, default=None,
        help=('Class ID produced by the source model. By default it is '
              'inferred from bottle/plastic_bottle or a one-class model.'))
    parser.add_argument(
        '--max-boxes', type=int, default=0,
        help='Keep at most this many highest-confidence boxes (0 = all)')
    args = parser.parse_args()

    images_dir = Path(args.images)
    labels_dir = Path(args.labels)
    labels_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(
        p for p in images_dir.iterdir()
        if p.suffix.lower() in IMG_EXTENSIONS)
    if not images:
        raise SystemExit(f'No images found in {images_dir}')

    model = YOLO(args.weights)
    source_class = resolve_source_class(model, args.source_class)
    print(f'source_class={source_class} name={model.names[source_class]}')
    labeled, missed, multi = 0, [], []

    for image_path in images:
        results = model.predict(
            str(image_path), conf=args.conf,
            device=args.device, verbose=False)[0]
        boxes = [
            box for box in results.boxes
            if int(box.cls) == source_class]
        boxes.sort(key=lambda box: float(box.conf), reverse=True)
        if args.max_boxes > 0:
            boxes = boxes[:args.max_boxes]
        if not boxes:
            missed.append(image_path.name)
            continue
        lines = []
        for box in boxes:
            x, y, w, h = box.xywhn[0].tolist()
            lines.append(
                f'{TARGET_CLASS_ID} {x:.6f} {y:.6f} {w:.6f} {h:.6f}')
        (labels_dir / (image_path.stem + '.txt')).write_text(
            '\n'.join(lines) + '\n', encoding='utf-8')
        labeled += 1
        if len(boxes) > 1:
            multi.append((image_path.name, len(boxes)))

    print(f'total={len(images)} labeled={labeled} missed={len(missed)}')
    if missed:
        print('missed (label these by hand):')
        for name in missed:
            print(f'  {name}')
    if multi:
        print('multiple boxes (review these):')
        for name, count in multi:
            print(f'  {name}: {count} boxes')


if __name__ == '__main__':
    main()
