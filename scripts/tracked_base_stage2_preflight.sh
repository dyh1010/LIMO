#!/usr/bin/env bash

set -o pipefail

requested_ros_domain_id="${ROS_DOMAIN_ID:-137}"
requested_ros_localhost_only="${ROS_LOCALHOST_ONLY:-0}"
export ROS_DOMAIN_ID=137
export ROS_LOCALHOST_ONLY=0

if [[ -f /opt/ros/foxy/setup.bash ]]; then
  source /opt/ros/foxy/setup.bash
else
  echo 'FAIL: /opt/ros/foxy/setup.bash is missing' >&2
  exit 2
fi

if [[ -f /home/agilex/limo_ros2_ws/install/setup.bash ]]; then
  source /home/agilex/limo_ros2_ws/install/setup.bash
else
  echo 'FAIL: vendor limo_ros2_ws overlay is missing' >&2
  exit 2
fi

if [[ -f /home/agilex/limo_cleanup_ws/install/setup.bash ]]; then
  source /home/agilex/limo_cleanup_ws/install/setup.bash
fi

set -u

status=0
port="${TRACKED_BASE_PORT:-/dev/ttyTHS0}"
expected_sysfs_device="${TRACKED_BASE_EXPECTED_SYSFS_DEVICE:-}"
expected_driver="${TRACKED_BASE_EXPECTED_DRIVER:-}"

pass() {
  echo "PASS: $1"
}

fail() {
  echo "FAIL: $1" >&2
  status=1
}

echo '===== TOOL PREREQUISITES ====='
for required_command in fuser grep id ps readlink ros2 systemctl timeout tr; do
  if command -v "${required_command}" >/dev/null 2>&1; then
    pass "required command is available: ${required_command}"
  else
    fail "required command is missing: ${required_command}"
  fi
done
if [[ "${status}" -ne 0 ]]; then
  echo 'STAGE2_PREFLIGHT_BLOCKED'
  echo 'Do not start limo_base or the tracked-base gateway.'
  exit "${status}"
fi

echo '===== DDS DISCOVERY CONTEXT ====='
if [[ "${requested_ros_domain_id}" == '137' ]]; then
  pass 'ROS_DOMAIN_ID matches the integration baseline 137'
else
  fail "caller requested ROS_DOMAIN_ID=${requested_ros_domain_id}; use the integration baseline 137"
fi
if [[ "${requested_ros_localhost_only}" == '0' ]]; then
  pass 'ROS_LOCALHOST_ONLY=0 permits inspection of the complete integration graph'
else
  fail "caller requested ROS_LOCALHOST_ONLY=${requested_ros_localhost_only}; localhost isolation can hide publishers"
fi
for discovery_variable in \
    ROS_DISCOVERY_SERVER CYCLONEDDS_URI FASTRTPS_DEFAULT_PROFILES_FILE; do
  discovery_value="${!discovery_variable:-}"
  if [[ -n "${discovery_value}" ]]; then
    fail "${discovery_variable} is set; custom discovery can hide ROS participants"
  else
    pass "${discovery_variable} is unset"
  fi
done

require_confirmation() {
  name="$1"
  description="$2"
  value="${!name:-}"
  if [[ "${value}" == 'YES' ]]; then
    pass "${description}"
  else
    fail "${description}; export ${name}=YES only after现场签字"
  fi
}

echo '===== EXPLICIT PHYSICAL CONFIRMATIONS ====='
require_confirmation \
  TRACKED_BASE_PHYSICAL_CHECKLIST_CONFIRMED \
  '履带、黄色模式灯、车门间隙和软围挡已确认'
require_confirmation \
  TRACKED_BASE_ESTOP_TESTED \
  '现场物理急停或断电已独立测试'
require_confirmation \
  TRACKED_BASE_COMMAND_MODE_WRITE_ACK \
  '已知原厂 limo_base 启动会发送 0x421 commanded-mode 帧'

echo
echo '===== PORT IDENTITY AND OWNERSHIP ====='
if [[ "${port}" != '/dev/ttyTHS0' ]]; then
  fail "unexpected base port ${port}; only /dev/ttyTHS0 is admitted"
elif [[ ! -c "${port}" ]]; then
  fail "${port} is missing or is not a character device"
else
  pass "${port} exists as a character device"
fi

tty_name="${port##*/}"
actual_sysfs_device="$(readlink -f "/sys/class/tty/${tty_name}/device" \
  2>/dev/null || true)"
actual_driver="$(readlink -f "/sys/class/tty/${tty_name}/device/driver" \
  2>/dev/null || true)"
if [[ -z "${expected_sysfs_device}" ]]; then
  fail 'TRACKED_BASE_EXPECTED_SYSFS_DEVICE is unset; record it during level-1 audit'
elif [[ "${actual_sysfs_device}" != "${expected_sysfs_device}" ]]; then
  fail "sysfs identity mismatch: expected ${expected_sysfs_device}, got ${actual_sysfs_device:-missing}"
else
  pass "sysfs identity matches ${actual_sysfs_device}"
fi
if [[ -z "${expected_driver}" ]]; then
  fail 'TRACKED_BASE_EXPECTED_DRIVER is unset; record it during level-1 audit'
elif [[ "${actual_driver}" != "${expected_driver}" ]]; then
  fail "driver mismatch: expected ${expected_driver}, got ${actual_driver:-missing}"
else
  pass "driver identity matches ${actual_driver}"
fi

port_owners="$(fuser "${port}" 2>&1)"
fuser_status=$?
if [[ "${fuser_status}" -eq 0 ]]; then
  fail "${port} is already owned by PID(s): ${port_owners}"
elif [[ "${fuser_status}" -eq 1 \
    && -z "${port_owners//[[:space:]]/}" ]]; then
  pass "${port} has no current owner"
else
  fail "could not prove ${port} ownership (fuser exit ${fuser_status}): ${port_owners}"
fi

if id -nG | tr ' ' '\n' | grep -qx 'dialout'; then
  pass 'current user belongs to dialout'
else
  fail 'current user is not a member of dialout'
fi

grep -Eq '(^|[[:space:]])console=ttyTHS0([,[:space:]]|$)' /proc/cmdline
console_status=$?
if [[ "${console_status}" -eq 0 ]]; then
  fail 'ttyTHS0 is configured as a kernel console'
elif [[ "${console_status}" -eq 1 ]]; then
  pass 'ttyTHS0 is not listed as a kernel console'
else
  fail "could not inspect /proc/cmdline (grep exit ${console_status})"
fi

getty_state="$(systemctl is-active serial-getty@ttyTHS0.service 2>&1)"
getty_status=$?
if [[ "${getty_status}" -eq 0 ]]; then
  fail 'serial-getty@ttyTHS0.service is active'
elif [[ "${getty_status}" -eq 3 && "${getty_state}" == 'inactive' ]]; then
  pass 'serial-getty@ttyTHS0.service is not active'
else
  fail "could not prove serial-getty inactive (systemctl exit ${getty_status}): ${getty_state}"
fi

echo
echo '===== PROCESS AND ROS GRAPH OWNERSHIP ====='
if ! process_table="$(ps -eo pid,args 2>&1)"; then
  fail "process ownership query failed: ${process_table}"
else
  processes="$(echo "${process_table}" | grep -E \
    'limo_base|nav2|navigation|move_base|teleop|cmd_vel|cleanup_tracked_base' \
    | grep -v -E 'grep|tracked_base_stage2_preflight' || true)"
  if [[ -n "${processes}" ]]; then
    fail "motion-related process already exists: ${processes}"
  else
    pass 'no motion-related process is running'
  fi
fi

if ! nodes="$(timeout -k 2 8 \
    ros2 node list --no-daemon --spin-time 2.0 2>&1)"; then
  fail "ROS node query failed: ${nodes}"
elif echo "${nodes}" | grep -Eq \
    'limo_base|nav2|navigation|teleop|cleanup_tracked_base'; then
  fail "motion-related ROS node already exists: ${nodes}"
else
  pass 'no motion-related ROS node is visible'
fi

if ! vendor_prefix="$(ros2 pkg prefix limo_base 2>/dev/null)"; then
  fail 'limo_base package is not discoverable'
elif [[ "${vendor_prefix}" != '/home/agilex/limo_ros2_ws/install/limo_base' ]]; then
  fail "unexpected limo_base install prefix: ${vendor_prefix}"
else
  pass "vendor package prefix matches ${vendor_prefix}"
fi

for command_topic in \
    /cmd_vel /cmd_vel_nav /cmd_vel_teleop /limo/vel_cmd \
    /cleanup/base/safe_cmd_vel; do
  command_info="$(ROS2CLI_NO_DAEMON=1 timeout -k 2 8 \
    ros2 topic info "${command_topic}" --verbose 2>&1)"
  command_status=$?
  if echo "${command_info}" | grep -q "Unknown topic '${command_topic}'"; then
    pass "${command_topic} does not exist"
  elif [[ "${command_status}" -ne 0 ]]; then
    fail "could not inspect ${command_topic} publishers (exit ${command_status}): ${command_info}"
  elif echo "${command_info}" | grep -Eq 'Publisher count: 0' \
      && echo "${command_info}" | grep -Eq 'Subscription count: 0'; then
    pass "${command_topic} exists with zero endpoints"
  else
    fail "${command_topic} has an endpoint or could not be proven safe: ${command_info}"
  fi
done

echo
echo '===== VENDOR STARTUP WRITE ACKNOWLEDGEMENT ====='
vendor_source=/home/agilex/limo_ros2_ws/src/limo_ros2/limo_base/src/limo_driver.cpp
vendor_launch=/home/agilex/limo_ros2_ws/src/limo_ros2/limo_base/launch/limo_base.launch.py
if [[ ! -f "${vendor_source}" ]]; then
  fail "vendor source missing: ${vendor_source}"
elif grep -q 'enableCommandedMode();' "${vendor_source}"; then
  pass 'vendor startup 0x421 write risk is still present and acknowledged'
else
  fail 'vendor startup behavior changed; repeat source audit before proceeding'
fi
if [[ ! -f "${vendor_launch}" ]]; then
  fail "vendor launch missing: ${vendor_launch}"
elif grep -q "default_value='ttyTHS0'" "${vendor_launch}"; then
  pass 'vendor launch default port remains ttyTHS0'
else
  fail 'vendor launch default port changed; repeat source audit before proceeding'
fi

echo
if [[ "${status}" -eq 0 ]]; then
  echo 'STAGE2_PREFLIGHT_PASS'
  echo 'This script did not start limo_base or publish any ROS message.'
else
  echo 'STAGE2_PREFLIGHT_BLOCKED'
  echo 'Do not start limo_base or the tracked-base gateway.'
fi
exit "${status}"
