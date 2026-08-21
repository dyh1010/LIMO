#!/usr/bin/env bash

# Read-only, fail-closed audit for the ROS1 Noetic base plus ros1_bridge path.
# This script never starts a node, opens /dev/ttyTHS0, or publishes a message.

set -o pipefail

phase='pre-master'
if [[ "${1:-}" == '--phase' && -n "${2:-}" && -z "${3:-}" ]]; then
  phase="$2"
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--phase pre-master|post-master]" >&2
  exit 2
fi
if [[ "${phase}" != 'pre-master' && "${phase}" != 'post-master' ]]; then
  echo "BLOCKED: unknown preflight phase ${phase}" >&2
  exit 2
fi

status=0
requested_domain="${ROS_DOMAIN_ID:-137}"
requested_localhost="${ROS_LOCALHOST_ONLY:-0}"
requested_rmw="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
port="${ROS1_BASE_PORT:-/dev/ttyTHS0}"
expected_sysfs="${ROS1_BASE_EXPECTED_SYSFS_DEVICE:-/sys/devices/platform/3100000.serial}"
expected_driver="${ROS1_BASE_EXPECTED_DRIVER:-/sys/bus/platform/drivers/serial-tegra}"

pass() {
  echo "PASS: $1"
}

fail() {
  echo "FAIL: $1" >&2
  status=1
}

source_bridge_environment() {
  local noetic_setup="${ROS1_NOETIC_SETUP:-/opt/ros/noetic/setup.bash}"
  local vendor_setup="${ROS1_VENDOR_SETUP:-/home/agilex/agilex_ws/devel/setup.bash}"
  local adapter_setup="${ROS1_ADAPTER_SETUP:-/home/agilex/limo_cleanup_ros1_ws/devel/setup.bash}"
  local foxy_setup="${ROS2_FOXY_SETUP:-/opt/ros/foxy/setup.bash}"
  local cleanup_setup="${ROS2_CLEANUP_SETUP:-/home/agilex/limo_cleanup_ws/install/setup.bash}"

  for setup_file in "${noetic_setup}" "${vendor_setup}" "${adapter_setup}"; do
    if [[ ! -f "${setup_file}" ]]; then
      fail "required setup file is missing: ${setup_file}"
      continue
    fi
    # shellcheck disable=SC1090
    source "${setup_file}"
  done
  if command -v rosversion >/dev/null 2>&1; then
    ROS1_BASE_BRIDGE_DETECTED_ROS1_DISTRO="$(rosversion -d 2>&1)"
    export ROS1_BASE_BRIDGE_DETECTED_ROS1_DISTRO
  fi
  for setup_file in "${foxy_setup}" "${cleanup_setup}"; do
    if [[ ! -f "${setup_file}" ]]; then
      fail "required setup file is missing: ${setup_file}"
      continue
    fi
    # shellcheck disable=SC1090
    source "${setup_file}"
  done
}

if [[ "${ROS1_BASE_BRIDGE_SKIP_ENV_SOURCE:-NO}" != 'YES' ]]; then
  source_bridge_environment
fi

export ROS_DOMAIN_ID=137
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

echo '===== REQUIRED TOOLS ====='
for command_name in \
    fuser grep id pgrep ps readlink rospack roslaunch rosnode rostopic \
    rosversion ros2 stat timeout tr python3; do
  if command -v "${command_name}" >/dev/null 2>&1; then
    pass "required command is available: ${command_name}"
  else
    fail "required command is missing: ${command_name}"
  fi
done
if [[ "${status}" -ne 0 ]]; then
  echo 'ROS1_BASE_BRIDGE_PREFLIGHT_BLOCKED'
  exit "${status}"
fi

echo '===== ROS1/ROS2 ENVIRONMENT ====='
if [[ "${requested_domain}" == '137' ]]; then
  pass 'ROS_DOMAIN_ID matches integration baseline 137'
else
  fail "caller requested ROS_DOMAIN_ID=${requested_domain}; expected 137"
fi
if [[ "${requested_localhost}" == '0' ]]; then
  pass 'ROS_LOCALHOST_ONLY=0 exposes the complete ROS2 graph'
else
  fail "caller requested ROS_LOCALHOST_ONLY=${requested_localhost}; expected 0"
fi
if [[ "${requested_rmw}" == 'rmw_cyclonedds_cpp' ]]; then
  pass 'RMW_IMPLEMENTATION request matches rmw_cyclonedds_cpp'
else
  fail "caller requested RMW_IMPLEMENTATION=${requested_rmw}; expected rmw_cyclonedds_cpp"
fi
for discovery_name in \
    ROS_DISCOVERY_SERVER CYCLONEDDS_URI FASTRTPS_DEFAULT_PROFILES_FILE; do
  if [[ -n "${!discovery_name:-}" ]]; then
    fail "${discovery_name} is set and can hide ROS2 participants"
  else
    pass "${discovery_name} is unset"
  fi
done

ros1_distro="${ROS1_BASE_BRIDGE_DETECTED_ROS1_DISTRO:-unknown}"
if [[ "${ros1_distro}" == 'noetic' ]]; then
  pass 'ROS1 environment reported noetic before the ROS2 overlay was sourced'
else
  fail "pre-ROS2 ROS1 distro was ${ros1_distro:-unknown}; expected noetic"
fi

rmw_actual="$(python3 - <<'PY' 2>&1
import rclpy
getter = getattr(rclpy, 'get_rmw_implementation_identifier', None)
if getter is not None:
    print(getter())
else:
    from rclpy.impl.implementation_singleton import rclpy_implementation
    print(rclpy_implementation.rmw_get_implementation_identifier())
PY
)"
if [[ "${rmw_actual}" == 'rmw_cyclonedds_cpp' ]]; then
  pass 'runtime RMW getter reports rmw_cyclonedds_cpp'
else
  fail "runtime RMW getter returned ${rmw_actual:-unknown}"
fi

echo '===== PACKAGE AND MESSAGE PAIR AUDIT ====='
if bridge_prefix="$(ros2 pkg prefix ros1_bridge 2>&1)"; then
  pass "ros1_bridge is discoverable at ${bridge_prefix}"
else
  fail "ros1_bridge is not discoverable: ${bridge_prefix}"
fi
bridge_executables="$(ros2 pkg executables ros1_bridge 2>&1)"
if echo "${bridge_executables}" | grep -Eq '^ros1_bridge[[:space:]]+dynamic_bridge$'; then
  pass 'ros1_bridge dynamic_bridge executable is installed'
else
  fail "dynamic_bridge executable is missing: ${bridge_executables}"
fi
bridge_pairs="$(timeout -k 2 12 \
  ros2 run ros1_bridge dynamic_bridge --print-pairs 2>&1)"
bridge_pair_status=$?
if [[ "${bridge_pair_status}" -ne 0 ]]; then
  fail "could not enumerate bridge pairs (exit ${bridge_pair_status}): ${bridge_pairs}"
else
  for message_pattern in \
      'geometry_msgs.*/Twist' \
      'geometry_msgs.*/PoseStamped' \
      'std_msgs.*/Bool' \
      'std_msgs.*/String'; do
    if echo "${bridge_pairs}" | grep -Eq "${message_pattern}"; then
      pass "compiled bridge pair is available: ${message_pattern}"
    else
      fail "compiled bridge pair is missing: ${message_pattern}"
    fi
  done
fi

for package_name in \
    limo_bringup limo_base limo_v1_navigation limo_cleanup_ros1_base; do
  if package_path="$(rospack find "${package_name}" 2>&1)"; then
    pass "ROS1 package ${package_name} is discoverable at ${package_path}"
  else
    fail "ROS1 package ${package_name} is not discoverable: ${package_path}"
  fi
done

vendor_nodes="$(roslaunch --nodes limo_bringup limo_start.launch 2>&1)"
vendor_nodes_status=$?
if [[ "${vendor_nodes_status}" -ne 0 ]]; then
  fail "could not statically expand limo_start.launch: ${vendor_nodes}"
elif ! echo "${vendor_nodes}" | grep -qx '/limo_base_node'; then
  fail "limo_start.launch does not contain exact /limo_base_node: ${vendor_nodes}"
elif echo "${vendor_nodes}" | grep -Eqi 'teleop|keyboard|joy|move_base|nav2'; then
  fail "limo_start.launch unexpectedly contains a motion command source: ${vendor_nodes}"
else
  pass 'limo_start.launch contains /limo_base_node and no teleop/navigation node'
fi

wrapper_nodes="$(roslaunch --nodes limo_cleanup_ros1_base \
  limo_start_private_cmd.launch hardware_write_authorized:=true 2>&1)"
wrapper_nodes_status=$?
if [[ "${wrapper_nodes_status}" -eq 0 ]] \
    && echo "${wrapper_nodes}" | grep -qx '/limo_base_node'; then
  pass 'private-command wrapper statically expands to /limo_base_node'
else
  fail "private-command wrapper expansion failed: ${wrapper_nodes}"
fi

bridge_package_root="$(rospack find limo_cleanup_ros1_base 2>/dev/null || true)"
if [[ -z "${bridge_package_root}" ]]; then
  fail 'could not locate limo_cleanup_ros1_base package'
elif [[ -e "${bridge_package_root}/launch/v2_bridged_navigation_internal.launch" ]]; then
  fail 'bypassable internal integrated launch must not be installed'
elif ! timeout -k 1 5 rosrun limo_cleanup_ros1_base \
    run_v2_bridged_navigation.py --help >/dev/null 2>&1; then
  fail 'sole production bridged-navigation runner is unavailable'
else
  pass 'only the FD-gated bridged-navigation runner is installed'
fi

echo '===== ONE-TIME FIELD AUTHORIZATION ====='
authorization_file="${ROS1_BASE_ZERO_STAGE_AUTHORIZATION_FILE:-}"
if [[ "${phase}" == 'post-master' ]]; then
  pass 'POST_MASTER uses the already-consumed private authorization record'
elif [[ -n "${authorization_file}" && -f "${authorization_file}" \
    && ! -L "${authorization_file}" \
    && "$(stat -c '%a' "${authorization_file}" 2>/dev/null)" == '600' ]]; then
  pass 'one-time authorization file is present; execute runner will consume it'
else
  fail 'owner-only one-time authorization file is absent/unsafe'
fi

echo '===== UART IDENTITY AND EXCLUSION ====='
if [[ "${port}" != '/dev/ttyTHS0' ]]; then
  fail "unexpected base port ${port}; only /dev/ttyTHS0 is admitted"
elif [[ ! -c "${port}" ]]; then
  fail "${port} is missing or is not a character device"
else
  pass "${port} exists as a character device"
fi
tty_name="${port##*/}"
actual_sysfs="$(readlink -f "/sys/class/tty/${tty_name}/device" 2>/dev/null || true)"
actual_driver="$(readlink -f "/sys/class/tty/${tty_name}/device/driver" 2>/dev/null || true)"
if [[ "${actual_sysfs}" == "${expected_sysfs}" ]]; then
  pass "UART sysfs identity matches ${actual_sysfs}"
else
  fail "UART sysfs mismatch: expected ${expected_sysfs}, got ${actual_sysfs:-missing}"
fi
if [[ "${actual_driver}" == "${expected_driver}" ]]; then
  pass "UART driver identity matches ${actual_driver}"
else
  fail "UART driver mismatch: expected ${expected_driver}, got ${actual_driver:-missing}"
fi
uart_owners="$(fuser "${port}" 2>&1)"
uart_status=$?
if [[ "${uart_status}" -eq 1 && -z "${uart_owners//[[:space:]]/}" ]]; then
  pass "${port} has no owner before bridge startup"
elif [[ "${uart_status}" -eq 0 ]]; then
  fail "${port} is already owned by PID(s): ${uart_owners}"
else
  fail "could not prove UART ownership (fuser exit ${uart_status}): ${uart_owners}"
fi
if id -nG | tr ' ' '\n' | grep -qx dialout; then
  pass 'current user belongs to dialout'
else
  fail 'current user is not a member of dialout'
fi

echo '===== PROCESS AND GRAPH EXCLUSION ====='
process_table="$(ps -eo pid,args 2>&1)"
process_status=$?
if [[ "${process_status}" -ne 0 ]]; then
  fail "could not read process table: ${process_table}"
else
forbidden_processes="$(echo "${process_table}" | grep -E \
    'limo_base|dynamic_bridge|teleop|keyboard|move_base|nav2|cmd_vel_watchdog' \
    | grep -v -E 'grep|ros1_base_bridge_preflight' || true)"
  if [[ -n "${forbidden_processes}" ]]; then
    fail "base/bridge process already exists: ${forbidden_processes}"
  else
    pass 'no base, teleop, navigation, bridge, or watchdog process exists'
  fi
fi

if [[ "${phase}" == 'pre-master' ]]; then
  if [[ "${ROS_MASTER_URI:-http://localhost:11311}" \
      != 'http://localhost:11311' ]]; then
    fail "PRE_MASTER requires ROS_MASTER_URI=http://localhost:11311"
  elif timeout -k 1 2 rosnode list >/dev/null 2>&1; then
    fail 'PRE_MASTER requires the ROS1 master to be absent'
  elif pgrep -af '(^|/)(roscore|rosmaster)([[:space:]]|$)' >/dev/null; then
    fail 'PRE_MASTER found a roscore/rosmaster process'
  elif python3 - <<'PY'
import socket
sock = socket.socket()
try:
    sock.bind(('127.0.0.1', 11311))
finally:
    sock.close()
PY
  then
    pass 'PRE_MASTER target URI/port is local, free, and process-clean'
  else
    fail 'PRE_MASTER could not prove localhost:11311 is free'
  fi
else
  ros1_nodes="$(timeout -k 2 8 rosnode list 2>&1)"
  ros1_nodes_status=$?
  if [[ "${ros1_nodes_status}" -ne 0 ]]; then
    fail "POST_MASTER ROS1 master/node query failed: ${ros1_nodes}"
  elif echo "${ros1_nodes}" | grep -Eqi \
      'limo_base|dynamic_bridge|teleop|keyboard|move_base|cmd_vel_watchdog'; then
    fail "POST_MASTER motion-related ROS1 node already exists: ${ros1_nodes}"
  else
    pass 'POST_MASTER graph has no base, bridge, teleop, or watchdog node'
  fi
fi

ros2_nodes="$(timeout -k 2 8 ros2 node list --no-daemon --spin-time 2.0 2>&1)"
ros2_nodes_status=$?
if [[ "${ros2_nodes_status}" -ne 0 ]]; then
  fail "ROS2 node query failed: ${ros2_nodes}"
elif echo "${ros2_nodes}" | grep -Eqi \
    'limo_base|dynamic_bridge|teleop|nav2|cleanup_tracked_base'; then
  fail "motion-related ROS2 node already exists: ${ros2_nodes}"
else
  pass 'ROS2 graph has no base, bridge, teleop, Nav2, or gateway node'
fi

check_ros1_topic_empty() {
  local topic_name="$1"
  local topic_info
  topic_info="$(timeout -k 2 8 rostopic info "${topic_name}" 2>&1)"
  local topic_status=$?
  if echo "${topic_info}" | grep -Eq 'Unknown topic|does not appear to be published'; then
    pass "ROS1 ${topic_name} does not exist"
  elif [[ "${topic_status}" -ne 0 ]]; then
    fail "could not inspect ROS1 ${topic_name}: ${topic_info}"
  elif echo "${topic_info}" | grep -Eq 'Publishers:[[:space:]]*None' \
      && echo "${topic_info}" | grep -Eq 'Subscribers:[[:space:]]*None'; then
    pass "ROS1 ${topic_name} has zero endpoints"
  else
    fail "ROS1 ${topic_name} has an endpoint: ${topic_info}"
  fi
}

check_ros2_topic_empty() {
  local topic_name="$1"
  local topic_info
  topic_info="$(ROS2CLI_NO_DAEMON=1 timeout -k 2 8 \
    ros2 topic info "${topic_name}" --verbose 2>&1)"
  local topic_status=$?
  if echo "${topic_info}" | grep -q "Unknown topic '${topic_name}'"; then
    pass "ROS2 ${topic_name} does not exist"
  elif [[ "${topic_status}" -ne 0 ]]; then
    fail "could not inspect ROS2 ${topic_name}: ${topic_info}"
  elif echo "${topic_info}" | grep -Eq 'Publisher count: 0' \
      && echo "${topic_info}" | grep -Eq 'Subscription count: 0'; then
    pass "ROS2 ${topic_name} has zero endpoints"
  else
    fail "ROS2 ${topic_name} has an endpoint: ${topic_info}"
  fi
}

for topic_name in \
    /cmd_vel /cleanup/base/cmd_vel_request \
    /cleanup/base/safe_cmd_vel /cleanup/base/driver_cmd_vel \
    /cleanup/navigation/goal /cleanup/navigation/stop \
    /cleanup/navigation/cancel /cleanup/navigation/rearm \
    /cleanup/navigation/bridge_command \
    /cleanup/navigation/bridge_status /cleanup/navigation_intent; do
  if [[ "${phase}" == 'post-master' ]]; then
    check_ros1_topic_empty "${topic_name}"
  fi
  check_ros2_topic_empty "${topic_name}"
done

echo
if [[ "${status}" -eq 0 ]]; then
  echo "ROS1_BASE_BRIDGE_PREFLIGHT_PASS phase=${phase}"
  echo 'No node was started, no serial port was opened, and no message was published.'
else
  echo 'ROS1_BASE_BRIDGE_PREFLIGHT_BLOCKED'
  echo 'Do not start the ROS1 base driver, watchdog, gateway, or ros1_bridge.'
fi
exit "${status}"
