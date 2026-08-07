#!/usr/bin/env bash

set -euo pipefail

driver_package=${DABAI_DRIVER_PACKAGE:-orbbec_camera}
driver_launch_file=${DABAI_DRIVER_LAUNCH_FILE:-dabai.launch.py}

if ! command -v ros2 >/dev/null 2>&1; then
  echo 'ERROR: ros2 is not available; source the ROS 2 environment first.' >&2
  exit 2
fi

if ! ros2 pkg prefix "$driver_package" >/dev/null 2>&1; then
  echo "ERROR: ROS 2 package '$driver_package' is not installed." >&2
  echo 'Install the DaBai-compatible driver supplied with the robot first.' >&2
  exit 3
fi

echo "Starting camera only: ros2 launch $driver_package $driver_launch_file $*"
echo 'No LIMO base, navigation, arm, gripper, or cleanup executor is started.'
exec ros2 launch "$driver_package" "$driver_launch_file" "$@"
