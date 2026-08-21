#!/usr/bin/env bash

set -eu

echo 'FIELD_RUNTIME_AUTHORITY=ROS1_NOETIC'
echo 'LEGACY_ROS2_OFFLINE_ONLY'
echo 'NOT_NOETIC_FIELD_OR_DELIVERY_EVIDENCE'

if [[ "${LIMO_ALLOW_LEGACY_ROS2_OFFLINE-}" != '1' ]]; then
  echo 'BLOCKED: this retired entrypoint is unavailable.' >&2
  exit 64
fi

echo 'BLOCKED: legacy tracked-base hardware preflight is permanently retired.' >&2
echo 'Use the current ROS1/Noetic controlled runbook and its separate authorization boundary.' >&2
exit 64
