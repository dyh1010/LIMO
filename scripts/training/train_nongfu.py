"""Train and export the Nongfu bottle detector."""
import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True,
                        help='Path to data.yaml')
    parser.add_argument('--weights', default='yolov8n.pt',
                        help='Pretrained weights to start from')
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--batch', type=int, default=16)
    parser.add_argument('--patience', type=int, default=20)
    parser.add_argument('--project',
                        default=str(Path.home() / 'robotics/train/runs'))
    parser.add_argument('--name', default='nongfu_v1')
    parser.add_argument('--device', default='0')
    parser.add_argument('--export-to', default='',
                        help='Directory that receives best.pt and ONNX')
    args = parser.parse_args()

    model = YOLO(args.weights)
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        device=args.device,
        project=args.project,
        name=args.name,
    )

    save_dir = Path(results.save_dir)
    best_pt = save_dir / 'weights' / 'best.pt'
    print(f'best weights: {best_pt}')

    metrics = model.val(data=args.data, device=args.device)
    print(f'mAP50-95={metrics.box.map:.4f} '
          f'mAP50={metrics.box.map50:.4f}')

    onnx_path = model.export(format='onnx', imgsz=args.imgsz)
    print(f'onnx: {onnx_path}')

    if args.export_to:
        export_dir = Path(args.export_to)
        export_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best_pt, export_dir / 'nongfu_yolov8n_best.pt')
        shutil.copy2(onnx_path, export_dir / 'nongfu_yolov8n_best.onnx')
        print(f'exported best.pt and ONNX to {export_dir}')


if __name__ == '__main__':
    main()