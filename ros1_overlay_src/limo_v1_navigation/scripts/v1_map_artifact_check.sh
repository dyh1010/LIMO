#!/usr/bin/env bash
set -euo pipefail

# Prepared offline. save/reload require a fresh field authorization.

usage() {
  printf 'Usage: %s verify|save|reload /absolute/path/to/map_stem\n' "$0" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'BLOCKED: required command is missing: %s\n' "$1" >&2
    exit 1
  }
}

require_absolute_stem() {
  case "$MAP_STEM" in
    /*) ;;
    *) printf 'BLOCKED: map stem must be an absolute path\n' >&2; exit 1 ;;
  esac
}

reject_vendor_map() {
  case "$MAP_STEM" in
    */limo_bringup/maps/*|*/map02|*/map1017)
      printf 'BLOCKED: vendor or rejected map path\n' >&2
      exit 1
      ;;
  esac
}

resolve_image_path() {
  local image_value
  image_value="$(awk -F: '/^[[:space:]]*image[[:space:]]*:/{sub(/^[^:]*:[[:space:]]*/, ""); gsub(/^["\047]|["\047]$/, ""); print; exit}' "$MAP_YAML")"
  [ -n "$image_value" ] || {
    printf 'BLOCKED: YAML has no parseable image field: %s\n' "$MAP_YAML" >&2
    exit 1
  }
  case "$image_value" in
    /*) MAP_IMAGE="$image_value" ;;
    *) MAP_IMAGE="$(dirname "$MAP_YAML")/$image_value" ;;
  esac
}

verify_artifacts() {
  [ -s "$MAP_YAML" ] || {
    printf 'BLOCKED: YAML is missing or empty: %s\n' "$MAP_YAML" >&2
    exit 1
  }
  resolve_image_path
  [ -s "$MAP_IMAGE" ] || {
    printf 'BLOCKED: map image is missing or empty: %s\n' "$MAP_IMAGE" >&2
    exit 1
  }
  printf 'MAP_ID=%s\n' "$(basename "$MAP_STEM")"
  printf 'MAP_YAML=%s\n' "$MAP_YAML"
  printf 'MAP_IMAGE=%s\n' "$MAP_IMAGE"
  sha256sum "$MAP_YAML" "$MAP_IMAGE"
  grep -E '^[[:space:]]*(image|resolution|origin|negate|occupied_thresh|free_thresh):' "$MAP_YAML"
}

[ "$#" -eq 2 ] || usage
MODE="$1"
MAP_STEM="$2"
MAP_YAML="${MAP_STEM}.yaml"
MAP_IMAGE=''
require_absolute_stem
reject_vendor_map

case "$MODE" in
  verify)
    require_command sha256sum
    verify_artifacts
    ;;

  save)
    [ "${V1_FIELD_AUTHORIZATION:-}" = 'YES' ] || {
      printf 'BLOCKED: fresh field authorization is required\n' >&2
      exit 1
    }
    require_command rosrun
    require_command rostopic
    require_command sha256sum
    [ "$(rostopic type /map 2>/dev/null || true)" = 'nav_msgs/OccupancyGrid' ] || {
      printf 'BLOCKED: /map is absent or has the wrong type\n' >&2
      exit 1
    }
    [ ! -e "$MAP_YAML" ] && [ ! -e "${MAP_STEM}.pgm" ] || {
      printf 'BLOCKED: refusing to overwrite existing artifacts\n' >&2
      exit 1
    }
    mkdir -p "$(dirname "$MAP_STEM")"
    rosrun map_server map_saver -f "$MAP_STEM"
    verify_artifacts
    ;;

  reload)
    [ "${V1_FIELD_AUTHORIZATION:-}" = 'YES' ] || {
      printf 'BLOCKED: fresh field authorization is required\n' >&2
      exit 1
    }
    require_command rosnode
    require_command rostopic
    require_command rosrun
    require_command sha256sum
    verify_artifacts
    EXISTING_NODES="$(rosnode list 2>/dev/null | grep -v '^/rosout$' || true)"
    [ -z "$EXISTING_NODES" ] || {
      printf 'BLOCKED: standalone reload requires an empty ROS1 graph\n%s\n' "$EXISTING_NODES" >&2
      exit 1
    }
    RELOAD_LOG="${TMPDIR:-/tmp}/v1_map_reload_check.$$.log"
    MAP_SERVER_PID=''
    cleanup() {
      if [ -n "$MAP_SERVER_PID" ] && kill -0 "$MAP_SERVER_PID" 2>/dev/null; then
        kill "$MAP_SERVER_PID"
        wait "$MAP_SERVER_PID" 2>/dev/null || true
      fi
    }
    trap cleanup EXIT INT TERM
    rosrun map_server map_server "$MAP_YAML" __name:=v1_map_reload_check >"$RELOAD_LOG" 2>&1 &
    MAP_SERVER_PID="$!"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      [ "$(rostopic type /map 2>/dev/null || true)" = 'nav_msgs/OccupancyGrid' ] && break
      sleep 1
    done
    [ "$(rostopic type /map 2>/dev/null || true)" = 'nav_msgs/OccupancyGrid' ] || {
      printf 'BLOCKED: map_server did not publish /map\n' >&2
      sed -n '1,200p' "$RELOAD_LOG" >&2
      exit 1
    }
    rostopic echo -n 1 /map/header/frame_id
    rostopic echo -n 1 /map_metadata
    printf 'RELOAD_CHECK=PASS_FILE_LOAD_ONLY\n'
    ;;

  *) usage ;;
esac
