"""Organize labeled images into a YOLO train/val dataset.

Copies image/label pairs into images/{train,val} and
labels/{train,val}, then writes data.yaml. Images without a label
file are skipped and reported instead of becoming silent negatives.
"""
import argparse
import random
import shutil
from pathlib import Path

IMG_EXTENSIONS = ('.jpg', '.jpeg', '.png')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--images', required=True,
                        help='Folder with the source photos')
    parser.add_argument('--labels', required=True,
                        help='Folder with YOLO .txt labels')
    parser.add_argument('--out', required=True,
                        help='Output dataset root')
    parser.add_argument('--val-ratio', type=float, default=0.15)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--class-name', default='plastic_bottle')
    args = parser.parse_args()

    images_dir = Path(args.images)
    labels_dir = Path(args.labels)
    out_dir = Path(args.out)

    pairs, skipped = [], []
    for image_path in sorted(images_dir.iterdir()):
        if image_path.suffix.lower() not in IMG_EXTENSIONS:
            continue
        label_path = labels_dir / (image_path.stem + '.txt')
        if label_path.exists():
            pairs.append((image_path, label_path))
        else:
            skipped.append(image_path.name)

    if not pairs:
        raise SystemExit('No labeled image pairs found')

    random.seed(args.seed)
    random.shuffle(pairs)
    val_count = max(1, round(len(pairs) * args.val_ratio))
    val_pairs, train_pairs = pairs[:val_count], pairs[val_count:]

    for split, items in (('train', train_pairs), ('val', val_pairs)):
        (out_dir / 'images' / split).mkdir(parents=True, exist_ok=True)
        (out_dir / 'labels' / split).mkdir(parents=True, exist_ok=True)
        for image_path, label_path in items:
            shutil.copy2(
                image_path, out_dir / 'images' / split / image_path.name)
            shutil.copy2(
                label_path, out_dir / 'labels' / split / label_path.name)

    data_yaml = (
        f'path: {out_dir.resolve()}\n'
        'train: images/train\n'
        'val: images/val\n'
        'names:\n'
        f'  0: {args.class_name}\n')
    (out_dir / 'data.yaml').write_text(data_yaml, encoding='utf-8')

    print(f'train={len(train_pairs)} val={len(val_pairs)} '
          f'skipped_no_label={len(skipped)}')
    print(f'dataset root: {out_dir.resolve()}')
    if skipped:
        print('skipped (no label file):')
        for name in skipped:
            print(f'  {name}')


if __name__ == '__main__':
    main()