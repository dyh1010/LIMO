#!/usr/bin/env bash

set -eo pipefail

source /home/dyh/robotics/env/ros2_wsl.sh
source /home/dyh/robotics/workspaces/limo_ws/install/setup.bash
source /home/dyh/robotics/workspaces/limo_cleanup_ws/install/setup.bash

set -u

test_dir=$(mktemp -d /tmp/limo_real_perception_startup.XXXXXX)
launch_log="$test_dir/launch.log"
launch_pid=''

stop_launch() {
  if [[ -n "$launch_pid" ]] && kill -0 -- "-$launch_pid" 2>/dev/null; then
    kill -INT -- "-$launch_pid" 2>/dev/null || true
    for _ in {1..60}; do
      if ! kill -0 -- "-$launch_pid" 2>/dev/null; then
        break
      fi
      sleep 0.10
    done
    if kill -0 -- "-$launch_pid" 2>/dev/null; then
      kill -TERM -- "-$launch_pid" 2>/dev/null || true
    fi
    wait "$launch_pid" 2>/dev/null || true
  fi
}

trap stop_launch EXIT

setsid ros2 launch limo_cleanup_bringup real_perception_only.launch.py \
  start_camera:=false \
  detector_device:=cpu >"$launch_log" 2>&1 &
launch_pid=$!

ready=false
for _ in {1..120}; do
  if grep -q 'Dual-model detector ready' "$launch_log"; then
    ready=true
    break
  fi
  if ! kill -0 "$launch_pid" 2>/dev/null; then
    break
  fi
  sleep 0.25
done

if grep -Eq 'Traceback|ModuleNotFoundError|ImportError' "$launch_log"; then
  cat "$launch_log"
  echo 'FAIL: real perception startup raised an import/runtime error' >&2
  exit 1
fi

if [[ "$ready" != true ]]; then
  cat "$launch_log"
  echo 'FAIL: real perception node did not become ready' >&2
  exit 1
fi

if ! grep -q 'always_active=True' "$launch_log"; then
  cat "$launch_log"
  echo 'FAIL: read-only perception did not enable always_active' >&2
  exit 1
fi

echo 'PASS: read-only perception loaded both models in always-active mode'
echo "Smoke-test log: $launch_log"
