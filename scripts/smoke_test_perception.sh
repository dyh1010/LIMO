#!/usr/bin/env bash

set -eo pipefail

source /home/dyh/robotics/env/ros2_wsl.sh
source /home/dyh/robotics/workspaces/limo_ws/install/setup.bash
source /home/dyh/robotics/workspaces/limo_cleanup_ws/install/setup.bash

set -u

test_dir=$(mktemp -d /tmp/limo_cleanup_perception.XXXXXX)
launch_pid=''
status_pid=''
detection_pid=''

stop_process() {
  local pid=$1
  if [[ -n "$pid" ]] && kill -0 -- "-$pid" 2>/dev/null; then
    kill -INT -- "-$pid" 2>/dev/null || true
    for _ in {1..40}; do
      if ! kill -0 -- "-$pid" 2>/dev/null; then
        break
      fi
      sleep 0.05
    done
    if kill -0 -- "-$pid" 2>/dev/null; then
      kill -TERM -- "-$pid" 2>/dev/null || true
      sleep 0.2
    fi
    if kill -0 -- "-$pid" 2>/dev/null; then
      kill -KILL -- "-$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
  fi
}

cleanup() {
  stop_process "$status_pid"
  stop_process "$detection_pid"
  stop_process "$launch_pid"
}

trap cleanup EXIT

start_system() {
  local launch_log=$1
  shift
  setsid ros2 launch limo_cleanup_bringup cleanup_system.launch.py \
    "$@" > "$launch_log" 2>&1 &
  launch_pid=$!
  sleep 2
}

stop_system() {
  stop_process "$launch_pid"
  launch_pid=''
  sleep 1
}

start_status_capture() {
  local status_log=$1
  setsid ros2 topic echo /cleanup/status > "$status_log" 2>&1 &
  status_pid=$!
  sleep 0.5
}

stop_captures() {
  stop_process "$status_pid"
  status_pid=''
}

normal_launch="$test_dir/normal_launch.log"
normal_status="$test_dir/normal_status.log"

start_system "$normal_launch" \
  mock_step_duration:=0.10 \
  mock_detection_delay:=0.30 \
  detection_timeout:=2.0
start_status_capture "$normal_status"
ros2 topic pub --once \
  /cleanup/command_text \
  std_msgs/msg/String \
  "{data: '捡纸盒'}" > /dev/null
sleep 3
stop_captures
stop_system

grep -q 'state: object_detected' "$normal_status"
grep -q 'state: succeeded' "$normal_status"
grep -q 'Published detection .*paper_box' "$normal_launch"
grep -q 'Accepted detection .*paper_box' "$normal_launch"
grep -q 'Received detection .*paper_box' "$normal_launch"
echo 'PASS normal: matching detection passed the gate and unlocked execution'

timeout_launch="$test_dir/timeout_launch.log"
timeout_status="$test_dir/timeout_status.log"

start_system "$timeout_launch" \
  use_mock_perception:=false \
  mock_step_duration:=0.10 \
  detection_timeout:=0.60
start_status_capture "$timeout_status"
ros2 topic pub --once \
  /cleanup/command_text \
  std_msgs/msg/String \
  "{data: '捡塑料瓶'}" > /dev/null
sleep 2
stop_captures
stop_system

grep -q 'state: object_not_found' "$timeout_status"
echo 'PASS timeout: missing detection failed safely'

cancel_launch="$test_dir/cancel_launch.log"
cancel_status="$test_dir/cancel_status.log"

start_system "$cancel_launch" \
  mock_step_duration:=0.10 \
  mock_detection_delay:=3.0 \
  detection_timeout:=5.0
start_status_capture "$cancel_status"
ros2 topic pub --once \
  /cleanup/command_text \
  std_msgs/msg/String \
  "{data: '捡易拉罐'}" > /dev/null
sleep 0.5
ros2 topic pub --once \
  /cleanup/command_text \
  std_msgs/msg/String \
  "{data: '停止任务'}" > /dev/null
sleep 1.5
stop_captures
stop_system

grep -q 'state: cancelled' "$cancel_status"
echo 'PASS cancel: waiting task was cancelled'

gate_launch="$test_dir/gate_launch.log"
gate_status="$test_dir/gate_status.log"

start_system "$gate_launch" \
  mock_step_duration:=0.10 \
  mock_detection_delay:=0.30 \
  mock_detection_confidence:=0.10 \
  detection_timeout:=1.0
start_status_capture "$gate_status"
ros2 topic pub --once \
  /cleanup/command_text \
  std_msgs/msg/String \
  "{data: '捡塑料瓶'}" > /dev/null
sleep 2.5
stop_captures
stop_system

grep -q 'state: object_not_found' "$gate_status"
grep -q 'Rejected detection .*low_confidence' "$gate_launch"
echo 'PASS gate: low-confidence detection was rejected and execution failed safely'

echo "Smoke-test logs: $test_dir"
