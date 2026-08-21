# V2 vision field evidence and offline readiness runbook

> Runtime correction (2026-08-14): the robot field runtime is ROS1 Noetic.
> The authoritative on-robot procedure is
> PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md. Every Foxy, ros2, colcon,
> rosbag2 DB3/CDR or DDS QoS command below is retained only for offline
> migration/build archaeology and must not be executed as the field camera
> entry or reported as ROS1 PASS. The user has an active camera-only approval;
> the camera is currently running, so older statements below that the camera
> is stopped are historical rather than current facts.

Everything below this correction is legacy offline reference. It does not
authorize navigation, base, arm or gripper motion, and it must not be used to
stop or operate the user's parallel non-camera nodes. The current camera-only
authorization is active and is governed by
`PERCEPTION_V2_READONLY_CAMERA_AUTHORIZATION.md` plus the ROS1 Noetic field
runbook. The frozen v5 gap crosswalk is
`evidence/PERCEPTION_V2_V5_GAP_CROSSWALK.json` and accounts for every one of
the current 37 top-level failures.

## 1. Build and install proof after the WSL environment is usable

The current Windows host cannot enter WSL and returns
`Wsl/Service/E_ACCESSDENIED` before Bash starts. That is an environment block,
not a source build failure and not a build PASS. Do not repeatedly retry it.

When a usable WSL/ROS environment is available, run this without starting any
ROS node or graph. Use a new directory name for every attempt and do not use
`--symlink-install`:

```bash
set -euo pipefail
umask 077
source /opt/ros/foxy/setup.bash
test ! -e /tmp/limo_v2_colcon_FIELD_ID
mkdir -p /tmp/limo_v2_colcon_FIELD_ID
export ROS2CLI_NO_DAEMON=1
export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID=137
export PYTHONDONTWRITEBYTECODE=1
cd '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws'
colcon --log-base /tmp/limo_v2_colcon_FIELD_ID/log build \
  --base-paths '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws/src' \
  --packages-select limo_cleanup_interfaces limo_cleanup_perception \
  --build-base /tmp/limo_v2_colcon_FIELD_ID/build \
  --install-base /tmp/limo_v2_colcon_FIELD_ID/install \
  --executor sequential --event-handlers console_cohesion+
colcon --log-base /tmp/limo_v2_colcon_FIELD_ID/test-log test \
  --packages-select limo_cleanup_interfaces limo_cleanup_perception \
  --build-base /tmp/limo_v2_colcon_FIELD_ID/build \
  --install-base /tmp/limo_v2_colcon_FIELD_ID/install \
  --executor sequential --event-handlers console_cohesion+
colcon test-result \
  --test-result-base /tmp/limo_v2_colcon_FIELD_ID/build --verbose
```

Record Python, ROS distribution, architecture, build/test exit codes, test
failure count, exact build/test/test-result commands, current required-source
manifest hash, and non-empty hashed log artifacts, plus proof that no node was
started. The expected field platform is Foxy, Python 3.8.10 and `aarch64`.
Hash the machine-readable record and reference it as `ros_build_validation` in
the readiness bundle.

The dedicated camera-only package is not yet part of that frozen two-package
readiness build record. Build and test it separately in a second new isolation
root, still without starting a graph:

```bash
set -euo pipefail
umask 077
source /opt/ros/foxy/setup.bash
test ! -e /tmp/limo_v2_dabai_sensor_FIELD_ID
mkdir -p /tmp/limo_v2_dabai_sensor_FIELD_ID
export ROS2CLI_NO_DAEMON=1
export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID=137
cd '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws'
colcon --log-base /tmp/limo_v2_dabai_sensor_FIELD_ID/log build \
  --base-paths '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws/src' \
  --packages-select limo_cleanup_dabai_sensor \
  --build-base /tmp/limo_v2_dabai_sensor_FIELD_ID/build \
  --install-base /tmp/limo_v2_dabai_sensor_FIELD_ID/install \
  --executor sequential --event-handlers console_cohesion+
colcon --log-base /tmp/limo_v2_dabai_sensor_FIELD_ID/test-log test \
  --packages-select limo_cleanup_dabai_sensor \
  --build-base /tmp/limo_v2_dabai_sensor_FIELD_ID/build \
  --install-base /tmp/limo_v2_dabai_sensor_FIELD_ID/install \
  --executor sequential --event-handlers console_cohesion+
colcon test-result \
  --test-result-base /tmp/limo_v2_dabai_sensor_FIELD_ID/build --verbose
```

Expected source-contract denominator is 8/8. This separate PASS would still
not authorize camera start and cannot be substituted for the current
interfaces/perception build record. Before formal readiness can become true,
the sensor package source/install hashes must also be bound into field hardware
evidence. The current draft readiness schema does not yet consume that separate
artifact, so this remains an explicit delivery blocker.

The build record uses schema version 2. With `W` replaced by the resolved
workspace path and `I` by the new isolation directory, its command section is
the following exact argv contract (JSON arrays, not shell command strings):

```json
{
  "schema_version": 2,
  "workspace_root": "W",
  "isolation_root": "I",
  "cwd": "W",
  "commands": {
    "build_argv": ["colcon", "--log-base", "I/log", "build", "--base-paths", "W/src", "--packages-select", "limo_cleanup_interfaces", "limo_cleanup_perception", "--build-base", "I/build", "--install-base", "I/install", "--executor", "sequential", "--event-handlers", "console_cohesion+"],
    "test_argv": ["colcon", "--log-base", "I/test-log", "test", "--packages-select", "limo_cleanup_interfaces", "limo_cleanup_perception", "--build-base", "I/build", "--install-base", "I/install", "--executor", "sequential", "--event-handlers", "console_cohesion+"],
    "test_result_argv": ["colcon", "test-result", "--test-result-base", "I/build", "--verbose"]
  }
}
```

The same record must contain `result: "PASS"`, all three zero exit codes,
zero test failures, `nodes_started: false`, exact platform and release fields,
three distinct non-empty hashed logs, the source-manifest artifact identity,
and an exact copy of its `required_source_names`, `entries`, and
`source_set_sha256`. Substituting a different workspace, isolation root,
manifest wrapper, or source set is rejected.

Before build/runtime evidence, freeze the exact source set into a new file:

```bash
python3 scripts/generate_perception_source_manifest.py \
  --workspace '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws' \
  --release-id FIELD_ID-source-SHA \
  --generated-at-unix-sec EPOCH_SECONDS \
  --output /approved/evidence/FIELD_ID/source_manifest.json
```

The output path is exclusive. Do not edit or regenerate it in place; a source
change requires a new release ID, manifest, build, runtime proof, and field
bundle.
The manifest recursively binds every regular build, test and install input in
`limo_cleanup_interfaces` and `limo_cleanup_perception`. Confirm that it uses
the complete generated `required_source_names`, including
`perception:limo_cleanup_perception/typed_raw_binding.py` and
`perception:limo_cleanup_perception/evidence_binding.py`; a hand-maintained
short list or an older manifest is stale and must not be reused.
Build success does not prove that Torch, Ultralytics, either model, or the
camera driver can run; record those separately in the software and hardware
evidence.

Generate the runtime/model artifact in the same fixed Foxy/Python environment.
This loads both YOLO files and verifies their exact single-class names; it does
not start ROS or a camera:

```bash
python3 scripts/perception_release_preflight.py \
  --project-root '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws' \
  --release-dir /path/to/the_matching_controlled_release \
  --models-dir '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws/models' \
  --release-id FIELD_ID-source-SHA \
  --source-manifest /approved/evidence/FIELD_ID/source_manifest.json \
  --require-runtime \
  --report /approved/evidence/FIELD_ID/runtime_preflight.json
```

The runtime-preflight report path is exclusive. It refuses an existing file;
never overwrite or silently refresh evidence from a previous source release.

The controlled release directory must correspond to the source manifest being
validated. If it is an older release, its PASS cannot prove current source;
the current-source hashes and isolated non-symlink build remain separate,
mandatory readiness inputs.

## 2. Read-only graph safety and four-stream capture

Camera reading is allowed only under the task's read-only authorization. A
camera-only authorization must not be used to enumerate or inspect UART/tty,
base, navigation, arm, gripper, actuator-owner, or control-graph paths. Before
starting the camera owner or detector, require a separate operator attestation
that any complete robot bringup/control chain was stopped, and statically
verify that the exact frozen camera launch source and argv contain only the
camera/TF sensor chain. The hardware readiness report must contain PASS results
for all four streams, aligned grids and frames, valid intrinsics, depth units,
measured `base_link -> camera_color_optical_frame`, independently validated
extrinsics, and the static isolation evidence. A report that says the TF
requirement was disabled is not acceptable.

Remote metadata inspection is restricted by the installed
`dabai_camera_query_allowlist.json`. Its exact argv arrays are the complete
allowlist: one pre-identified DaBai persistent link per invocation, using only
non-recursive `readlink`, `stat`, or `udevadm info`. Do not use `find -L`,
recursive sysfs traversal, global udev/USB/process enumeration, shell variable
substitution, globs, or combined remote commands. Freeze and source-review the
allowlist before execution; an unexpected path, extra record, empty output, or
non-camera property is FAIL and ends remote inspection.

The frozen remote argv are exactly the following. Run at most one row per SSH
invocation and only after reviewing the installed allowlist hash; this block is
policy text, not permission to execute it:

```text
readlink -f -- /dev/dabai
stat --dereference --format=%F,%a,%U,%G,%n -- /dev/dabai
udevadm info --query=property --name=/dev/dabai
readlink -f -- /dev/dc1_rgb
stat --dereference --format=%F,%a,%U,%G,%n -- /dev/dc1_rgb
udevadm info --query=property --name=/dev/dc1_rgb
readlink -f -- /dev/dabai_dc1_
stat --dereference --format=%F,%a,%U,%G,%n -- /dev/dabai_dc1_
udevadm info --query=property --name=/dev/dabai_dc1_
```

The current task contains an explicit bounded camera-read authorization, but
its fail-closed preflight has not passed. Therefore no camera, ROS graph,
recorder, detector, collector, or hardware checker has started. Authorization
alone never waives a failed launch/dependency/TF/build precondition and never
covers a control publisher, navigation goal, actuator connection, or motion
consumer.

### 2.1 Frozen camera-only startup candidate

The existing `limo_cleanup_bringup/dabai_camera.launch.py` and the historical
`limo_cleanup_hardware/sensors_readonly.launch.py` are forbidden for this
capture. The former belongs to a package with base/executor dependencies and
allows its vendor package/file to be replaced; the latter mixes non-camera
dependencies and publishes an unverified hard-coded base transform.

The sole proposed entry is the dedicated launch-only package:

```bash
ros2 launch limo_cleanup_dabai_sensor \
  dabai_cc1wc520183_sensor_only.launch.py
```

It accepts no launch arguments, checks the installed vendor
`orbbec_camera/launch/dabai.launch.py` SHA-256 against
`955c98ac653182241a26ae3b4cc4eba3937d1529cd60c0361b23d05f2e4e7aaf`
before returning a camera action, fixes serial `CC1WC520183`, RGB
`640x480@30`, raw depth `640x400@30`, registration/depth scale/frame sync on,
IR/point clouds/LDP off, TF publication on at `10 Hz`, and forces local ROS 2
domain `137`. Its package runtime dependencies are exactly
`ament_index_python`, `launch`, and `orbbec_camera`; it contains no `Node`,
process, detector, base, navigation, arm, gripper, action, service, UART/tty,
or measured-base-TF surface.

This source-level candidate is not installed or target-built yet and is not a
current start command. A positive TF rate is expected to provide `/tf`, but a
short sample must prove whether the vendor also provides a valid `/tf_static`.
The package deliberately does not publish `base_link -> camera_link`; without
an independently measured and separately audited owner, formal readiness must
remain false. Do not add a dummy/static transform merely to satisfy the six
topic manifest.

Use a unique evidence directory for every field session. Collect four
independently arranged scenes, never by relabeling one capture:

- `background`: no bottle and no trash bin.
- `bin_only`: trash bin, no bottle.
- `bottle_in_bin`: bottle visibly inside the bin opening region.
- `bottle_outside`: actionable bottle outside the bin, with the bin visible.

For each scene, collect at least 30 unique complete typed frames. The collector
subscribes only to `/cleanup/perception/frames`, creates no publisher, writes
new files exclusively, and fails unless the configured frame target is fully
met without duplicates, serialization errors, or interruption:

```bash
ros2 run limo_cleanup_perception perception_frame_collector \
  --scene background \
  --task-id read-only-perception \
  --output /approved/evidence/FIELD_ID/background.frames.jsonl \
  --manifest /approved/evidence/FIELD_ID/background.collector.json \
  --max-frames 120 --duration-sec 120
```

Repeat with new paths for the other three scenes. Also preserve a per-scene
raw rosbag2 capture. A hand-written JSON summary or copied `metadata.yaml` is
**metadata-only evidence and is not acceptable**: it does not prove that any
sensor payload was recorded, that `/tf` and `/tf_static` were present, or that
a control topic was absent.

The raw input supported by the first readiness implementation is one
uncompressed rosbag2 SQLite `.db3` file per scene. Record exactly the four
configured RGB-D topics plus `/tf` and `/tf_static`; do not record the whole
graph. The four stream types must be `sensor_msgs/msg/Image`,
`sensor_msgs/msg/Image`, `sensor_msgs/msg/CameraInfo`, and
`sensor_msgs/msg/CameraInfo`; both TF topics must be
`tf2_msgs/msg/TFMessage`. The recorded topic table must contain no base,
navigation, arm, gripper, trajectory, action-goal, or other command topic. In
particular, reject `/cmd_vel`, `/cleanup/base/safe_cmd_vel`,
`/navigate_to_pose`, `/arm_controller/joint_trajectory`, and
`/gripper_controller/commands`.

Raw capture is a separate, on-site read-only operation. It may start only after
the camera/graph authorization and both no-actuation checks described above.
The following is a command template, not authorization to start a camera or a
ROS node. Use an exact new output URI for every scene; rosbag2 must refuse an
existing path:

```bash
set -euo pipefail
umask 077
FIELD_ROOT=/approved/evidence/FIELD_ID
SCENE=background
CAPTURE_ID=FIELD_ID-background-001
BAG_URI="$FIELD_ROOT/$CAPTURE_ID"
test ! -e "$BAG_URI"
mkdir -p "$FIELD_ROOT"
ros2 bag record --storage sqlite3 --output "$BAG_URI" \
  /camera/color/image_raw \
  /camera/depth/image_raw \
  /camera/color/camera_info \
  /camera/depth/camera_info \
  /tf /tf_static
```

Stop recording with SIGINT after at least 30 complete four-stream samples.
Record the operator, independently arranged scene, `CAPTURE_ID`, start/end
Unix time, and exact topic arguments at capture time. Do not rename one bag or
reuse one `CAPTURE_ID` for another scene. Preserve and hash both
`metadata.yaml` and the `.db3`; neither file may be edited after capture.

After the environment is usable, index each stopped bag offline. This command
opens the `.db3` read-only, starts no ROS node or camera, publishes nothing,
and creates the JSON output exclusively. Run it only from a current isolated
install in which the `rgbd_bag_indexer` console entry and its tests have passed;
the presently blocked Windows/WSL environment is not evidence of that PASS.
The output path must not exist:

```bash
test ! -e "$FIELD_ROOT/$CAPTURE_ID.rgbd-index.json"
ros2 run limo_cleanup_perception rgbd_bag_indexer \
  --bag "$BAG_DB3" \
  --capture-id "$CAPTURE_ID" \
  --scene "$SCENE" \
  --rgb-topic /camera/color/image_raw \
  --aligned-depth-topic /camera/depth/image_raw \
  --rgb-camera-info-topic /camera/color/camera_info \
  --depth-camera-info-topic /camera/depth/camera_info \
  --expected-topic-manifest \
    /current/install/limo_cleanup_perception/share/limo_cleanup_perception/fixtures/rgbd_expected_topics.json \
  --output "$FIELD_ROOT/$CAPTURE_ID.rgbd-index.json"
```

Set `BAG_DB3` to the actual `.db3` file emitted by rosbag2 instead of assuming
a `${CAPTURE_ID}_0.db3` name; verify it is the only storage file for this first-version
workflow. Repeat capture and indexing independently for `bin_only`,
`bottle_in_bin`, and `bottle_outside`, using unique paths and IDs.

The index must bind `capture_id` and scene to the arrangement; enumerate the
complete topic set, exact ROS type, serialization format, message count and
first/last record time; preserve and parse the rosbag topic-table offered-QoS
evidence (including transient-local `/tf_static`); and demonstrate that no
forbidden or unexpected topic exists. It strictly decodes every Image,
CameraInfo and TFMessage CDR payload, takes synchronization only from decoded
ROS Header stamps (never the rosbag record timestamp), binds frame, resolution,
encoding and intrinsics to the separate RGB-D report, and recomputes a
monotonic one-to-one bundle index. Collector-native typed rows intentionally
contain only the public `PerceptionFrame` contract. After both files stop, run
the offline `typed_raw_binding` command with the typed JSONL, collector
manifest, raw DB3/index, capture window, release/source-set and model hashes.
The collector manifest is exact-schema evidence: it must state
`read_only=true`, `authorizes_motion=false`,
`publishes_ros_messages=false`, the one typed-frame subscription topic/type,
the complete bounded-run counts, and the frozen five-topic control deny-list;
missing or extra publisher/control/motion fields are rejected.

For example, after filling the capture times and hashes from the stopped
artifacts (the output path must not exist):

```bash
ros2 run limo_cleanup_perception typed_raw_binding \
  --typed-frames "$FIELD_ROOT/$SCENE.frames.jsonl" \
  --collector-manifest "$FIELD_ROOT/$SCENE.collector.json" \
  --raw-bag "$BAG_DB3" \
  --raw-inspection "$FIELD_ROOT/$CAPTURE_ID.rgbd-index.json" \
  --scene "$SCENE" --capture-id "$CAPTURE_ID" \
  --task-id read-only-perception \
  --started-unix-sec CAPTURE_START --ended-unix-sec CAPTURE_END \
  --release-id FIELD_ID-source-SHA \
  --source-set-sha256 SOURCE_SET_SHA256 \
  --bottle-model-sha256 BOTTLE_MODEL_SHA256 \
  --trash-bin-model-sha256 TRASH_BIN_MODEL_SHA256 \
  --output "$FIELD_ROOT/$CAPTURE_ID.typed-raw-binding.json"
```

Its exclusive JSON output binds the unique RGB-Header-stamp intersection of
typed rows and raw bundles to the raw bundle index, four message IDs, payload
sizes/SHA-256, record timestamps, and per-bundle TF sample-set SHA. Both typed
and raw denominators, unmatched counts and rates are retained; the formal
ground-truth scoring set requires every evaluated typed frame to have this raw
binding. Readiness reopens it so stamp-only or same-stamp cross-bag
substitution cannot pass. The decoded `/tf` and `/tf_static` payloads
must form a camera-frame-to-`base_link` chain. Any RGB candidate rejection
rate or per-stream/typed-to-raw unpaired rate above 5%, a zero denominator, or
counts that do not close exactly is fail-closed; 5% is accepted and any value
strictly above it is rejected. Missing raw `.db3`, missing/empty QoS evidence,
topic/type/count/time disagreement, reused capture identity, any additional
topic, or any control topic is a fail-closed result.

The expected-topic manifest is an installed, hashed policy artifact. CLI topic
arguments cannot redefine it: all four names must exactly equal the manifest,
and the bag must contain that exact six-topic set. QoS parsing is strict:
unknown or duplicated keys, invalid history/depth/duration, empty values,
incompatible reliability/durability, and a non-transient `/tf_static` are
rejected. Liveliness is strictly parsed and must match the frozen per-stream
`AUTOMATIC` policy.
For the current frozen artifact the manifest ID is
`limo-dabai-rgbd-six-topics-v1`; take it by parsing the installed
`rgbd_expected_topics.json`, and bind its actual size and SHA-256. Do not type
an alias or copy an ID from an old template/report.
Header and TF frame IDs with leading `/`, whitespace/control characters,
empty segments, `.` or `..` segments are invalid; depth row steps must align
to the encoding's element size. Dynamic
TF is selected at every accepted RGB Header timestamp using the newest sample
at or before that stamp; every bundle requires one unambiguous `base_link` to
camera chain within the configured maximum TF age. Conflicting parents,
same-stamp conflicts, changing paths, missing coverage, and changing camera
extrinsics fail closed.
For each non-static message, the rosbag receive timestamp must be at or after
its decoded Header stamp and no more than 0.75 s later; record timestamps are
strictly increasing per topic. Constant, reversed, future-before-header, or
large-skew receive times are rejected even when every Header stamp looks valid.

Field/hardware evidence and scene captures must be no older than 24 hours when
the readiness gate is run. Runtime preflight and isolated build/test proof must
be no older than 30 days. Every `ros_build_validation` record must include a
finite `generated_at_unix_sec`; WSL `E_ACCESSDENIED` is an environment block,
not a source build failure and not a PASS.

## 3. Independent annotation and measurement

For every evaluated `sequence + stamp`, create a schema-v2 exhaustive
ground-truth row reviewed by a second person. It must label every bottle and
trash-bin instance, positive-area bbox, and bottle-in-bin relationship. Give
every instance a stable ID. Scene names are not ground truth. Every row also
contains `raw_rgb` with the exact bundle index, RGB message ID/Header stamp,
lowercase payload SHA-256 and serialized size from the re-indexed DB3. The
mapping is one-to-one; a missing row, reused bundle, same-stamp record from a
different bag, unknown key or mismatched payload identity fails closed.

For every matched target instance, bind target ROI depth quality and metric XYZ
truth to the same sequence, stamp, instance ID, class, and prediction
observation ID. XYZ truth is in metres in `base_link`; record the measurement
method. Both p95 and maximum XYZ error must be at most 0.02 m. Independently
measure the camera mount, record its owner/reference hash/time, and keep TF
tolerances at or below 0.02 m translation and 0.05 rad rotation.
The per-scene schema-v2 depth-quality artifact includes one
`known_distance_samples` row for every scored frame (including `background`,
where there is no detector target). Each row binds a unique reference ID,
measurement method/reference hash, sequence/stamp, integer in-bounds ROI and
the exact aligned-depth bundle/message/Header/payload identity. That hash must
identify a separate per-scene `depth_measurement_reference` JSON artifact,
not the depth-quality file or a free-form note. Its independently measured and
reviewed sample table contains the same unique reference ID, sequence/stamp,
method and expected distance for every raw frame, plus scene/capture/window and
the complete capture provenance. Readiness reopens this artifact and requires
one-to-one equality, so editing both `expected_depth_m` and its self-reported
error, reusing a reference from another scene/bag, or omitting samples cannot
pass. The estimator
is fixed to `median_valid_depth_in_roi`. Readiness opens the DB3 read-only,
strictly decodes the actual 16UC1/mono16/32FC1 pixels including stride and
endianness, and recomputes valid count/ratio, median depth and absolute error;
self-reported good measurements cannot substitute for the pixels. All samples
must close against the ground-truth/raw frame denominator, and both p95 and
maximum absolute error must be at most 0.02 m.

The fixed quantitative gates are: expected-class recall at least 0.90;
absent-class false-positive rate at most 0.01; scene-level expected-target 3D
valid rate at least 0.80 (each detector target uses the configured ROI minimum
0.02); outside actionable recall at least 0.90; in-bin actionable leak exactly
0; outside wrong suppression exactly 0; RGB-D rejection at most 0.05; sync p95
at most 0.15 s; processing p95 at most 0.50 s; consumer end-to-end p95 at most
0.75 s. Instance matching requires same sequence/stamp/class and bbox IoU at
least 0.50; bottle and trash-bin instance precision, recall, and F1 must each
be at least 0.90.

Latency evidence is valid only with `use_sim_time=false`, sensor header stamps
and `CLOCK_REALTIME`/Unix receipt time proven to share a clock domain, and NTP
or chrony synchronization status recorded. A mere `clock_domain` string is not
a substitute for this field proof.

## 4. One-command fail-closed acceptance

Create one evidence bundle manifest using paths relative to the manifest where
possible. Every artifact declaration contains `path`, `size_bytes`, and
lowercase SHA-256. It binds:

The top-level `release_binding` gives one release ID, the source-manifest file
SHA-256, the separately recomputed canonical source-set SHA-256, and its
generation time. Runtime and build reports carry the same ID/hashes, are
generated after that manifest and before field capture, and
bind the same two model hashes. Build logs are real hashed artifacts, not
self-reported strings. The build source manifest lists every required
interfaces/perception source with path, size and SHA-256; readiness reopens the
files and recomputes the canonical hash. Exact isolated colcon argv arrays are
checked, and runtime includes a passing `source_hashes_match` check.

Start from the installed fail-closed template
`share/limo_cleanup_perception/fixtures/perception_readiness_bundle_template.json`;
copy it to a new evidence path and replace every `FILL`, null, and empty
arrangement. The untouched template is intentionally guaranteed to fail.

The current v5 missing-evidence report has 37 failures because the empty
bundle reaches top-level release/software/build/hardware/scene/extrinsics and
evaluator gates. A missing scene is deliberately short-circuited; therefore
those 37 strings are not an exhaustive list of the gates inside a present
scene. Use the 37/37 mapping in
`evidence/PERCEPTION_V2_V5_GAP_CROSSWALK.json` and supply every scene artifact
listed below. For each of the four independently captured scenes, all of these
are mandatory:

- at least 30 unique typed frames and a completed collector manifest;
- the exact six-topic raw SQLite DB3, strict offline inspection, and
  typed/raw binding;
- exhaustive bottle and trash-bin ground truth bound to raw RGB payloads;
- decoded `/tf` and `/tf_static` evidence forming the camera-to-`base_link`
  chain, plus independently measured extrinsics;
- instance-bound XYZ truth, raw depth pixels, depth-quality evidence, and a
  separately reviewed depth-measurement reference;
- synchronized processing/transport latency evidence in a proven clock
  domain; and
- one immutable capture/release/source/model/TF/truth time-window and hash
  binding across all of the above.

Truth, raw TF, XYZ, depth, latency, current runtime proof, isolated build/test
proof, or hardware/no-actuation proof missing from any required location is a
delivery-blocking failure even when it was hidden by the missing-scene
short-circuit in v5.

- both model files and the exact evaluation/runtime source files;
- isolated non-symlink interfaces+perception build/test proof;
- hardware four-stream/TF/no-actuation readiness proof;
- four independent arrangements, frames, collector manifests, raw SQLite
  rosbag2 files and their offline indexes, synchronized RGB-D reports,
  exhaustive truth, TF, independently reviewed depth-measurement reference,
  depth-quality, XYZ, and system-time latency evidence.

Every capture-derived artifact contains the complete immutable
`capture_provenance`: capture binding/ID, scene/task, capture window, release,
source/model hashes, raw DB3/index hashes and frozen topic-manifest identity.
Every scene declaration also contains `evidence_binding`, which repeats that
identity and binds the current path/size/SHA-256 of frames, collector,
typed/raw binding, RGB-D, truth, TF, XYZ and depth artifacts as one evidence
set. This prevents combining independently valid files from different bags or
time windows. Declare every raw/index artifact with its actual path, size, and
lowercase SHA-256. A metadata-only bundle is intentionally incomplete and must
never produce `delivery_ready=true`.

Run only after all files are complete; the report path must not exist:

```bash
ros2 run limo_cleanup_perception perception_readiness \
  --bundle /approved/evidence/FIELD_ID/readiness_bundle.json \
  --report /approved/evidence/FIELD_ID/readiness_report.json
```

Exit 0 and `delivery_ready=true` require every gate to pass. Missing or altered
files, fewer than 30 unique frames, duplicate identity, incomplete truth,
missing trash-bin labels, invalid depth, loose/unvalidated TF, XYZ error,
missing latency, unverified build, or unproven no-actuation state all exit 1.
The command only reads evidence and writes its report; it imports no ROS client
library and publishes no message.

The intake schema and empty intake template installed with the perception
fixtures are the machine-readable field-session starting point. Validate the
filled intake before capture and never reuse an evidence path. A successful
intake validation is only format/precondition evidence; it is not camera
authorization and cannot set `delivery_ready=true`.

## 5. Deferred environment-only verification

Do not retry the blocked WSL entry in this handoff. Once a usable Foxy
environment is explicitly restored, run the isolated build above and then
record the environment-owned checks without starting a ROS graph or camera:

```bash
source /opt/ros/foxy/setup.bash
source /tmp/limo_v2_colcon_FIELD_ID/install/setup.bash
python3 -m pytest -q \
  src/limo_cleanup_perception/test/test_detection_gate.py
python3 -m pytest -q \
  src/limo_cleanup_perception/test/test_flake8.py
python3 -m pytest -q \
  src/limo_cleanup_perception/test/test_pep257.py
python3 -m pytest -q \
  src/limo_cleanup_perception/test/test_copyright.py
```

Expected detection-gate result is 14 passed. Expected ament result is one
flake8 pass, one pydocstyle pass, and the currently declared copyright test
reported as one skip; do not relabel that skip as a PASS. These expectations
remain pending until reproduced in the restored target environment.
