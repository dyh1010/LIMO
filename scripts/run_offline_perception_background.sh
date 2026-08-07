#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 OUTPUT_DIR [offline_dual_detector arguments...]" >&2
  exit 2
fi

output_dir=$1
shift
mkdir -p "$output_dir"
log_file="$output_dir/offline_dual_detector.log"
pid_file="$output_dir/offline_dual_detector.pid"
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
detector="$repo_root/src/limo_cleanup_perception/limo_cleanup_perception/offline_dual_detector.py"
source /home/dyh/robotics/train/venv/bin/activate
export PYTHONPATH="$repo_root/src/limo_cleanup_perception"

nohup python "$detector" --output-dir "$output_dir" "$@" \
  >"$log_file" 2>&1 &
pid=$!
printf '%s\n' "$pid" >"$pid_file"
echo "started pid=$pid log=$log_file"
