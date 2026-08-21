#!/usr/bin/env bash

set -euo pipefail

readonly authority_redirect='docs/HARDWARE_READINESS_ROS1_NOETIC_REDIRECT.md'
readonly authority_runbook='docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md'
readonly atomic_launcher='audit_tools/ros1_camera_only_atomic_launcher.py'
readonly isolated_domain='197'

block_current_entry() {
  echo 'BLOCKED_NON_AUTHORITATIVE_HARDWARE_READINESS: this retired ROS2 wrapper never starts ROS or a camera.' >&2
  echo "Read ${authority_redirect}, then ${authority_runbook}." >&2
  echo "The only production camera-driver role is ${atomic_launcher}; it remains fail-closed until host admission is bound." >&2
  exit 64
}

for argument in "$@"; do
  case "${argument}" in
    *start_camera:=true*)
      echo 'BLOCKED_LEGACY_ROS2_CAMERA_START_FORBIDDEN' >&2
      exit 65
      ;;
    *'/camera/'*|*'/dev/'*|*ttyTHS*|*fuser*|*'ros2 topic'*|*'ros2 node'*|*'ros2 launch'*|*roslaunch*)
      echo 'BLOCKED_LEGACY_ROS2_REAL_TOPIC_DEVICE_OR_GRAPH_FORBIDDEN' >&2
      exit 66
      ;;
  esac
done

if [[ "$#" -eq 0 ]]; then
  block_current_entry
fi
if [[ "$#" -ne 1 || "$1" != '--legacy-ros2-offline-only' ]]; then
  echo 'BLOCKED_LEGACY_ROS2_OFFLINE_ONLY_ARGUMENT_INVALID' >&2
  exit 67
fi
if [[ "${LEGACY_ROS2_OFFLINE_ONLY:-}" != '1' ]]; then
  echo 'BLOCKED_LEGACY_ROS2_OFFLINE_ONLY_OPT_IN_REQUIRED' >&2
  exit 68
fi
if [[ "${ROS_LOCALHOST_ONLY:-}" != '1' || "${ROS_DOMAIN_ID:-}" != "${isolated_domain}" ]]; then
  echo 'BLOCKED_LEGACY_ROS2_OFFLINE_ISOLATION_REQUIRED: require ROS_LOCALHOST_ONLY=1 and ROS_DOMAIN_ID=197.' >&2
  exit 69
fi
if [[ -n "${ROS_MASTER_URI:-}" || -n "${ROS_IP:-}" || -n "${ROS_HOSTNAME:-}" || -n "${ROS_DISCOVERY_SERVER:-}" || -n "${CYCLONEDDS_URI:-}" || -n "${FASTRTPS_DEFAULT_PROFILES_FILE:-}" ]]; then
  echo 'BLOCKED_LEGACY_ROS2_AMBIENT_GRAPH_CONFIGURATION' >&2
  exit 70
fi

echo 'LEGACY_ROS2_OFFLINE_ONLY_PURE_STATIC_ACKNOWLEDGEMENT'
echo 'No ROS graph, camera, topic, device, UART, inference, network, or hardware action was performed.'
echo "Current authority route: ${authority_redirect} -> ${authority_runbook} -> ${atomic_launcher} (still fail-closed)."
exit 0
