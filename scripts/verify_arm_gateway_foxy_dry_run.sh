#!/usr/bin/env bash

set -euo pipefail

project_root=${1:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}
ros_setup=${ROS_SETUP:-/opt/ros/foxy/setup.bash}
domain_id=${ARM_FOXY_DRY_RUN_DOMAIN_ID:-219}
work_dir=${ARM_FOXY_DRY_RUN_WORK_DIR:?ARM_FOXY_DRY_RUN_WORK_DIR is required}
evidence_dir=${ARM_FOXY_DRY_RUN_EVIDENCE_DIR:?ARM_FOXY_DRY_RUN_EVIDENCE_DIR is required}
build_dir="$work_dir/build"
install_dir="$work_dir/install"
colcon_log_dir="$work_dir/colcon-log"
baseline_pid_file="$evidence_dir/arm_gateway_pids_before.txt"
after_pid_file="$evidence_dir/arm_gateway_pids_after.txt"
new_pid_file="$evidence_dir/arm_gateway_new_pids.txt"

case "$work_dir" in
  /tmp/arm_foxy_dryrun_20260813_v3/work) ;;
  *) echo "ERROR: unexpected v3 work path: $work_dir" >&2; exit 1 ;;
esac
case "$evidence_dir" in
  /tmp/arm_foxy_dryrun_20260813_v3/evidence) ;;
  *) echo "ERROR: unexpected v3 evidence path: $evidence_dir" >&2; exit 1 ;;
esac
case "$domain_id" in
  ''|*[!0-9]*)
    echo 'ERROR: ARM_FOXY_DRY_RUN_DOMAIN_ID must be an integer' >&2
    exit 1
    ;;
esac
if [ "$domain_id" -lt 0 ] || [ "$domain_id" -gt 232 ]; then
  echo 'ERROR: ARM_FOXY_DRY_RUN_DOMAIN_ID must be in 0..232' >&2
  exit 1
fi

mkdir -p "$work_dir" "$evidence_dir"

snapshot_arm_pids() {
  ps -eo pid=,args= | awk \
    -v gateway_a='cleanup_arm_' -v gateway_b='gateway' \
    -v smoke_a='arm_gateway_' -v smoke_b='smoke_client' '
    $0 ~ gateway_a gateway_b || $0 ~ smoke_a smoke_b {
      pid=$1
      $1=""
      sub(/^[[:space:]]+/, "")
      print pid "\t" $0
    }
  ' | sort -n
}

snapshot_arm_pids >"$baseline_pid_file"

[ -f "$ros_setup" ] || {
  echo "ERROR: Foxy setup missing: $ros_setup" >&2
  exit 3
}

set +u
# shellcheck disable=SC1090
source "$ros_setup"
set -u

for required_command in awk colcon grep ps python3 ros2 sort tee; do
  if ! command -v "$required_command" >"$evidence_dir/command_${required_command}.txt" 2>&1; then
    echo "ERROR: required command missing: $required_command" >&2
    exit 2
  fi
done

[ -d "$project_root/src/limo_cleanup_interfaces" ] || {
  echo 'ERROR: interface package source missing' >&2
  exit 4
}
[ -d "$project_root/src/limo_cleanup_executor" ] || {
  echo 'ERROR: executor package source missing' >&2
  exit 5
}

python3 - "$project_root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
backend = (
    root / 'src/limo_cleanup_executor/limo_cleanup_executor/arm_backends.py'
).read_text(encoding='utf-8')
node = (
    root / 'src/limo_cleanup_executor/limo_cleanup_executor/arm_gateway_node.py'
).read_text(encoding='utf-8')
launch = (
    root / 'src/limo_cleanup_executor/launch/arm_gateway_dry_run.launch.py'
).read_text(encoding='utf-8')
config = (
    root / 'src/limo_cleanup_executor/config/arm_gateway_dry_run.yaml'
).read_text(encoding='utf-8')

for token in (
        'import_module', 'from pymycobot', 'import pymycobot',
        'client_factory or'):
    if token in backend:
        raise SystemExit('ERROR: default vendor path token: ' + token)
if 'client_factory is required for offline contract tests' not in backend:
    raise SystemExit('ERROR: explicit client factory gate is missing')
if "self.backend_name != 'dry_run'" not in node:
    raise SystemExit('ERROR: ROS backend gate is missing')
if "'backend': 'dry_run'" not in launch:
    raise SystemExit('ERROR: launch does not pin dry_run')
for name, source in (('launch', launch), ('config', config)):
    if '/' + 'dev/' in source or 'pymycobot' in source:
        raise SystemExit('ERROR: {} contains a hardware path'.format(name))
PY

export PYTHONDONTWRITEBYTECODE=1
export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID="$domain_id"

printf 'FOXY_ARM_DRY_RUN_START domain=%s evidence=%s work_dir=%s\n' \
  "$ROS_DOMAIN_ID" "$evidence_dir" "$work_dir"

colcon --log-base "$colcon_log_dir" build \
  --base-paths "$project_root/src" \
  --packages-select limo_cleanup_interfaces limo_cleanup_executor \
  --build-base "$build_dir" \
  --install-base "$install_dir" \
  --event-handlers console_cohesion+ \
  2>&1 | tee "$evidence_dir/colcon_build.log"

set +u
# shellcheck disable=SC1090
source "$install_dir/setup.bash"
set -u

colcon --log-base "$colcon_log_dir" test \
  --base-paths "$project_root/src" \
  --packages-select limo_cleanup_interfaces limo_cleanup_executor \
  --build-base "$build_dir" \
  --install-base "$install_dir" \
  --executor sequential \
  --event-handlers console_cohesion+ \
  2>&1 | tee "$evidence_dir/colcon_test.log"

colcon test-result --test-result-base "$build_dir" --verbose \
  2>&1 | tee "$evidence_dir/colcon_test_result.log"

python3 -m unittest discover \
  -s "$project_root/src/limo_cleanup_executor/test" \
  -p 'test_arm*.py' -v \
  2>&1 | tee "$evidence_dir/arm_unittest.log"

python3 -m pytest -q -p no:cacheprovider \
  "$project_root/src/limo_cleanup_executor/test/test_arm_gateway_ros_smoke.py" \
  2>&1 | tee "$evidence_dir/arm_ros_smoke.log"

ros2 launch limo_cleanup_executor arm_gateway_dry_run.launch.py \
  --show-args 2>&1 | tee "$evidence_dir/arm_launch_show_args.log"

snapshot_arm_pids >"$after_pid_file"
awk 'FILENAME == ARGV[1] { before[$1]=1; next }
     !($1 in before) { print }' \
  "$baseline_pid_file" "$after_pid_file" >"$new_pid_file"
if [ -s "$new_pid_file" ]; then
  echo 'ERROR: new arm dry-run processes remain; no process was killed' >&2
  exit 7
fi

printf 'FOXY_ARM_DRY_RUN_PASS domain=%s evidence=%s work_dir=%s\n' \
  "$ROS_DOMAIN_ID" "$evidence_dir" "$work_dir"
