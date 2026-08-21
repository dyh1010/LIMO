#!/usr/bin/env bash

set -euo pipefail

bundle=/tmp/arm_foxy_dryrun_20260813_v3.tar.gz
root=/tmp/arm_foxy_dryrun_20260813_v3
source_dir="$root/source"
work_dir="$root/work"
evidence_dir="$root/evidence"
expected_sha=${ARM_DRYRUN_SHA256:?ARM_DRYRUN_SHA256 is required}
domain_id=${ARM_FOXY_DRY_RUN_DOMAIN_ID:-219}
timeout_s=${ARM_FOXY_DRY_RUN_TIMEOUT_S:-600}
summary=/tmp/arm_foxy_dryrun_20260813_v3_summary.log
preserved_evidence=/tmp/arm_foxy_dryrun_20260813_v3_evidence
baseline_pid_file="$evidence_dir/runner_pids_before.txt"
after_pid_file="$evidence_dir/runner_pids_after.txt"
residual_pid_file="$evidence_dir/runner_new_pids.txt"
cleanup_pid_file="$evidence_dir/runner_process_cleanup.txt"

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

pid_still_matches() {
  ps -p "$1" -o args= | awk \
    -v gateway_a='cleanup_arm_' -v gateway_b='gateway' \
    -v smoke_a='arm_gateway_' -v smoke_b='smoke_client' '
    $0 ~ gateway_a gateway_b || $0 ~ smoke_a smoke_b { found=1 }
    END { exit !found }
  '
}

finish() {
  local status=$?
  local cleanup_failed=0
  trap - EXIT INT TERM HUP

  if [ -d "$evidence_dir" ] && [ ! -e "$preserved_evidence" ]; then
    mv "$evidence_dir" "$preserved_evidence" || cleanup_failed=1
  fi

  case "$root" in
    /tmp/arm_foxy_dryrun_20260813_v3)
      rm -rf -- "$source_dir" "$work_dir" "$root" || cleanup_failed=1
      ;;
    *)
      printf 'ERROR: refused unexpected cleanup root: %s\n' "$root" \
        >>"$summary"
      cleanup_failed=1
      ;;
  esac
  case "$bundle" in
    /tmp/arm_foxy_dryrun_20260813_v3.tar.gz)
      rm -f -- "$bundle" || cleanup_failed=1
      ;;
    *)
      printf 'ERROR: refused unexpected bundle cleanup: %s\n' "$bundle" \
        >>"$summary"
      cleanup_failed=1
      ;;
  esac

  if [ -e "$root" ] || [ -e "$bundle" ]; then
    cleanup_failed=1
  fi
  if [ "$cleanup_failed" -ne 0 ] && [ "$status" -eq 0 ]; then
    status=90
  fi

  printf 'TARGET_V3_CLEANUP status=%s root_removed=%s bundle_removed=%s ' \
    "$cleanup_failed" "$([ ! -e "$root" ] && echo true || echo false)" \
    "$([ ! -e "$bundle" ] && echo true || echo false)" >>"$summary"
  printf 'evidence=%s summary=%s\n' "$preserved_evidence" "$summary" \
    >>"$summary"

  if [ "$status" -eq 0 ]; then
    printf 'TARGET_FOXY_ARM_DRY_RUN_PASS sha256=%s evidence=%s summary=%s\n' \
      "$observed_sha" "$preserved_evidence" "$summary" | tee -a "$summary"
  else
    printf 'TARGET_FOXY_ARM_DRY_RUN_FAIL status=%s sha256=%s ' \
      "$status" "${observed_sha:-UNAVAILABLE}" | tee -a "$summary"
    printf 'evidence=%s summary=%s\n' "$preserved_evidence" "$summary" \
      | tee -a "$summary"
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

case "$timeout_s" in
  ''|*[!0-9]*) echo 'ERROR: timeout must be an integer' >&2; exit 1 ;;
esac
if [ "$timeout_s" -lt 60 ] || [ "$timeout_s" -gt 1800 ]; then
  echo 'ERROR: timeout must be in 60..1800 seconds' >&2
  exit 1
fi

[ -f "$bundle" ] || { echo 'ERROR: uploaded v3 bundle missing' >&2; exit 2; }
[ ! -e "$root" ] || { echo 'ERROR: fixed v3 root already exists' >&2; exit 3; }
[ ! -e "$preserved_evidence" ] || {
  echo 'ERROR: preserved v3 evidence path already exists' >&2
  exit 3
}

observed_sha=$(sha256sum "$bundle" | awk '{print $1}')
[ "$observed_sha" = "$expected_sha" ] || {
  echo "ERROR: bundle SHA mismatch: $observed_sha" >&2
  exit 4
}

mkdir "$root" "$source_dir" "$work_dir" "$evidence_dir"
snapshot_arm_pids >"$baseline_pid_file"
tar -xzf "$bundle" -C "$source_dir"

export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID="$domain_id"
export ARM_FOXY_DRY_RUN_DOMAIN_ID="$domain_id"
export ARM_FOXY_DRY_RUN_WORK_DIR="$work_dir"
export ARM_FOXY_DRY_RUN_EVIDENCE_DIR="$evidence_dir"

printf 'TARGET_V3_START root=%s bundle=%s sha256=%s domain=%s timeout=%s\n' \
  "$root" "$bundle" "$observed_sha" "$domain_id" "$timeout_s" \
  >"$summary"

set +e
timeout --signal=TERM --kill-after=15s "${timeout_s}s" \
  bash "$source_dir/scripts/verify_arm_gateway_foxy_dry_run.sh" \
  "$source_dir" >>"$summary" 2>&1
run_status=$?
set -e

printf 'TARGET_V3_RUN_EXIT status=%s\n' "$run_status" >>"$summary"
snapshot_arm_pids >"$after_pid_file"
awk 'FILENAME == ARGV[1] { before[$1]=1; next }
     !($1 in before) { print }' \
  "$baseline_pid_file" "$after_pid_file" >"$residual_pid_file"

: >"$cleanup_pid_file"
residual_found=0
while IFS=$'\t' read -r pid args; do
  [ -n "${pid:-}" ] || continue
  residual_found=1
  if pid_still_matches "$pid"; then
    printf 'TERM\t%s\t%s\n' "$pid" "$args" >>"$cleanup_pid_file"
    kill -TERM "$pid" 2>>"$cleanup_pid_file" || true
    for attempt in 1 2 3 4 5; do
      pid_still_matches "$pid" || break
      sleep 0.2
    done
    if pid_still_matches "$pid"; then
      printf 'KILL\t%s\t%s\n' "$pid" "$args" >>"$cleanup_pid_file"
      kill -KILL "$pid" 2>>"$cleanup_pid_file" || true
    fi
  else
    printf 'ALREADY_EXITED\t%s\t%s\n' \
      "$pid" "$args" >>"$cleanup_pid_file"
  fi
done <"$residual_pid_file"

if [ "$residual_found" -ne 0 ] && [ "$run_status" -eq 0 ]; then
  run_status=92
fi
exit "$run_status"
