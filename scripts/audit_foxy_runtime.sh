#!/usr/bin/env bash
# Read-only ROS 2 Foxy/ARM64 deployment audit.
# This script never starts hardware drivers, opens serial devices, publishes,
# calls services/actions, or sends commands to any actuator.
# ROS1_NOETIC_CURRENT_FIELD_AUTHORITY
# LEGACY_ROS2_OFFLINE_ONLY / NON_AUTHORITATIVE_DO_NOT_RUN
# NOT_NOETIC_BUILD_INSTALL_FIELD_OR_DELIVERY_EVIDENCE
#
# The historical audit body is retained below for provenance only.  Generic
# offline opt-in cannot source Foxy, inspect an overlay/package index, import
# project runtime modules, or query a ROS graph.  Current operators must enter
# through docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md.

set -euo pipefail

readonly operations_index='docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md'

if [[ "${LIMO_ALLOW_LEGACY_ROS2_OFFLINE:-}" != '1' ]]; then
  echo 'BLOCKED_LEGACY_ROS2_OFFLINE_OPT_IN_REQUIRED' >&2
  echo "Read ${operations_index}." >&2
  exit 64
fi

echo 'BLOCKED_FOXY_RUNTIME_AUDIT_REQUIRES_SEPARATE_EXPLICIT_FIELD_OR_BRIDGE_AUTHORITY' >&2
echo 'No ROS source, overlay, package, graph, topic, model, camera, device, network, or hardware query was performed.' >&2
echo "Read ${operations_index}." >&2
exit 65

set -u

project_root=''
overlay_setup=''
require_perception=0
check_graph=0

usage() {
  cat <<'EOF'
Usage: audit_foxy_runtime.sh [--overlay SETUP] [--project-root DIR]
                              [--require-perception] [--check-graph]

  --overlay SETUP          Source an existing ROS overlay setup.bash first.
  --project-root DIR       Parse project Python files and inspect package paths.
  --require-perception     Treat Torch and Ultralytics as required, not optional.
  --check-graph            Run one bounded, daemon-free, read-only topic query.

The default audit is entirely local to the filesystem and Python environment.
It does not start ROS nodes or touch hardware devices.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --overlay)
      [ "$#" -ge 2 ] || { echo 'missing value for --overlay' >&2; exit 2; }
      overlay_setup=$2
      shift 2
      ;;
    --project-root)
      [ "$#" -ge 2 ] || { echo 'missing value for --project-root' >&2; exit 2; }
      project_root=$2
      shift 2
      ;;
    --require-perception)
      require_perception=1
      shift
      ;;
    --check-graph)
      check_graph=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

pass_count=0
warn_count=0
fail_count=0

pass() {
  pass_count=$((pass_count + 1))
  printf '[PASS] %s\n' "$*"
}

warn() {
  warn_count=$((warn_count + 1))
  printf '[WARN] %s\n' "$*"
}

fail() {
  fail_count=$((fail_count + 1))
  printf '[FAIL] %s\n' "$*"
}

section() {
  printf '\n== %s ==\n' "$*"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

source_ros() {
  if [ -n "${ROS_DISTRO:-}" ]; then
    return 0
  fi
  if [ -r /opt/ros/foxy/setup.bash ]; then
    set +u
    # shellcheck disable=SC1091
    source /opt/ros/foxy/setup.bash
    set -u
    return 0
  fi
  return 1
}

section 'Safety contract'
pass 'audit mode is read-only; no driver, serial, publisher, service, action, or actuator command is used'

section 'Platform'
printf 'hostname=%s\n' "$(hostname 2>/dev/null || echo unknown)"
architecture=$(uname -m 2>/dev/null || echo unknown)
printf 'architecture=%s\n' "$architecture"
if [ "$architecture" = aarch64 ]; then
  pass 'architecture is aarch64'
else
  warn "architecture is $architecture, not the LIMO aarch64 target"
fi
if [ -r /etc/os-release ]; then
  . /etc/os-release
  printf 'os=%s\n' "${PRETTY_NAME:-unknown}"
  if [ "${VERSION_ID:-}" = '20.04' ]; then
    pass 'OS version is Ubuntu 20.04'
  else
    warn "OS version is ${VERSION_ID:-unknown}, not the Foxy target 20.04"
  fi
fi
if command_exists python3; then
  python3 --version 2>&1
  if python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 8) else 1)'; then
    pass 'Python 3.8 matches Ubuntu 20.04 / ROS 2 Foxy'
  else
    warn 'Python is not 3.8; validate binary and pip package compatibility explicitly'
  fi
else
  fail 'python3 is missing'
fi

if source_ros; then
  pass "ROS environment sourced (${ROS_DISTRO:-unknown})"
else
  fail 'could not source /opt/ros/foxy/setup.bash and ROS_DISTRO is unset'
fi
if [ "${ROS_DISTRO:-}" = foxy ]; then
  pass 'ROS_DISTRO is foxy'
else
  warn "ROS_DISTRO is ${ROS_DISTRO:-unset}, not foxy"
fi
if [ -n "$overlay_setup" ]; then
  if [ -r "$overlay_setup" ]; then
    set +u
    # shellcheck disable=SC1090
    source "$overlay_setup"
    set -u
    pass "ROS overlay sourced: $overlay_setup"
  else
    fail "ROS overlay setup is not readable: $overlay_setup"
  fi
fi

section 'DDS and domain'
printf 'ROS_DOMAIN_ID=%s\n' "${ROS_DOMAIN_ID:-unset}"
printf 'RMW_IMPLEMENTATION=%s\n' "${RMW_IMPLEMENTATION:-unset}"
printf 'CYCLONEDDS_URI=%s\n' "${CYCLONEDDS_URI:-unset}"
if [ -n "${ROS_DOMAIN_ID:-}" ]; then
  pass 'ROS_DOMAIN_ID is explicitly set'
else
  warn 'ROS_DOMAIN_ID is unset; Domain 0 can receive unrelated LAN discovery traffic'
fi
if [ "${RMW_IMPLEMENTATION:-}" = rmw_cyclonedds_cpp ]; then
  pass 'Cyclone DDS is selected'
else
  warn 'rmw_cyclonedds_cpp is not explicitly selected'
fi
case "${CYCLONEDDS_URI:-}" in
  file://*)
    cyclone_path=${CYCLONEDDS_URI#file://}
    if [ -r "$cyclone_path" ]; then
      pass "Cyclone DDS configuration is readable: $cyclone_path"
    else
      fail "Cyclone DDS configuration is not readable: $cyclone_path"
    fi
    ;;
  '') warn 'CYCLONEDDS_URI is unset' ;;
  *) warn 'CYCLONEDDS_URI is not a file:// URI; inspect it manually' ;;
esac

if command_exists pgrep; then
  daemon_count=$(pgrep -fc '[/]_ros2_daemon' 2>/dev/null || true)
  printf 'ros2_daemon_processes=%s\n' "$daemon_count"
  if [ "$daemon_count" -le 1 ]; then
    pass 'no duplicate ROS 2 daemon processes detected'
  else
    warn 'multiple ROS 2 daemon processes are running; check stale domain/RMW daemons'
  fi
fi

section 'Build toolchain'
for tool_name in git cmake gcc g++ colcon rosdep; do
  if command_exists "$tool_name"; then
    tool_path=$(command -v "$tool_name")
    pass "build tool present: $tool_name ($tool_path)"
  else
    fail "build tool missing: $tool_name"
  fi
done

section 'Exact Foxy Python APIs used by the project'
if command_exists python3 && [ -n "${ROS_DISTRO:-}" ]; then
  if python3 - <<'PY'
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
    PythonExpression,
)
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node as RclpyNode
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener
print('core_imports=ok')
PY
  then
    pass 'core launch/rclpy/tf2 imports succeed'
  else
    fail 'one or more core launch/rclpy/tf2 imports failed'
  fi

  api_output=$(python3 - <<'PY' 2>&1
import inspect
import launch.substitutions as substitutions
from launch.substitutions import LaunchConfiguration
import launch_ros.parameter_descriptions as parameter_descriptions
from launch_ros.substitutions import FindPackageShare

print('AndSubstitution=' + str(hasattr(substitutions, 'AndSubstitution')))
print('NotSubstitution=' + str(hasattr(substitutions, 'NotSubstitution')))
print('PythonExpression=' + str(hasattr(substitutions, 'PythonExpression')))
print('ParameterFile=' + str(hasattr(parameter_descriptions, 'ParameterFile')))
if hasattr(parameter_descriptions, 'ParameterFile'):
    print('ParameterFile.allow_substs=' + str(
        'allow_substs' in inspect.signature(
            parameter_descriptions.ParameterFile.__init__).parameters))
else:
    print('ParameterFile.allow_substs=False')
print('ParameterValue=' + str(hasattr(parameter_descriptions, 'ParameterValue')))
if hasattr(parameter_descriptions, 'ParameterValue'):
    print('ParameterValue.value_type=' + str(
        'value_type' in inspect.signature(
            parameter_descriptions.ParameterValue.__init__).parameters))
else:
    print('ParameterValue.value_type=False')
try:
    FindPackageShare(LaunchConfiguration('driver_package'))
except Exception as exc:
    print('FindPackageShare.dynamic=False:' + type(exc).__name__ + ':' + str(exc))
else:
    print('FindPackageShare.dynamic=True')
PY
  )
  printf '%s\n' "$api_output"
  for required_api in \
    'FindPackageShare.dynamic=True' \
    'PythonExpression=True' \
    'ParameterValue.value_type=True'; do
    if printf '%s\n' "$api_output" | grep -Fqx "$required_api"; then
      pass "$required_api"
    else
      fail "$required_api is unavailable"
    fi
  done
  for avoided_api in \
    ParameterFile.allow_substs \
    AndSubstitution \
    NotSubstitution; do
    if printf '%s\n' "$api_output" | grep -Fqx "$avoided_api=True"; then
      pass "$avoided_api is available"
    else
      warn "$avoided_api is unavailable; project launch files must avoid it"
    fi
  done
fi

section 'ROS package index'
required_ros_packages='rclpy launch launch_ros sensor_msgs std_msgs geometry_msgs action_msgs tf2_ros rosidl_default_runtime'
if command_exists ros2; then
  for package_name in $required_ros_packages; do
    if ros2 pkg prefix "$package_name" >/dev/null 2>&1; then
      pass "ROS package present: $package_name"
    else
      fail "ROS package missing: $package_name"
    fi
  done
  for camera_package in orbbec_camera astra_camera; do
    if ros2 pkg prefix "$camera_package" >/dev/null 2>&1; then
      pass "camera driver package present: $camera_package"
    else
      warn "camera driver package not found: $camera_package"
    fi
  done
else
  fail 'ros2 command is missing'
fi

section 'Python packages'
for module_name in numpy cv2; do
  if python3 -c "import $module_name" >/dev/null 2>&1; then
    version=$(python3 -c "import $module_name as m; print(getattr(m, '__version__', 'unknown'))" 2>/dev/null || true)
    pass "Python module present: $module_name ($version)"
  else
    fail "Python module missing: $module_name"
  fi
done
if python3 -c 'import torch' >/dev/null 2>&1; then
  version=$(python3 -c "import torch; print(getattr(torch, '__version__', 'unknown'))" 2>/dev/null || true)
  pass "Python module present: torch ($version)"
elif [ "$require_perception" -eq 1 ]; then
  fail 'Python module required for current dual-model detector is missing: torch'
else
  warn 'optional perception module missing: torch'
fi

ultralytics_probe=$(python3 -c \
  'import ultralytics; from ultralytics import YOLO; print(getattr(ultralytics, "__version__", "unknown")); print("YOLO_import=ok")' \
  2>&1)
ultralytics_status=$?
if [ "$ultralytics_status" -eq 0 ]; then
  printf '%s\n' "$ultralytics_probe"
  ultralytics_metadata=$(python3 - <<'PY' 2>/dev/null || true
from importlib import metadata
dist = metadata.metadata('ultralytics')
print('ultralytics_requires_python=' + str(dist.get('Requires-Python')))
PY
  )
  printf '%s\n' "$ultralytics_metadata"
  pass 'Ultralytics package and YOLO class import successfully'
  if printf '%s\n' "$ultralytics_probe" | grep -q 'Python.*required'; then
    if [ "$require_perception" -eq 1 ]; then
      fail 'installed Ultralytics explicitly reports that Python 3.8 is unsupported'
    else
      warn 'installed Ultralytics explicitly reports that Python 3.8 is unsupported'
    fi
  fi
elif [ "$require_perception" -eq 1 ]; then
  printf '%s\n' "$ultralytics_probe"
  fail 'Ultralytics or its YOLO class cannot be imported'
else
  warn 'optional perception module missing or unusable: ultralytics'
fi

section 'Project source'
if [ -n "$project_root" ]; then
  if [ ! -d "$project_root" ]; then
    fail "project root does not exist: $project_root"
  else
    pass "project root exists: $project_root"
    PROJECT_ROOT="$project_root" python3 - <<'PY'
import ast
import os
from pathlib import Path

root = Path(os.environ['PROJECT_ROOT'])
bad = []
count = 0
for path in sorted(root.glob('src/**/*.py')):
    if any(part in {'build', 'install', 'log', '__pycache__'} for part in path.parts):
        continue
    count += 1
    try:
        source = path.read_text(encoding='utf-8')
        ast.parse(source, filename=str(path), feature_version=(3, 8))
    except Exception as exc:
        bad.append((path, exc))
print('python_files_checked=' + str(count))
for path, exc in bad:
    print('syntax_error=' + str(path) + ':' + str(exc))
raise SystemExit(1 if bad else 0)
PY
    if [ "$?" -eq 0 ]; then
      pass 'project Python files parse with Python 3.8 grammar'
    else
      fail 'project contains Python syntax incompatible with Python 3.8'
    fi

    if grep -R -n \
        -e AndSubstitution -e NotSubstitution -e ParameterFile \
        "$project_root/src/limo_cleanup_bringup/launch" \
        --include='*.py' >/tmp/limo_audit_foxy_apis.$$ 2>/dev/null; then
      fail 'project launch files still use APIs unavailable on Foxy:'
      sed -n '1,40p' /tmp/limo_audit_foxy_apis.$$
    else
      pass 'project launch files avoid Foxy-incompatible APIs'
    fi
    rm -f /tmp/limo_audit_foxy_apis.$$

    if grep -R -n -F '/mnt/c/' "$project_root/src" \
        --include='*.py' --include='*.yaml' --include='*.sh' \
        --exclude-dir='test' \
        >/tmp/limo_audit_wsl_paths.$$ 2>/dev/null; then
      warn 'WSL-specific /mnt/c paths remain in deployable files:'
      sed -n '1,40p' /tmp/limo_audit_wsl_paths.$$
    else
      pass 'no WSL-specific /mnt/c paths found in deployable files'
    fi
    rm -f /tmp/limo_audit_wsl_paths.$$
  fi
else
  warn 'project source audit skipped; pass --project-root after copying source'
fi

if [ "$check_graph" -eq 1 ]; then
  section 'Bounded read-only ROS graph query'
  if command_exists timeout && command_exists ros2; then
    if ROS2CLI_NO_DAEMON=1 timeout -k 2 10 ros2 topic list >/tmp/limo_audit_topics.$$ 2>&1; then
      pass 'daemon-free ros2 topic list completed'
      sed -n '1,80p' /tmp/limo_audit_topics.$$
    else
      status=$?
      fail "daemon-free ros2 topic list failed (exit=$status)"
      sed -n '1,80p' /tmp/limo_audit_topics.$$
    fi
    rm -f /tmp/limo_audit_topics.$$
  else
    fail 'timeout or ros2 is unavailable'
  fi
fi

section 'Summary'
printf 'pass=%s warn=%s fail=%s\n' "$pass_count" "$warn_count" "$fail_count"
if [ "$fail_count" -gt 0 ]; then
  exit 1
fi
exit 0
