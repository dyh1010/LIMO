#!/usr/bin/env bash

set -eo pipefail

source /home/dyh/robotics/env/ros2_wsl.sh
source /home/dyh/robotics/workspaces/limo_cleanup_ws/install/setup.bash

set -u

test_dir=$(mktemp -d /tmp/limo_cleanup_gripper.XXXXXX)
launch_pid=''

stop_launch() {
  if [[ -n "$launch_pid" ]] && kill -0 -- "-$launch_pid" 2>/dev/null; then
    kill -INT -- "-$launch_pid" 2>/dev/null || true
    for _ in {1..40}; do
      if ! kill -0 -- "-$launch_pid" 2>/dev/null; then
        break
      fi
      sleep 0.05
    done
    if kill -0 -- "-$launch_pid" 2>/dev/null; then
      kill -TERM -- "-$launch_pid" 2>/dev/null || true
    fi
    wait "$launch_pid" 2>/dev/null || true
  fi
  launch_pid=''
}

trap stop_launch EXIT

start_launch() {
  local log=$1
  shift
  setsid ros2 launch limo_cleanup_bringup gripper_control.launch.py \
    "$@" > "$log" 2>&1 &
  launch_pid=$!
  sleep 2
}

dry_log="$test_dir/dry_run_launch.log"
open_log="$test_dir/open_goal.log"
partial_log="$test_dir/partial_goal.log"

start_launch "$dry_log"
ros2 action send_goal \
  /cleanup/gripper \
  limo_cleanup_interfaces/action/ControlGripper \
  "{command: 1, position: 0.0, speed: 0.2, verify: true}" \
  --feedback > "$open_log"
ros2 action send_goal \
  /cleanup/gripper \
  limo_cleanup_interfaces/action/ControlGripper \
  "{command: 3, position: 0.35, speed: 0.15, verify: true}" \
  --feedback > "$partial_log"

grep -q 'success: true' "$open_log"
grep -q 'final_state: succeeded' "$open_log"
grep -q 'success: true' "$partial_log"
grep -q 'commanded_position: 0.349' "$partial_log"
grep -q 'backend=dry_run' "$dry_log"
grep -q 'allow_hardware_motion=False' "$dry_log"
echo 'PASS: dry-run open and partial-grasp commands were verified'
stop_launch

blocked_log="$test_dir/blocked_launch.log"
blocked_goal="$test_dir/blocked_goal.log"
start_launch "$blocked_log" backend:=pymycobot
ros2 action send_goal \
  /cleanup/gripper \
  limo_cleanup_interfaces/action/ControlGripper \
  "{command: 2, position: 0.0, speed: 0.2, verify: true}" \
  > "$blocked_goal"

grep -q 'success: false' "$blocked_goal"
grep -q 'final_state: motion_not_authorized' "$blocked_goal"
grep -q 'hardware motion is disabled' "$blocked_log"
echo 'PASS: pymycobot backend stayed blocked without explicit authorization'

echo "Smoke-test logs: $test_dir"
