#!/usr/bin/env bash

set -o pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace_root="$(cd "${script_dir}/.." && pwd)"
setup_file="${TRACKED_SMOKE_SETUP:-${workspace_root}/install/setup.bash}"

if [[ -f /opt/ros/foxy/setup.bash ]]; then
  source /opt/ros/foxy/setup.bash
elif [[ -f /opt/ros/humble/setup.bash ]]; then
  source /opt/ros/humble/setup.bash
else
  echo 'FAIL: no supported ROS2 setup was found' >&2
  exit 2
fi
if [[ ! -f "${setup_file}" ]]; then
  echo "FAIL: workspace setup is missing: ${setup_file}" >&2
  exit 2
fi
source "${setup_file}"

set -u

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_LOCALHOST_ONLY=0
export ROS_DOMAIN_ID=137
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces></General></Domain></CycloneDDS>'

launch_log="$(mktemp)"
launch_pid=''

cleanup() {
  if [[ -n "${launch_pid}" ]]; then
    if kill -0 "${launch_pid}" 2>/dev/null; then
      kill -INT -- "-${launch_pid}" 2>/dev/null || true
      for attempt in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "${launch_pid}" 2>/dev/null || break
        sleep 0.2
      done
    fi
    if kill -0 "${launch_pid}" 2>/dev/null; then
      kill -TERM -- "-${launch_pid}" 2>/dev/null || true
      for attempt in 1 2 3 4 5; do
        kill -0 "${launch_pid}" 2>/dev/null || break
        sleep 0.2
      done
    fi
    if kill -0 "${launch_pid}" 2>/dev/null; then
      kill -KILL -- "-${launch_pid}" 2>/dev/null || true
    fi
    wait "${launch_pid}" 2>/dev/null || true
  fi
  rm -f "${launch_log}"
}
trap cleanup EXIT INT TERM

setsid ros2 launch limo_cleanup_bringup tracked_base_zero_output.launch.py \
  >"${launch_log}" 2>&1 &
launch_pid=$!

if ! timeout -k 2 15 \
    python3 "${script_dir}/verify_tracked_zero_output.py"; then
  echo '===== zero-output guard launch log =====' >&2
  sed -n '1,160p' "${launch_log}" >&2
  exit 1
fi

if ! kill -0 "${launch_pid}" 2>/dev/null; then
  echo 'FAIL: zero-output launch exited before verification completed' >&2
  sed -n '1,160p' "${launch_log}" >&2
  exit 1
fi

echo 'TRACKED_ZERO_GUARD_SMOKE_PASS'
echo 'The vendor limo_base driver was not started.'
