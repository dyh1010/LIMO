#!/usr/bin/env python3
"""GUI-only JYU2C checkerboard collector; it never imports robot APIs."""

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

import cv2
import numpy as np


PATTERN = (11, 8)
SQUARE_SIZE_MM = 14.0
FLAGS = cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE
CAMERA_SERIAL = "JYU2C-2083-2603103"
CAMERA_VENDOR_ID = "1bcf"
CAMERA_MODEL_ID = "2281"
CAMERA_DEVICE = (
    "/dev/v4l/by-id/"
    "usb-JoyandAI_JYU2C-2083_JYU2C-2083-2603103-video-index0"
)


def view_feature(corners, width, height):
    points = corners.reshape(PATTERN[1], PATTERN[0], 2)
    quad = np.array(
        [points[0, 0], points[0, -1], points[-1, 0], points[-1, -1]],
        dtype=np.float64,
    )
    quad[:, 0] /= float(width)
    quad[:, 1] /= float(height)
    return quad.reshape(-1)


def diverse_enough(feature, accepted, threshold):
    if not accepted:
        return True
    return min(float(np.linalg.norm(feature - item)) for item in accepted) >= threshold


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default=CAMERA_DEVICE)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target", type=int, default=30)
    parser.add_argument("--max-seconds", type=float, default=180.0)
    parser.add_argument("--min-interval", type=float, default=0.75)
    parser.add_argument("--diversity", type=float, default=0.075)
    parser.add_argument("--min-blur", type=float, default=65.0)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.device != CAMERA_DEVICE:
        raise RuntimeError("jyu2c_stable_device_path_required")
    device_path = Path(args.device)
    if not device_path.is_symlink():
        raise RuntimeError("jyu2c_stable_device_symlink_missing")
    resolved_device = device_path.resolve(strict=True)
    if not resolved_device.name.startswith("video"):
        raise RuntimeError("jyu2c_stable_device_target_invalid")
    output = Path(args.output)
    output.mkdir(parents=False, exist_ok=False)
    selected_dir = output / "selected"
    selected_dir.mkdir()

    camera = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    if not camera.isOpened():
        raise RuntimeError("camera_open_failed")

    accepted_features = []
    records = []
    started = time.monotonic()
    last_saved = -math.inf
    window = "LIMO JYU2C Intrinsics Capture - q to stop"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 960, 720)

    try:
        while time.monotonic() - started < args.max_seconds:
            ok, frame = camera.read()
            if not ok or frame is None:
                continue
            height, width = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found, corners = cv2.findChessboardCornersSB(gray, PATTERN, flags=FLAGS)
            blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            preview = frame.copy()
            status = "show full 11x8 board"
            if found and len(corners) == PATTERN[0] * PATTERN[1]:
                cv2.drawChessboardCorners(preview, PATTERN, corners, True)
                feature = view_feature(corners, width, height)
                ready = (
                    blur >= args.min_blur
                    and time.monotonic() - last_saved >= args.min_interval
                    and diverse_enough(feature, accepted_features, args.diversity)
                )
                status = "hold still" if not ready else "accepted"
                if ready:
                    index = len(records)
                    path = selected_dir / f"view_{index:02d}.png"
                    # Calibration authority is the untouched camera frame.
                    # Detection overlays exist only in the GUI preview.
                    cv2.imwrite(str(path), frame)
                    accepted_features.append(feature)
                    records.append(
                        {
                            "index": index,
                            "path": str(path),
                            "unix_ns": time.time_ns(),
                            "blur": blur,
                            "feature": feature.tolist(),
                        }
                    )
                    last_saved = time.monotonic()
                    if len(records) >= args.target:
                        break

            cv2.rectangle(preview, (0, 0), (width, 66), (0, 0, 0), -1)
            cv2.putText(
                preview,
                f"accepted {len(records)}/{args.target} | corners 11x8 | square 14.00 mm",
                (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 0), 2,
            )
            cv2.putText(
                preview, f"{status} | blur {blur:.0f} | q=stop",
                (12, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.57, (255, 255, 255), 1,
            )
            cv2.imshow(window, preview)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()

    for record in records:
        record["sha256"] = sha256_file(Path(record["path"]))
    manifest = {
        "schema": "limo_jyu2c_checkerboard_intrinsics_capture/v1",
        "status": "CAPTURED_NOT_CALIBRATED",
        "camera": {
            "model": "JYU2C-2083",
            "serial": CAMERA_SERIAL,
            "usb_vendor_id": CAMERA_VENDOR_ID,
            "usb_model_id": CAMERA_MODEL_ID,
            "stable_device_path": args.device,
            "resolved_video_node_at_open": str(resolved_device),
            "v4l_index": 0,
        },
        "pattern_inner_corners": list(PATTERN),
        "square_size_mm": SQUARE_SIZE_MM,
        "selected_count": len(records),
        "target_count": args.target,
        "records": records,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "selected": len(records)}), flush=True)
    return 0 if len(records) >= 12 else 3


if __name__ == "__main__":
    raise SystemExit(main())
