#!/usr/bin/env bash

set -euo pipefail

if ! command -v ros2 >/dev/null 2>&1; then
  echo 'ERROR: ros2 is not available; source the ROS 2 environment first.' >&2
  exit 2
fi

if ! ros2 pkg prefix limo_cleanup_bringup >/dev/null 2>&1; then
  echo 'ERROR: limo_cleanup_bringup is not installed/sourced.' >&2
  exit 3
fi

echo 'Running strict read-only acceptance.'
echo 'This launch contains no base, navigation, arm, gripper, or executor node.'
exec ros2 launch limo_cleanup_bringup \
  hardware_readonly_acceptance.launch.py "$@"
