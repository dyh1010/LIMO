#!/usr/bin/env bash

set -euo pipefail

# Permanently retired fail-closed shim.  The former implementation verified a
# pathname and then launched through ROS package resolution, so the verified
# bytes were not atomically bound to the executed bytes.  Keeping the filename
# avoids silently reviving old operator notes while making every invocation
# non-executable.
echo 'ERROR: scripts/start_dabai_camera.sh is retired and never starts ROS.' >&2
echo 'Use docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md and the host-owned' >&2
echo 'audit_tools/ros1_camera_only_atomic_launcher.py sealed-memfd path.' >&2
echo 'The atomic launcher requires --mode EXECUTE_AUDITED_CAMERA_ONLY and an' >&2
echo 'explicit --actual-vendor-launch absolute path; it accepts no overrides.' >&2
exit 64
