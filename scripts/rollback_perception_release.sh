#!/usr/bin/env bash
# Fail-closed rollback for the two perception release package directories.

set -euo pipefail

archive=''
workspace=''
execute=0
authorization=''

usage() {
  cat <<'EOF'
Usage: rollback_perception_release.sh --archive FILE --workspace DIR
                                      [--execute --authorization PHRASE]

Default mode is dry-run validation. Execution additionally requires the exact
phrase: AUTHORIZE_PERCEPTION_ROLLBACK_20260812
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --archive) archive=${2:-}; shift 2 ;;
    --workspace) workspace=${2:-}; shift 2 ;;
    --execute) execute=1; shift ;;
    --authorization) authorization=${2:-}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$archive" ] && [ -f "$archive" ] || {
  echo 'ERROR: --archive must name an existing tar.gz' >&2; exit 3; }
[ -n "$workspace" ] && [ -d "$workspace" ] || {
  echo 'ERROR: --workspace must name an existing directory' >&2; exit 4; }
workspace=$(cd "$workspace" && pwd -P)
[ "$workspace" != / ] && [ "$workspace" != /home ] || {
  echo 'ERROR: refusing broad workspace path' >&2; exit 5; }

members=$(tar -tzf "$archive")
[ -n "$members" ] || { echo 'ERROR: empty recovery archive' >&2; exit 6; }
unexpected=$(printf '%s\n' "$members" | awk '
  !(/^limo_cleanup_ws\/$/ ||
    /^limo_cleanup_ws\/src\/$/ ||
    /^limo_cleanup_ws\/src\/limo_cleanup_perception\/?/ ||
    /^limo_cleanup_ws\/src\/limo_cleanup_bringup\/?/) {print}')
[ -z "$unexpected" ] || {
  echo 'ERROR: archive contains out-of-scope members:' >&2
  printf '%s\n' "$unexpected" >&2
  exit 7
}

printf 'archive_sha256=%s\n' "$(sha256sum "$archive" | awk '{print $1}')"
printf 'workspace=%s\n' "$workspace"
printf '%s\n' 'archive_scope=PASS'

if [ "$execute" -eq 0 ]; then
  printf '%s\n' 'ROLLBACK_DRY_RUN_PASS'
  exit 0
fi
[ "$authorization" = 'AUTHORIZE_PERCEPTION_ROLLBACK_20260812' ] || {
  echo 'ERROR: exact rollback authorization phrase is required' >&2
  exit 8
}

target_perception="$workspace/src/limo_cleanup_perception"
target_bringup="$workspace/src/limo_cleanup_bringup"
[ -d "$target_perception" ] && [ -d "$target_bringup" ] || {
  echo 'ERROR: exact target package directories are missing' >&2; exit 9; }
stamp=$(date -u +%Y%m%dT%H%M%SZ)
staging="$workspace/.perception_rollback_staging_$stamp"
preserved="$workspace/.perception_before_rollback_$stamp"
[ ! -e "$staging" ] && [ ! -e "$preserved" ] || {
  echo 'ERROR: rollback staging or preserved path already exists' >&2
  exit 10
}
mkdir "$staging"
tar -xzf "$archive" -C "$staging"
[ -d "$staging/limo_cleanup_ws/src/limo_cleanup_perception" ] && \
  [ -d "$staging/limo_cleanup_ws/src/limo_cleanup_bringup" ] || {
    echo 'ERROR: archive lacks one of the exact package directories' >&2
    exit 11
  }
mkdir "$preserved"
mv "$target_perception" "$preserved/limo_cleanup_perception"
mv "$target_bringup" "$preserved/limo_cleanup_bringup"
mv "$staging/limo_cleanup_ws/src/limo_cleanup_perception" \
  "$target_perception"
mv "$staging/limo_cleanup_ws/src/limo_cleanup_bringup" \
  "$target_bringup"
rmdir "$staging/limo_cleanup_ws/src" \
  "$staging/limo_cleanup_ws" "$staging"
printf 'previous_packages=%s\n' "$preserved"
printf '%s\n' 'ROLLBACK_EXECUTED_REBUILD_REQUIRED'
