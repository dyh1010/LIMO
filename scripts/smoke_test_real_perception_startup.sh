#!/usr/bin/env bash

# ROS1_NOETIC_CURRENT_FIELD_AUTHORITY
# LEGACY_ROS2_OFFLINE_ONLY / NON_AUTHORITATIVE_DO_NOT_RUN
# NOT_FIELD_OR_DELIVERY_EVIDENCE
#
# This retired helper used to start the ROS2 dual-model detector. Model
# loading is not a provably isolated pure-fake operation, so the helper is now
# a permanent fail-closed shim. Current operators must enter through
# docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md and the host-owned
# audit_tools/ros1_camera_only_atomic_launcher.py gate.

set -euo pipefail

readonly operations_index='docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md'
readonly atomic_launcher='audit_tools/ros1_camera_only_atomic_launcher.py'

if [[ "${LIMO_ALLOW_LEGACY_ROS2_OFFLINE:-}" != '1' ]]; then
  echo 'BLOCKED_LEGACY_ROS2_OFFLINE_OPT_IN_REQUIRED' >&2
  echo "Read ${operations_index}; production camera entry is ${atomic_launcher}." >&2
  exit 64
fi

echo 'BLOCKED_LEGACY_REAL_PERCEPTION_NOT_PROVABLY_PURE_OFFLINE' >&2
echo 'No ROS graph, model, inference, camera, topic, device, network, or hardware action was performed.' >&2
echo "Read ${operations_index}; production camera entry is ${atomic_launcher}." >&2
exit 65
