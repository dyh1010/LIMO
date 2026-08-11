#!/usr/bin/env bash

set -o pipefail

if [[ -f /opt/ros/foxy/setup.bash ]]; then
  source /opt/ros/foxy/setup.bash
elif [[ -f /opt/ros/humble/setup.bash ]]; then
  source /opt/ros/humble/setup.bash
else
  echo 'FAIL: no supported ROS2 setup was found' >&2
  exit 2
fi

if [[ -f install/setup.bash ]]; then
  source install/setup.bash
else
  echo 'FAIL: run this script from a built workspace root' >&2
  exit 2
fi

set -u

export ROS_DOMAIN_ID=137
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces></General></Domain></CycloneDDS>'

zero_launch_log="$(mktemp)"
zero_launch_pid=''

stop_zero_launch() {
  if [[ -z "${zero_launch_pid}" ]]; then
    return
  fi
  kill -TERM -- "-${zero_launch_pid}" 2>/dev/null || true
  for shutdown_attempt in {1..30}; do
    if ! kill -0 "${zero_launch_pid}" 2>/dev/null; then
      break
    fi
    sleep 0.1
  done
  if kill -0 "${zero_launch_pid}" 2>/dev/null; then
    kill -KILL -- "-${zero_launch_pid}" 2>/dev/null || true
  fi
  wait "${zero_launch_pid}" 2>/dev/null || true
  zero_launch_pid=''
}

cleanup_zero_launch() {
  stop_zero_launch
  rm -f "${zero_launch_log}"
}
trap cleanup_zero_launch EXIT INT TERM

setsid ros2 launch limo_cleanup_bringup tracked_base_zero_output.launch.py \
  output_topic:=/test/cleanup/tracked_zero_output \
  >"${zero_launch_log}" 2>&1 &
zero_launch_pid=$!

if ! python3 scripts/smoke_test_tracked_zero_launch.py; then
  echo '===== zero-output launch log =====' >&2
  sed -n '1,240p' "${zero_launch_log}" >&2
  exit 1
fi

stop_zero_launch

remaining_nodes="$(ros2 node list --no-daemon --spin-time 1.0 2>&1)"
if echo "${remaining_nodes}" | grep -Eq \
    'cleanup_tracked_base_zero_output|cleanup_tracked_zero_launch_probe'; then
  echo "FAIL: zero-output smoke left a ROS node: ${remaining_nodes}" >&2
  exit 1
fi

echo 'PASS: zero-output launch smoke completed without a real /cmd_vel publisher'
