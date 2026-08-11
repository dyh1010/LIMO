#!/usr/bin/env bash

set -o pipefail

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-137}"
export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"

if [[ -f /opt/ros/foxy/setup.bash ]]; then
  source /opt/ros/foxy/setup.bash
else
  echo 'FAIL: /opt/ros/foxy/setup.bash is missing' >&2
  exit 2
fi

if [[ -f /home/agilex/limo_ros2_ws/install/setup.bash ]]; then
  source /home/agilex/limo_ros2_ws/install/setup.bash
else
  echo 'WARN: vendor limo_ros2_ws overlay is missing' >&2
fi

if [[ -f /home/agilex/limo_cleanup_ws/install/setup.bash ]]; then
  source /home/agilex/limo_cleanup_ws/install/setup.bash
fi

# Foxy and colcon setup files may read optional variables before defining
# them. Enable nounset only after both environments have been sourced.
set -u

section() {
  echo
  echo "===== $1 ====="
}

section HOST
hostname
uname -a
date --iso-8601=seconds
echo "ROS_DISTRO=${ROS_DISTRO:-unset}"
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY}"

section LIMO_BASE_PACKAGE
ros2 pkg prefix limo_base 2>&1 || true

section RELEVANT_PROCESSES
ps -eo pid,etimes,args | grep -E \
  'limo_base|nav2|navigation|teleop|cmd_vel|cleanup_tracked_base' \
  | grep -v -E 'grep|robot_tracked_readonly_audit' || true

section ROS_NODES
ros2 node list --no-daemon --spin-time 2.0 2>&1 || true

section MOTION_TOPICS
ros2 topic list -t --no-daemon --spin-time 2.0 2>&1 \
  | grep -E 'cmd_vel|odom|imu|limo.*status|battery|motion|safety' || true

section CMD_VEL_OWNERSHIP
ROS2CLI_NO_DAEMON=1 timeout -k 2 8 \
  ros2 topic info /cmd_vel --verbose 2>&1 || true

for topic in /cmd_vel_nav /cmd_vel_teleop /limo/vel_cmd; do
  section "OWNERSHIP ${topic}"
  ROS2CLI_NO_DAEMON=1 timeout -k 2 8 \
    ros2 topic info "${topic}" --verbose 2>&1 || true
done

section DEVICE_LINKS
ls -l /dev/limo* /dev/ttyTHS* /dev/ttyUSB* /dev/ttyACM* 2>&1 || true

section DEVICE_IDENTITY_AND_OWNERS
for device in /dev/ttyUSB0 /dev/ttyACM0; do
  if [[ ! -e "${device}" ]]; then
    echo "${device}: missing"
    continue
  fi
  echo "--- ${device} ---"
  udevadm info --query=property --name="${device}" 2>/dev/null \
    | grep -E \
      '^(DEVNAME|ID_BUS|ID_VENDOR_ID|ID_MODEL_ID|ID_SERIAL_SHORT|ID_USB_DRIVER)=' \
    || true
  fuser -v "${device}" 2>&1 || true
done

section PLATFORM_UART_IDENTITY_AND_OWNERS
for device in /dev/ttyTHS0 /dev/ttyTHS1 /dev/ttyTHS3 /dev/ttyTHS4; do
  if [[ ! -e "${device}" ]]; then
    echo "${device}: missing"
    continue
  fi
  echo "--- ${device} ---"
  udevadm info --query=property --name="${device}" 2>/dev/null \
    | grep -E '^(DEVNAME|DEVPATH|ID_PATH|ID_PATH_TAG|MAJOR|MINOR)=' \
    || true
  sys_device="$(readlink -f "/sys/class/tty/${device##*/}/device" \
    2>/dev/null || true)"
  echo "SYS_DEVICE=${sys_device:-unknown}"
  if [[ -n "${sys_device}" ]]; then
    echo "DRIVER=$(readlink -f "${sys_device}/driver" 2>/dev/null || true)"
    echo "OF_NODE=$(readlink -f "${sys_device}/of_node" 2>/dev/null || true)"
    for property in name status compatible; do
      property_path="${sys_device}/of_node/${property}"
      if [[ -f "${property_path}" ]]; then
        printf 'OF_%s=' "${property^^}"
        tr '\000' '\n' < "${property_path}" 2>/dev/null || true
      fi
    done
  fi
  fuser -v "${device}" 2>&1 || true
done

section DEVICE_TREE_SERIAL_ALIASES
for alias_path in /proc/device-tree/aliases/serial*; do
  if [[ ! -f "${alias_path}" ]]; then
    continue
  fi
  printf '%s=' "$(basename "${alias_path}")"
  tr -d '\000' < "${alias_path}" 2>/dev/null || true
  echo
done

section RESULT
echo 'READ_ONLY_AUDIT_COMPLETE'
echo 'AUDIT_STATUS=EVIDENCE_CAPTURED_NOT_ACCEPTANCE_PASS'
echo 'No velocity, navigation, arm, gripper, power or actuator command was sent.'
