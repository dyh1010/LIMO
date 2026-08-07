#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
detector="$repo_root/src/limo_cleanup_perception/limo_cleanup_perception/offline_dual_detector.py"
source /home/dyh/robotics/train/venv/bin/activate
export PYTHONPATH="$repo_root/src/limo_cleanup_perception"
exec python "$detector" "$@"
