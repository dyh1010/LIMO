#!/usr/bin/env bash

# Default mode is read-only preflight. Execute mode can open /dev/ttyTHS0,
# but only after the complete zero chain and both pre-driver verifiers pass.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace_root="$(cd "${script_dir}/.." && pwd)"
execute_mode='NO'
if [[ "${1:-}" == '--execute-zero-stage' ]]; then
  execute_mode='YES'
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--execute-zero-stage]" >&2
  exit 2
fi

source_required() {
  local setup_file="$1"
  if [[ ! -f "${setup_file}" ]]; then
    echo "BLOCKED: required setup file is missing: ${setup_file}" >&2
    exit 2
  fi
  # shellcheck disable=SC1090
  source "${setup_file}"
}

source_required "${ROS1_NOETIC_SETUP:-/opt/ros/noetic/setup.bash}"
source_required "${ROS1_VENDOR_SETUP:-/home/agilex/agilex_ws/devel/setup.bash}"
source_required "${ROS1_ADAPTER_SETUP:-/home/agilex/limo_cleanup_ros1_ws/devel/setup.bash}"
ROS1_BASE_BRIDGE_DETECTED_ROS1_DISTRO="$(rosversion -d 2>&1)"
export ROS1_BASE_BRIDGE_DETECTED_ROS1_DISTRO
source_required "${ROS2_FOXY_SETUP:-/opt/ros/foxy/setup.bash}"
source_required "${ROS2_CLEANUP_SETUP:-/home/agilex/limo_cleanup_ws/install/setup.bash}"

export ROS_DOMAIN_ID=137
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
unset ROS_DISCOVERY_SERVER CYCLONEDDS_URI FASTRTPS_DEFAULT_PROFILES_FILE

ROS1_BASE_BRIDGE_SKIP_ENV_SOURCE=YES \
  bash "${script_dir}/ros1_base_bridge_preflight.sh" --phase pre-master

if [[ "${execute_mode}" != 'YES' ]]; then
  echo 'ROS1_BASE_BRIDGE_PREFLIGHT_ONLY_COMPLETE'
  echo 'No ROS node was started and /dev/ttyTHS0 was not opened.'
  exit 0
fi

for command_name in awk date fuser id mktemp mv pgrep seq setsid stat timeout wc xargs; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "BLOCKED: ${command_name} is required for zero-stage execution." >&2
    exit 1
  fi
done

authorization_file="${ROS1_BASE_ZERO_STAGE_AUTHORIZATION_FILE:-}"
authorization_consumed=''
authorization_consumed_uptime=''
authorization_remaining_seconds=''
consume_one_time_authorization() {
  local boot_id
  local current_epoch
  local expires_epoch
  local file_owner
  local file_mode
  if [[ -z "${authorization_file}" || ! -f "${authorization_file}" \
      || -L "${authorization_file}" ]]; then
    echo 'BLOCKED: a regular one-time authorization file is required.' >&2
    return 1
  fi
  read -r file_owner file_mode < <(stat -c '%u %a' "${authorization_file}")
  if [[ "${file_owner}" != "$(id -u)" || "${file_mode}" != '600' ]]; then
    echo 'BLOCKED: authorization file must be owner-only mode 600.' >&2
    return 1
  fi
  boot_id="$(< /proc/sys/kernel/random/boot_id)"
  current_epoch="$(date +%s)"
  expires_epoch="$(awk -F= '$1=="expires_epoch"{print $2}' \
    "${authorization_file}")"
  if [[ "$(wc -l < "${authorization_file}")" -ne 6 ]] \
      || ! grep -qx 'schema=ROS1_BASE_ZERO_STAGE_AUTH_V1' \
      "${authorization_file}" \
      || ! grep -qx "boot_id=${boot_id}" "${authorization_file}" \
      || ! grep -qx 'physical_checklist=YES' "${authorization_file}" \
      || ! grep -qx 'estop_tested=YES' "${authorization_file}" \
      || ! grep -qx 'command_mode_write_ack=YES' "${authorization_file}" \
      || [[ ! "${expires_epoch}" =~ ^[0-9]+$ ]] \
      || (( current_epoch >= expires_epoch )) \
      || (( expires_epoch - current_epoch > 300 )); then
    echo 'BLOCKED: authorization contents/boot/expiry are invalid.' >&2
    return 1
  fi
  authorization_consumed="${authorization_file}.consumed.$$"
  mv -- "${authorization_file}" "${authorization_consumed}"
  authorization_consumed_uptime="$(awk '{print $1}' /proc/uptime)"
  authorization_remaining_seconds=$((expires_epoch - current_epoch))
  echo 'PASS: one-time zero-stage authorization consumed.'
}
consume_one_time_authorization

verify_consumed_authorization_fresh() {
  local current_epoch
  local expires_epoch
  local current_uptime
  local monotonic_elapsed
  if [[ -z "${authorization_consumed}" \
      || ! -f "${authorization_consumed}" \
      || -L "${authorization_consumed}" ]]; then
    echo 'BLOCKED: consumed authorization record is unavailable.' >&2
    return 1
  fi
  current_epoch="$(date +%s)"
  current_uptime="$(awk '{print $1}' /proc/uptime)"
  monotonic_elapsed="$(awk -v now="${current_uptime}" \
    -v start="${authorization_consumed_uptime}" 'BEGIN{print now-start}')"
  expires_epoch="$(awk -F= '$1=="expires_epoch"{print $2}' \
    "${authorization_consumed}")"
  if [[ ! "${expires_epoch}" =~ ^[0-9]+$ ]] \
      || (( current_epoch >= expires_epoch )) \
      || ! awk -v elapsed="${monotonic_elapsed}" \
        -v budget="${authorization_remaining_seconds}" \
        'BEGIN{exit !(elapsed >= 0 && elapsed < budget)}'; then
    echo 'BLOCKED: one-time authorization expired before irreversible boundary.' >&2
    return 1
  fi
}

log_dir="$(mktemp -d /tmp/limo_ros1_bridge_zero_stage.XXXXXX)"
cleanup_state_file="${log_dir}/cleanup.state"
watchdog_pid=''
gateway_pid=''
bridge_pid=''
driver_pid=''
ros1_monitor_pid=''
ros2_monitor_pid=''
master_pid=''

cleanup_event() {
  rosrun limo_cleanup_ros1_base cleanup_sequence_guard.py \
    --state-file "${cleanup_state_file}" --event "$1"
}

process_group_alive() {
  local process_pid="$1"
  kill -0 -- "-${process_pid}" 2>/dev/null
}

stop_group() {
  local process_pid="$1"
  if [[ -z "${process_pid}" ]]; then
    return 0
  fi
  if process_group_alive "${process_pid}"; then
    kill -TERM -- "-${process_pid}" 2>/dev/null || true
    for _ in $(seq 1 30); do
      if ! process_group_alive "${process_pid}"; then
        break
      fi
      sleep 0.1
    done
    if process_group_alive "${process_pid}"; then
      kill -KILL -- "-${process_pid}" 2>/dev/null || true
      for _ in $(seq 1 30); do
        if ! process_group_alive "${process_pid}"; then
          break
        fi
        sleep 0.1
      done
    fi
  fi
  wait "${process_pid}" 2>/dev/null || true
  if process_group_alive "${process_pid}"; then
    echo "CLEANUP_BLOCKED: process group ${process_pid} survived KILL." >&2
    return 1
  fi
  return 0
}

verify_uart_idle() {
  local uart_owners
  local uart_status
  uart_status=0
  uart_owners="$(fuser /dev/ttyTHS0 2>&1)" || uart_status=$?
  if [[ "${uart_status}" -eq 1 && -z "${uart_owners//[[:space:]]/}" ]]; then
    return 0
  fi
  echo "BLOCKED: /dev/ttyTHS0 is not idle: ${uart_owners:-unknown}" >&2
  return 1
}

verify_driver_exclusion() {
  local node_info
  local node_info_status
  local node_pid
  local uart_pids
  local ros1_driver_nodes
  local ros2_driver_nodes
  local ros2_node_status
  node_info_status=0
  node_info="$(timeout -k 2 8 rosnode info /limo_base_node 2>&1)" \
    || node_info_status=$?
  if [[ "${node_info_status}" -ne 0 ]]; then
    echo "BLOCKED: could not inspect /limo_base_node: ${node_info}" >&2
    return 1
  fi
  node_pid="$(echo "${node_info}" | awk '/^Pid:/{print $2}')"
  uart_pids="$(fuser /dev/ttyTHS0 2>/dev/null | xargs)"
  if [[ -z "${node_pid}" || "${uart_pids}" != "${node_pid}" ]]; then
    echo "BLOCKED: UART owner ${uart_pids:-none} does not exactly match " \
      "limo_base_node PID ${node_pid:-unknown}." >&2
    return 1
  fi
  ros1_driver_nodes="$(timeout -k 2 8 rosnode list \
    | grep -E 'limo_base' || true)"
  if [[ "${ros1_driver_nodes}" != '/limo_base_node' ]]; then
    echo "BLOCKED: ROS1 driver nodes are ${ros1_driver_nodes:-none}." >&2
    return 1
  fi
  ros2_node_status=0
  ros2_driver_nodes="$(timeout -k 2 8 ros2 node list --no-daemon \
    --spin-time 2.0 2>&1)" || ros2_node_status=$?
  if [[ "${ros2_node_status}" -ne 0 ]]; then
    echo "BLOCKED: could not prove ROS2 driver exclusion: " \
      "${ros2_driver_nodes}" >&2
    return 1
  fi
  ros2_driver_nodes="$(echo "${ros2_driver_nodes}" \
    | grep -E 'limo_base' || true)"
  if [[ -n "${ros2_driver_nodes}" ]]; then
    echo "BLOCKED: ROS2 limo_base is concurrently visible." >&2
    return 1
  fi
}

verify_driver_stopped() {
  local driver_nodes
  local driver_processes
  driver_nodes="$(timeout -k 2 8 rosnode list 2>/dev/null \
    | grep -E 'limo_base' || true)"
  driver_processes="$(pgrep -af 'limo_base_node|limo_start_private_cmd' || true)"
  if [[ -n "${driver_nodes}" || -n "${driver_processes}" ]]; then
    echo "CLEANUP_BLOCKED: driver survived; nodes=${driver_nodes:-none} " \
      "processes=${driver_processes:-none}" >&2
    return 1
  fi
  verify_uart_idle
}

wait_for_new_zero_window() {
  local log_path="$1"
  local token="$2"
  local process_pid="$3"
  local initial_count
  initial_count="$(grep -c "${token}" "${log_path}" 2>/dev/null || true)"
  for _ in $(seq 1 50); do
    if ! kill -0 "${process_pid}" 2>/dev/null; then
      return 1
    fi
    if (( $(grep -c "${token}" "${log_path}" 2>/dev/null || true) \
        > initial_count )); then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

prove_zero_immediately_before_driver_stop() {
  if ! wait_for_new_zero_window \
      "${log_dir}/ros2_topology_monitor.log" \
      'ROS1_BRIDGE_ROS2_CONTINUOUS_ZERO_WINDOW_PASS' \
      "${ros2_monitor_pid}"; then
    echo 'CLEANUP_BLOCKED: ROS2 continuous zero window was not proven.' >&2
    return 1
  fi
  if ! wait_for_new_zero_window \
      "${log_dir}/ros1_topology_monitor.log" \
      'ROS1_BASE_BRIDGE_CONTINUOUS_ZERO_WINDOW_PASS' \
      "${ros1_monitor_pid}"; then
    echo 'CLEANUP_BLOCKED: ROS1 continuous zero window was not proven.' >&2
    return 1
  fi
}

verify_cleanup() {
  local failed=0
  local ros1_graph_unavailable=0
  local ros1_nodes
  local ros1_status
  local ros2_nodes
  local ros2_status
  local related_processes
  ros1_status=0
  ros1_nodes="$(timeout -k 2 8 rosnode list 2>&1)" || ros1_status=$?
  if [[ "${ros1_status}" -ne 0 ]]; then
    # The watchdog roslaunch may own the temporary ROS master.  Its group is
    # stopped last, so an unreachable master is expected only if no roscore or
    # rosmaster process survives the process-table check below.
    ros1_graph_unavailable=1
  elif echo "${ros1_nodes}" | grep -Eq \
      'limo_base|dynamic_bridge|cmd_vel_watchdog|verify_ros1_base_(bridge|zero_stage)'; then
    echo "CLEANUP_BLOCKED: residual ROS1 nodes: ${ros1_nodes}" >&2
    failed=1
  fi
  ros2_status=0
  ros2_nodes="$(timeout -k 2 8 ros2 node list --no-daemon \
    --spin-time 2.0 2>&1)" || ros2_status=$?
  if [[ "${ros2_status}" -ne 0 ]]; then
    echo "CLEANUP_BLOCKED: could not prove ROS2 node cleanup: " \
      "${ros2_nodes}" >&2
    failed=1
  elif echo "${ros2_nodes}" | grep -Eq \
      'dynamic_bridge|cleanup_tracked_base|verify_ros1_bridge_ros2'; then
    echo "CLEANUP_BLOCKED: residual ROS2 nodes: ${ros2_nodes}" >&2
    failed=1
  fi
  related_processes="$(pgrep -af \
    'roscore|rosmaster|limo_base_node|limo_start_private_cmd|dynamic_bridge|tracked_base_zero_output|cleanup_tracked_base_zero_output|safe_cmd_vel_watchdog_zero|cleanup_ros1_safe_cmd_vel_watchdog|verify_ros1_base_(bridge|zero_stage)_topology|verify_ros1_bridge_ros2_zero_output' \
    || true)"
  if [[ -n "${related_processes}" ]]; then
    echo "CLEANUP_BLOCKED: residual processes: ${related_processes}" >&2
    failed=1
  fi
  if [[ "${ros1_graph_unavailable}" -eq 1 \
      && -z "${related_processes}" ]]; then
    echo 'PASS: ROS1 master is absent and no related ROS1 process remains.'
  fi
  if ! verify_uart_idle; then
    failed=1
  fi
  if [[ "${failed}" -eq 0 ]]; then
    echo 'ROS1_BASE_BRIDGE_ZERO_STAGE_CLEANUP_PASS'
    return 0
  fi
  return 1
}

cleanup() {
  local exit_status=$?
  local cleanup_failed=0
  trap - EXIT INT TERM
  # There are no nonzero producers in zero-stage.  In future modes they must
  # be stopped here before touching bridge/gateway/watchdog.
  if ! cleanup_event producers_stopped; then cleanup_failed=1; fi
  if [[ -n "${driver_pid}" ]]; then
    local zero_proven=1
    if prove_zero_immediately_before_driver_stop; then
      if ! cleanup_event zero_proven; then cleanup_failed=1; fi
    else
      zero_proven=0
      cleanup_failed=1
    fi
    sleep 0.35
    if ! stop_group "${driver_pid}" || ! verify_driver_stopped; then
      cleanup_event driver_failed || true
      echo 'CLEANUP_BLOCKED: driver survived; zero safety chain retained.' >&2
      echo "ROS1_BASE_BRIDGE_ZERO_STAGE_LOG_DIR=${log_dir}"
      exit 1
    fi
    if [[ "${zero_proven}" -eq 1 ]]; then
      if ! cleanup_event driver_gone; then cleanup_failed=1; fi
    else
      if ! cleanup_event driver_gone_unproven; then cleanup_failed=1; fi
    fi
  else
    if ! cleanup_event driver_absent; then cleanup_failed=1; fi
  fi
  # Only after driver disappearance and UART release may the safety chain go.
  if ! cleanup_event stop_safety; then
    echo 'CLEANUP_BLOCKED: state machine forbids safety-chain teardown.' >&2
    exit 1
  fi
  if ! stop_group "${ros1_monitor_pid}"; then cleanup_failed=1; fi
  if ! stop_group "${ros2_monitor_pid}"; then cleanup_failed=1; fi
  if ! stop_group "${bridge_pid}"; then cleanup_failed=1; fi
  if ! stop_group "${gateway_pid}"; then cleanup_failed=1; fi
  if ! stop_group "${watchdog_pid}"; then cleanup_failed=1; fi
  if ! stop_group "${master_pid}"; then cleanup_failed=1; fi
  if ! verify_cleanup; then
    cleanup_failed=1
  fi
  if ! cleanup_event cleanup_complete; then cleanup_failed=1; fi
  if [[ -n "${authorization_consumed}" ]]; then
    rm -f -- "${authorization_consumed}"
  fi
  if [[ "${cleanup_failed}" -ne 0 ]]; then
    exit_status=1
  fi
  echo "ROS1_BASE_BRIDGE_ZERO_STAGE_LOG_DIR=${log_dir}"
  exit "${exit_status}"
}
trap cleanup EXIT INT TERM

wait_for_ros1_node() {
  local expected_node="$1"
  for _ in $(seq 1 40); do
    if timeout -k 1 2 rosnode list 2>/dev/null \
        | grep -qx "${expected_node}"; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

wait_for_ros2_node() {
  local expected_node="$1"
  for _ in $(seq 1 40); do
    if timeout -k 1 3 ros2 node list --no-daemon --spin-time 1.0 2>/dev/null \
        | grep -qx "${expected_node}"; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

wait_for_log_token() {
  local log_path="$1"
  local expected_token="$2"
  local process_pid="$3"
  for _ in $(seq 1 40); do
    if grep -q "${expected_token}" "${log_path}" 2>/dev/null; then
      return 0
    fi
    if ! kill -0 "${process_pid}" 2>/dev/null; then
      return 1
    fi
    sleep 0.25
  done
  return 1
}

if timeout -k 1 2 rosnode list >/dev/null 2>&1; then
  echo 'BLOCKED: zero-stage requires an absent ROS1 master it can own.' >&2
  exit 1
fi
echo 'Starting an owned ROS1 master for this zero-stage lifecycle.'
setsid roscore >"${log_dir}/roscore.log" 2>&1 &
master_pid=$!
master_ready='NO'
for _ in $(seq 1 40); do
  if timeout -k 1 2 rosnode list >/dev/null 2>&1; then
    master_ready='YES'
    break
  fi
  sleep 0.1
done
if [[ "${master_ready}" != 'YES' ]]; then
  echo 'BLOCKED: owned ROS1 master did not become ready.' >&2
  exit 1
fi
ROS1_BASE_BRIDGE_SKIP_ENV_SOURCE=YES \
  bash "${script_dir}/ros1_base_bridge_preflight.sh" --phase post-master

echo 'Starting ROS1 zero-only watchdog; UART remains unopened.'
setsid roslaunch limo_cleanup_ros1_base safe_cmd_vel_watchdog_zero.launch \
  >"${log_dir}/watchdog.log" 2>&1 &
watchdog_pid=$!
if ! wait_for_ros1_node '/cleanup_ros1_safe_cmd_vel_watchdog'; then
  echo 'BLOCKED: ROS1 watchdog did not become ready.' >&2
  exit 1
fi

echo 'Starting ROS2 zero-only gateway before any vendor process.'
setsid ros2 launch limo_cleanup_bringup tracked_base_zero_output.launch.py \
  >"${log_dir}/gateway.log" 2>&1 &
gateway_pid=$!
if ! wait_for_ros2_node '/cleanup_tracked_base_zero_output'; then
  echo 'BLOCKED: ROS2 zero gateway did not become ready.' >&2
  exit 1
fi

echo 'Starting restricted dynamic_bridge before any vendor process.'
setsid ros2 run ros1_bridge dynamic_bridge \
  >"${log_dir}/dynamic_bridge.log" 2>&1 &
bridge_pid=$!

echo 'Starting continuous ROS2 zero verifier before vendor startup.'
setsid python3 "${workspace_root}/scripts/verify_ros1_bridge_ros2_zero_output.py" \
  --ros-args -p continuous:=true \
  >"${log_dir}/ros2_topology_monitor.log" 2>&1 &
ros2_monitor_pid=$!
if ! wait_for_log_token "${log_dir}/ros2_topology_monitor.log" \
    'ROS1_BRIDGE_ROS2_ZERO_MONITORING' "${ros2_monitor_pid}"; then
  echo 'BLOCKED: pre-vendor ROS2 continuous zero proof failed.' >&2
  exit 1
fi

echo 'Proving ROS1 topology and ten continuous zero samples without driver.'
if ! rosrun limo_cleanup_ros1_base verify_ros1_base_bridge_topology.py \
    _driver_expected:=false \
    _monitor_role:=zero_stage \
    _ready_topic:=/cleanup/base/zero_stage_topology_ready \
    __name:=/verify_ros1_base_zero_stage_topology \
    >"${log_dir}/ros1_pre_driver_verifier.log" 2>&1; then
  echo 'BLOCKED: pre-vendor ROS1 zero/topology proof failed.' >&2
  exit 1
fi
if ! grep -q 'ROS1_BASE_BRIDGE_TOPOLOGY_PASS' \
    "${log_dir}/ros1_pre_driver_verifier.log"; then
  echo 'BLOCKED: ROS1 pre-driver verifier did not emit PASS.' >&2
  exit 1
fi
verify_uart_idle

echo 'All zero proofs passed; starting explicitly authorized ROS1 vendor.'
verify_consumed_authorization_fresh
setsid roslaunch limo_cleanup_ros1_base limo_start_private_cmd.launch \
  hardware_write_authorized:=true \
  >"${log_dir}/ros1_vendor_driver.log" 2>&1 &
driver_pid=$!
if ! wait_for_ros1_node '/limo_base_node'; then
  echo 'BLOCKED: ROS1 limo_base_node did not become ready.' >&2
  exit 1
fi
verify_driver_exclusion

setsid rosrun limo_cleanup_ros1_base verify_ros1_base_bridge_topology.py \
  _driver_expected:=true _continuous:=true \
  _monitor_role:=zero_stage \
  _ready_topic:=/cleanup/base/zero_stage_topology_ready \
  __name:=/verify_ros1_base_zero_stage_topology \
  >"${log_dir}/ros1_topology_monitor.log" 2>&1 &
ros1_monitor_pid=$!
if ! wait_for_log_token "${log_dir}/ros1_topology_monitor.log" \
    'ROS1_BASE_BRIDGE_TOPOLOGY_MONITORING' "${ros1_monitor_pid}"; then
  echo 'BLOCKED: post-vendor ROS1 continuous monitor failed.' >&2
  exit 1
fi

echo 'ROS1_BASE_BRIDGE_ZERO_STAGE_READY'
echo 'Only zero commands are admitted. Nonzero motion remains disabled.'
loop_count=0
while true; do
  for required_pid in \
      "${driver_pid}" "${bridge_pid}" "${gateway_pid}" "${watchdog_pid}" \
      "${ros1_monitor_pid}" "${ros2_monitor_pid}"; do
    if ! kill -0 "${required_pid}" 2>/dev/null; then
      echo "BLOCKED: required process exited: PID ${required_pid}" >&2
      exit 1
    fi
  done
  verify_driver_exclusion
  loop_count=$((loop_count + 1))
  if (( loop_count % 25 == 0 )); then
    if ! wait_for_new_zero_window \
        "${log_dir}/ros2_topology_monitor.log" \
        'ROS1_BRIDGE_ROS2_CONTINUOUS_ZERO_WINDOW_PASS' \
        "${ros2_monitor_pid}" \
        || ! wait_for_new_zero_window \
        "${log_dir}/ros1_topology_monitor.log" \
        'ROS1_BASE_BRIDGE_CONTINUOUS_ZERO_WINDOW_PASS' \
        "${ros1_monitor_pid}"; then
      echo 'BLOCKED: continuous zero monitor heartbeat became stale.' >&2
      exit 1
    fi
    echo 'PASS: UART, driver exclusion, and zero heartbeats remain valid.'
  fi
  sleep 0.2
done
