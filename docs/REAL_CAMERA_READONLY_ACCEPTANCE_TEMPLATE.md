# HISTORICAL ROS2/Foxy camera worksheet — NON_AUTHORITATIVE / DO NOT RUN

> [!CAUTION]
> **ROS1/Noetic is the current field authority. / 当前现场权威为 ROS1 Noetic。**
> This file is retained only as historical ROS2/Foxy/rosbag2 provenance. It
> must not be run and cannot prove or authorize current ROS1/Noetic build,
> install, camera operation, four-scene evidence, TF/3D, latency, field, or
> delivery PASS. / 本文仅保留历史迁移事实，禁止执行，也不能授权当前现场或交付。
> Start from
> [`docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md`](PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md),
> then follow the ROS1/Noetic field runbook to its host-owned atomic launcher.

# DaBai real-camera read-only acceptance result template (historical body)

This is a recording template, not authorization to connect to a robot or
camera. Keep base, navigation, arm, gripper, cleanup executor, vendor follow,
and all command bridges stopped throughout the procedure.

## Authorization and identity

- Operator:
- Main-task authorization reference:
- Robot identity/hostname:
- Maintenance window:
- Repository commit:
- Controlled release manifest SHA-256:
- Source-manifest artifact SHA-256:
- Canonical source-set SHA-256:
- Recovery archive path and SHA-256:
- Python / Torch / Ultralytics versions:
- Bottle model SHA-256:
- Trash-bin model SHA-256:
- Field evidence directory (new and access-restricted):
- Evidence directory confirmed absent before creation:

## Static preflight

The following legacy commands are retained as non-executable historical text.
Do not copy or run them; use the current operations index above.

```text
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: python3 scripts/generate_perception_source_manifest.py
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --workspace '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws'
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --release-id FIELD_ID-source-SHA
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --generated-at-unix-sec EPOCH_SECONDS
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --output /approved/evidence/FIELD_ID/source_manifest.json
```

```text
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: python3 scripts/perception_release_preflight.py
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --project-root '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws'
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --release-dir /path/to/perception_rgbd_release_20260812
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --models-dir '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws/models'
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --release-id FIELD_ID-source-SHA
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --source-manifest /approved/evidence/FIELD_ID/source_manifest.json
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --require-runtime
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --report /tmp/limo_perception_release_preflight.json
```

- `passed`:
- Report SHA-256:
- Report `source_manifest_artifact_sha256` equals the manifest file hash:
- Report `source_set_sha256` equals the manifest canonical source-set hash:
- Manifest includes `perception:limo_cleanup_perception/typed_raw_binding.py`:
- Any FAIL/WARN and disposition:

## Isolated interfaces + perception build evidence

The machine-readable build record must use schema version 2 and exactly mirror
the commands in the field-readiness runbook. Record:

- Workspace root (same root used by manifest generation and preflight):
- Isolation root (new `/tmp/limo_v2_colcon_FIELD_ID`):
- `cwd` equals workspace root:
- Exact `build_argv` array:
- Exact `test_argv` array:
- Exact `test_result_argv` array:
- Exit codes `build=0`, `test=0`, `test_result=0`:
- Test failures `0`:
- `nodes_started=false`:
- Build, test and test-result log paths / sizes / SHA-256 (all non-empty):
- Source-manifest artifact path / size / SHA-256:
- Embedded required names, entries and `source_set_sha256` exactly match the
  generated source manifest:
- Build validation report path / size / SHA-256:

## Graph-isolation evidence

Record both ROS1 and ROS2 environments separately. Do not source Noetic and
Foxy in one shell.

- ROS1 nodes checked:
- ROS2 nodes checked:
- `/dev/ttyTHS0` owner:
- Command-topic publisher/subscriber audit:
- Confirmed stopped components:

## Exact four-stream contract

| Stream | Expected topic | Actual type | frame_id | width x height | stamp |
| --- | --- | --- | --- | --- | --- |
| RGB | `/camera/color/image_raw` | `sensor_msgs/msg/Image` | | | |
| aligned depth | `/camera/depth/image_raw` | `sensor_msgs/msg/Image` | | | |
| RGB CameraInfo | `/camera/color/camera_info` | `sensor_msgs/msg/CameraInfo` | | | |
| depth CameraInfo | `/camera/depth/camera_info` | `sensor_msgs/msg/CameraInfo` | | | |

- Timestamp span, maximum observed:
- Required maximum: `0.15 s`
- Frame equality:
- Resolution equality:
- Depth encoding:
- Depth scale/unit:
- Known-distance median and error:
- `base_link -> camera_color_optical_frame` TF:
- Independent extrinsics reference and tolerance result:

## Per-scene raw rosbag2 evidence

Metadata-only evidence is not accepted. For each scene, retain one uncompressed
rosbag2 SQLite `.db3`, its original `metadata.yaml`, and an offline index made
from the stopped `.db3`. The bag must contain exactly the four configured
RGB-D topics plus `/tf` and `/tf_static`; it must contain no additional or
control topic. Capture requires separate on-site read-only authorization and
completed no-actuation checks. The index step below starts no camera or ROS
node and publishes nothing.

| Scene | capture_id | Independent arrangement | Capture start/end Unix | `.db3` path / size / SHA-256 | `metadata.yaml` SHA-256 | Index path / SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| `background` | | | | | | |
| `bin_only` | | | | | | |
| `bottle_in_bin` | | | | | | |
| `bottle_outside` | | | | | | |

For each stopped bag, use an index output path that does not exist and fill the
actual scene, capture ID, `.db3` path, and deployed topic names. Run this only
from a current isolated install where the indexer entry and tests are proven;
do not mark that build PASS merely because this template contains the command:

```text
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: set -euo pipefail
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: umask 077
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: SCENE=background
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: CAPTURE_ID=FIELD_ID-background-001
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: BAG_DB3=/approved/evidence/FIELD_ID/FIELD_ID-background-001/ACTUAL.db3
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: INDEX_JSON=/approved/evidence/FIELD_ID/FIELD_ID-background-001.rgbd-index.json
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: test -f "$BAG_DB3"
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: test ! -e "$INDEX_JSON"
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: ros2 run limo_cleanup_perception rgbd_bag_indexer
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --bag "$BAG_DB3"
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --capture-id "$CAPTURE_ID"
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --scene "$SCENE"
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --rgb-topic /camera/color/image_raw
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --aligned-depth-topic /camera/depth/image_raw
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --rgb-camera-info-topic /camera/color/camera_info
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --depth-camera-info-topic /camera/depth/camera_info
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --expected-topic-manifest /current/install/limo_cleanup_perception/share/limo_cleanup_perception/fixtures/rgbd_expected_topics.json
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: --output "$INDEX_JSON"
```

Per scene, copy the indexer's exact values into the review record rather than
estimating them:

| Topic | Required type | Message count | First record time | Last record time | Offered QoS proven |
| --- | --- | --- | --- | --- | --- |
| RGB topic | `sensor_msgs/msg/Image` | | | | |
| aligned-depth topic | `sensor_msgs/msg/Image` | | | | |
| RGB CameraInfo topic | `sensor_msgs/msg/CameraInfo` | | | | |
| depth CameraInfo topic | `sensor_msgs/msg/CameraInfo` | | | | |
| `/tf` | `tf2_msgs/msg/TFMessage` | | | | |
| `/tf_static` | `tf2_msgs/msg/TFMessage` | | | | transient-local: |

- Complete recorded topic set equals the six approved topics:
- Installed expected-topic manifest path / size / SHA-256:
- QoS history/depth/reliability/durability all parse and match manifest policy:
- QoS liveliness parses and matches the frozen `AUTOMATIC` policy:
- Header/TF frame IDs contain no leading slash, whitespace/control, empty,
  `.` or `..` segment:
- Depth step is aligned to its encoding element size:
- Forbidden topics found (must be empty):
- Unexpected topics found (must be empty):
- Four RGB-D streams each have at least 30 messages:
- Topic types and serialization formats match:
- Count and first/last time agree with synchronized RGB-D evidence:
- `/tf_static` QoS durability is proven, not left blank:
- `/tf` and `/tf_static` are present with the exact type and required QoS:
- Decoded TF artifact binds the recorded `base_link -> camera` transform:
- Every accepted RGB bundle has one unambiguous, in-age TF chain:
- Index `capture_id` equals arrangement `capture_id`:
- Index scene equals arrangement scene:
- Capture time range lies within the recorded arrangement window:
- Raw bag/index fingerprints are unique across all four scenes:
- Index outputs were created exclusively and no prior file was overwritten:

## Typed-frame to raw-payload binding

- Collector manifest exact schema validated:
- `read_only=true`, `authorizes_motion=false`,
  `publishes_ros_messages=false`:
- Collector subscribed only to `/cleanup/perception/frames` with
  `limo_cleanup_interfaces/msg/PerceptionFrame`:
- Collector target at least 30, completed, no duplicate/serialization error,
  and complete five-topic control deny-list:
- `typed_raw_binding` path / size / SHA-256:
- Typed frame count / raw bundle count / paired count:
- Unpaired typed count/rate (must be `<=0.05`, denominator nonzero):
- Unpaired raw-bundle count/rate (must be `<=0.05`, denominator nonzero):
- Every paired row binds sequence, stamp, frame, four message IDs, four payload
  hashes/sizes/receive times, sync span, and TF sample-set hash:
- Release/source-set/model hashes and capture window all match this scene:

## Readiness result

Use `start_camera:=false`; the approved camera owner must start the driver.

```text
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: ros2 launch limo_cleanup_bringup hardware_readonly_acceptance.launch.py
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: start_camera:=false
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: rgb_topic:=/camera/color/image_raw
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: depth_topic:=/camera/depth/image_raw
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: camera_info_topic:=/camera/color/camera_info
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: depth_camera_info_topic:=/camera/depth/camera_info
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: check_expected_extrinsics:=true
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: expected_x:=MEASURED_X expected_y:=MEASURED_Y expected_z:=MEASURED_Z
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: expected_roll:=MEASURED_ROLL expected_pitch:=MEASURED_PITCH
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: expected_yaw:=MEASURED_YAW
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: translation_tolerance_m:=0.02 rotation_tolerance_rad:=0.05
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: report_path:=/tmp/limo_rgbd_contract_readiness.json
```

- Readiness JSON SHA-256:
- All checks PASS:
- `no_actuation_publishers` PASS:
- `no_actuation_subscribers` PASS:
- This readiness record does not claim source build/test PASS unless a separate,
  current isolated build artifact is attached:

## Detector fail-closed observations

- Valid four-stream bundle produces expected status:
- Bottle outside bin result:
- Bottle inside bin filtered result:
- Empty background false target count:
- Stale CameraInfo causes `rgbd_contract_rejected` and no detection:
- Frame mismatch causes `rgbd_contract_rejected` and no detection:
- Resolution mismatch causes `rgbd_contract_rejected` and no detection:
- Invalid timestamp status uses JSON `null`, not Infinity/NaN:

## Exit

- Detector/readiness stopped with SIGINT:
- No camera/base/navigation/arm/gripper process left by this procedure:
- Temporary reports copied to approved evidence location:
- Original `.db3`, `metadata.yaml`, offline index, typed frames, and hashes
  preserved without modification:
- Final result: `PASS` / `FAIL`
- Remaining blocker:
