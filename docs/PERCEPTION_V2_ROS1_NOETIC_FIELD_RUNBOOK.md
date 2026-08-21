# V2 ROS1 Noetic camera-only field runbook

This is the authoritative on-robot V2 camera procedure. The robot runtime is
ROS1 Noetic. ROS2/Foxy packages, ros2 launch, ros2 run, rosbag2 DB3/CDR and
DDS QoS checks are offline migration assets only and are not field PASS
evidence.

The procedure is sensor-only. It never publishes motion or control messages,
never starts navigation, the base, an arm, a gripper or an executor, and never
queries UART/tty or actuator devices. Existing non-camera terminals and nodes
must not be stopped by this procedure.

## 1. Current observed state and timeline

- Before the user opened the camera, the older preflight record correctly said
  that this task had started neither ROS nor the camera. That is historical.
- On 2026-08-14 the user started the camera manually. The following is a
  non-authoritative historical record, not an executable procedure:

      # HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: source /opt/ros/noetic/setup.bash
      # HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: source ~/agilex_ws/devel/setup.bash
      # HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: roslaunch astra_camera dabai_u3.launch

  The only production camera-start entry is the host-owned atomic launcher in
  section 5; neither these historical lines nor the retired start script may
  be used operationally.

- In another sourced Noetic terminal the user ran rqt_image_view and selected
  /camera/color/image_raw.
- The running node is /camera/camera, observed PID 86818. This task did not
  start or stop that node.

The exact launch source is
/home/agilex/agilex_ws/src/ros_astra_camera/launch/dabai_u3.launch, SHA-256
75f9ada995ac961d0b4dddb7d86d591f57dc5392165663f4a905709a24231b2e.
The audited XML contains one node only:
pkg=astra_camera, type=astra_camera_node, name=camera inside the camera
namespace. It has no include, base, navigation, arm, gripper, action, bridge
or executor entry.

## 2. Actual camera interface

The four RGB-D publishers are uniquely /camera/camera:

| Role | Topic | ROS1 type | Live probe / diagnostic bag Header frame | Grid/encoding |
|---|---|---|---|---|
| RGB | /camera/color/image_raw | sensor_msgs/Image | camera_color_optical_frame / camera_color_optical_frame | 640x480, rgb8 |
| raw depth | /camera/depth/image_raw | sensor_msgs/Image | camera_depth_optical_frame / camera_depth_optical_frame | 640x400, 16UC1 |
| RGB intrinsics | /camera/color/camera_info | sensor_msgs/CameraInfo | camera_color_optical_frame / camera_color_optical_frame | 640x480, plumb_bob |
| depth intrinsics | /camera/depth/camera_info | sensor_msgs/CameraInfo | camera_depth_optical_frame / empty Header.frame_id (invalid) | 640x400, plumb_bob |

All four streams measured approximately 30 Hz in a bounded eight-second live
subscriber check. That live probe and the later bag payload are separate
evidence. In the bounded diagnostic bag, every fresh depth CameraInfo and the
old sample have an empty Header.frame_id. The first depth CameraInfo delivered
to the recorder was also an old latched sample. The field indexer isolated it
using the connection header, capture window and message Header time; it is not
present in any new RGB-D pair.

Current driver parameters are diagnostic raw mode:

- depth_align=false;
- color_depth_synchronization=false;
- serial_number is empty;
- enable_ir=true and enable_point_cloud=true;
- RGB 640x480 at 30 Hz, depth 640x400 at 30 Hz;
- publish_tf=true, tf_publish_rate=10.0.

Therefore /camera/depth/image_raw is raw depth, not aligned depth, and the
current live stream cannot satisfy the existing aligned-grid detector contract.

## 3. TF and shared-graph rule

The live owner probe reported /camera/camera as the /tf_static publisher. Its
/tf owner set was /camera/camera plus /limo_base_node,
/base_link_to_camera_link, /base_link_to_imu_link and
/base_link_to_laser_link. The bounded bag is different: it contains four /tf
connections owned by /camera/camera and the three legacy static transform
publishers, but no /limo_base_node connection and no /tf_static message.
Reading those exact publisher names is allowed only to classify contamination.
This procedure must not stop, call or otherwise operate any non-camera owner.

ROS1 rosbag record subscribes by topic, not by publisher. Any bag recorded from
the current shared /tf is diagnostic only. It must have all of these machine
fields:

    {
      "formal_acceptance": false,
      "shared_graph": true,
      "mixed_tf": true,
      "not_in_four_scene_denominator": true,
      "delivery_ready": false
    }

No FPS, count or detection result may override these exclusions. TF inspection
must retain topic, connection, callerid, parent and child for every transform.
It must not assume that all /tf messages are dynamic: legacy ROS1 static
transform publishers may periodically send fixed edges on /tf.

## 4. Current diagnostic sample

The bounded shared-graph sample is:

    /home/agilex/camera_evidence/v2_ros1_shared_graph_diagnostic_20260814T052442Z.bag

It is rosbag v2.0, LZ4 compressed, 2.939682 seconds, 81,634,393 bytes, and
SHA-256
31a9c280aaa8d1ce6f1836bb9a445eafd87fbc5b096967932484c2f4c6982168.
It contains RGB CameraInfo 89, RGB 88, depth CameraInfo 87, depth 86 and
/tf 898 messages over four recorded connections. /tf_static delivered no
message in the window and is absent from the stored topic set. It is therefore
not a valid six-topic bag and not a formal scene capture.

The authoritative full-field diagnostic index is:

    evidence/perception_v2_field_20260814/diagnostic_shared_graph/
      v2_ros1_shared_graph_diagnostic_20260814T052442Z.diagnostic-manifest-v3.json

It is 6,989,444 bytes with SHA-256
4683b682b908a2325232aa604a3b7e6367dd0404a84baf0013d159ab8da7e08f.
It binds the exact 88,414-byte indexer source with SHA-256
4b541369995076cbb588ec53854a8f22edec99d71a0a96629b5252f896046037,
the source bag hash above, capture ID
v2-ros1-shared-diagnostic-20260814T052442Z and frozen expected-topic manifest
SHA-256 88771fcdac6770da49dc7ed75179c1b82243ca30e63f3e88d26a04ae70b59b2b.

The v3 index decoded all 1,248 ROS1 serialized payload records and their
connection headers rather than trusting rosbag info. Its field-level findings
are:

- 88 RGB candidates produced 86 unique Header-bound diagnostic pairs;
- there are zero formal-contract-valid pairs; the reported 86 accepted
  bundles are diagnostic timestamp pairings only and are not formal evidence;
- one old latched depth CameraInfo was isolated and is absent from every pair;
- 5 of 349 four-stream messages are unpaired, or 1.4327%: two RGB images and
  three RGB CameraInfo messages;
- both CameraInfo connections are latched even though the frozen formal topic
  manifest requires non-latched CameraInfo;
- all fresh depth CameraInfo payloads have an empty Header.frame_id, so every
  diagnostic pair carries the frame mismatch rejection;
- CameraInfo width, height, distortion model and K/D/R/P calibration payloads
  are stable within each stream, but that does not repair the invalid frame;
- the index contains 1,043 transforms across nine edge summaries: /tf
  contributes 898 messages over four connections and /tf_static contributes
  zero;
- the bag preserves topic, connection, callerid, parent and child for every
  transform, including /base_link to /laser_link published on /tf by
  /base_link_to_laser_link.

The machine policy remains formal_acceptance=false, shared_graph=true,
mixed_tf=true, not_in_four_scene_denominator=true and delivery_ready=false.
No count, frame rate, pairing rate or detection result may override it.

The adjacent `formal-gate-v3.json` is only a historical strict first-failure
probe. It stopped at `connection_latching_mismatch`, did not complete the
full-field diagnostic traversal, and must not be used as TF, pairing or scene
evidence. rosbag info alone is likewise never acceptance evidence.

## 5. Future isolated aligned capture

Do not change the currently running camera while parallel user tests depend on
it. At a later camera-only window, only the camera terminal may be restarted;
other terminals and non-camera nodes remain untouched. Use a separate ROS1
master and the audited launch with these fixed camera arguments:

Before sourcing ROS or starting that isolated master, run the inert host-owned
static preflight from the audited workspace:

    readonly ACTUAL_VENDOR_LAUNCH=/opt/limo/ros1_camera_runtime/share/astra_camera/launch/dabai_u3.launch
    python3 -I -B audit_tools/ros1_camera_only_field_preflight.py \
      --actual-vendor-launch "$ACTUAL_VENDOR_LAUNCH"

It emits exactly one `ROS1_CAMERA_ONLY_FIELD_PREFLIGHT ` JSON marker. The tool
only reopens the frozen authority-v4 predecessor, canonical-v5/report-v4
references, the archived 6,446-byte DaBai reference, the exact live absolute
vendor launch named above, the formal detector launch and local
Noetic/catkin/CMake/Python files. The archive is reference-only: the live file
must independently have the same 6,446 bytes and SHA-256, pass the complete
camera-only XML policy, have no symlink/reparse/linklike parent or target, and
retain the same path/inode/size/mtime/hash through the post-policy reread. It
does not source ROS, execute those tools, start a graph, open the camera or run
inference. A missing
`/opt/ros/noetic/setup.bash` or catkin tool is an environment blocker, not a
source build failure. Even a passing static preflight has
`formal_consumer=false` and `delivery_ready=false`.

Never replace this with `roslaunch astra_camera dabai_u3.launch`, direct
`roslaunch "$ACTUAL_VENDOR_LAUNCH"`, or any other ROS_PACKAGE_PATH/package-name
lookup. The static preflight intentionally returns before execution, so a path
could otherwise be replaced in that interval. The only production transition
to a future camera-only launch is the host-owned atomic launcher:

The exact command role below is a future production interface, not a current
authorization to execute. The launcher presently fails closed with
`camera_runtime_install_admission_not_bound` until a new source generation
binds host-validated Noetic install evidence, the roslaunch Python closure,
the exact Astra package/node resolution and a clean non-ambient exec
environment. Do not run it in the current generation.

    python3 -I -S -B audit_tools/ros1_camera_only_atomic_launcher.py \
      --mode EXECUTE_AUDITED_CAMERA_ONLY \
      --actual-vendor-launch "$ACTUAL_VENDOR_LAUNCH"

That launcher repeats the full static preflight, opens the exact absolute live
file with `O_NOFOLLOW`, rechecks its parent chain and file identity, copies the
validated 6,446 bytes into a Linux memfd, and applies
`F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL`. Immediately before exec
it rechecks the live path/parents/open descriptor and the sealed object. The
fixed `/opt/ros/noetic/bin/roslaunch` is itself opened with `O_NOFOLLOW` and
matched to path/size/SHA material obtained only from the independently
validated host-owned Noetic runtime-install admission. The caller cannot
supply or override that identity. A future admitted generation will execute only after the same
root-owned, non-linklike, non-group/world-writable file and complete parent
chain are re-opened and re-hashed immediately before descriptor-bound exec. Its argv receives only
`/proc/self/fd/<sealed-fd>` plus the audited camera-only overrides
(`camera_name=camera`, serial `CC1WC520183`, aligned/synchronized depth, IR and
both point-cloud modes disabled, TF enabled at 10 Hz). The CLI accepts no
caller-supplied roslaunch arguments. The original live pathname is never an
exec argument, so a rename, symlink swap or in-place rewrite cannot select the
executed vendor-launch bytes. Production roslaunch execution remains blocked
in this generation as stated above.

Before recording, re-check only /camera/camera and the exact six topics. Both
TF topic publisher sets must be exactly {/camera/camera} in that isolated
master. /tf_static must actually deliver a latched message. If either check
fails, stop only the isolated camera session and keep readiness false.

Formal capture uses the new immutable manifest generation
`dabai_ros1_formal_four_scene_six_topics_v1.json`, SHA-256
`46b135e8aaacce4dc1d552078ff5236299a68efc90ada47420cb6e30ea7fb5f4`.
The older `dabai_ros1_raw_rgbd_six_topics_v1.json` remains frozen for the
historical short-sample/diagnostic path and cannot authorize a formal scene.
The formal generation permits the DaBai driver's latched CameraInfo
connections, but every old pre-window latched sample must be quarantined in a
hash-bound isolation ledger and must not enter an RGB-D bundle.

Record with an absent absolute path and exact topic argv; never use -a, a
regex, a bridge or rosbag play:

    rosbag record --lz4 -O /approved/new/CAPTURE_ID.bag \
      /camera/color/image_raw \
      /camera/depth/image_raw \
      /camera/color/camera_info \
      /camera/depth/camera_info \
      /tf /tf_static \
      __name:=camera_only_recorder

Stop the recorder with SIGINT, require the .active file to disappear, then hash
the closed bag. On-site ROS2 middleware and ros1_bridge are forbidden.
Normalize and infer offline from the stopped ROS1 bag.

Index each closed scene bag offline with the formal mode and a new output path:

    rosrun limo_cleanup_ros1_perception rosbag1_rgbd_indexer.py \
      --bag /approved/new/CAPTURE_ID.bag \
      --capture-id CAPTURE_ID \
      --scene background \
      --mode formal_camera_only \
      --manifest "$(rospack find limo_cleanup_ros1_perception)/config/dabai_ros1_formal_four_scene_six_topics_v1.json" \
      --output /approved/new/CAPTURE_ID.formal-index.json

Replace `background` with exactly one of `background`, `bin_only`,
`bottle_in_bin` or `bottle_outside`. Formal admission additionally requires
all four RGB/depth/CameraInfo streams to share one frame and one pixel grid;
the current 640x480 color versus 640x400 raw-depth stream therefore remains a
formal failure even if its FPS and timestamp pairing look healthy.

## 6. Typed evidence and final-admission status

The closed bag and formal index are necessary but are not sufficient. A
formal scene also needs typed perception frames and a typed/raw binding. The
formal source generation has a separate read-only detector launch whose task
and capture identities have no defaults. After a real isolated Noetic
build/install has independently passed, start it with the same immutable IDs
used by the recorder, indexer and collector:

    export TASK_ID="v2-formal-four-scene-YYYYMMDD"
    export CAPTURE_ID="v2-SCENE-YYYYMMDDTHHMMSSZ"
    roslaunch limo_cleanup_ros1_perception perception_v2_formal_capture.launch \
      task_id:="$TASK_ID" \
      capture_id:="$CAPTURE_ID"

The launch contains only the dual-model read-only perception node. It has no
camera bringup, include, remap, environment substitution, navigation, control,
arm, gripper, Twist or goal surface. Never substitute the older
`perception_v2_readonly.launch` for a formal capture: that diagnostic entry has
no caller-bound task/capture identity.

The installed ROS1 collector entry is read-only and uses exclusive output
paths. Run it with the same `TASK_ID`, scene and capture-specific output paths:

    rosrun limo_cleanup_ros1_perception perception_frame_collector.py \
      --scene SCENE \
      --task-id "$TASK_ID" \
      --output "/approved/new/$CAPTURE_ID.frames.jsonl" \
      --manifest "/approved/new/$CAPTURE_ID.collector.json" \
      --max-frames 120 \
      --duration-sec 120

The formal launch closes the source-level identity route only. Until its exact
source generation has a real Noetic build/install result and the detector,
collector, stopped bag and index all recompute the same scene/capture/task
join, these outputs remain non-admitted material and contribute zero formal
frames.

After the independent build/install and identity gates are closed, bind the
stopped bag, formal index, collector manifest and typed JSONL offline with the
exact ROS1 interface:

    rosrun limo_cleanup_ros1_perception typed_raw_binding.py \
      --index /approved/new/CAPTURE_ID.formal-index.json \
      --frames /approved/new/CAPTURE_ID.frames.jsonl \
      --collector-manifest /approved/new/CAPTURE_ID.collector.json \
      --raw-bag /approved/new/CAPTURE_ID.bag \
      --workspace-root /approved/audited/workspace \
      --source-admission /approved/new/ROS1_SOURCE_ADMISSION.json \
      --topic-manifest /approved/new/dabai_ros1_formal_four_scene_six_topics_v1.json \
      --model-manifest /approved/new/model_bindings.json \
      --model-root /approved/new/models \
      --output /approved/new/CAPTURE_ID.typed-raw-binding.json

The command must return zero and recompute the same scene, capture ID, task
ID, capture window, model/source identities and at least 30 unique
associations. Any duplicate raw bag, reused content hash, reused bundle
fingerprint, overlapping scene window, diagnostic/shared/mixed TF,
synthetic/test-only marker, zero denominator or identity mismatch is an
immediate rejection.

Ground truth, TF application, XYZ, depth and latency cannot be supplied as
handwritten summary booleans. Every scene needs hash-bound per-frame records:

- ground truth independently arranged by an operator and checked by a
  different reviewer;
- raw TF topic, connection ID, caller ID, parent/child edge and transform
  identity joined to the indexed bag, plus an independent camera-to-base
  extrinsics reference;
- independent XYZ and depth measurement-reference artifacts joined to each
  observation; and
- sensor, inference and collector timestamps from which latency is recomputed.

There is currently no audited producer CLI for those five semantic artifact
roles. Missing producer output keeps the corresponding gate false.

The overlay `perception_readiness.py --input ...` command remains a
non-authoritative material check. Its self-reported model/install result can
never authorize delivery. The host-owned ROS1/Noetic field-readiness intake is
implemented in `ros1_noetic_field_readiness.py`; it accepts only an externally
anchored request and authority, independently invokes the isolated rosbag1
probe, and reopens the per-frame semantic artifacts. From the audited host
checkout, the future production invocation is:

    python3 -I -B /approved/host/src/limo_cleanup_perception/\
      limo_cleanup_perception/ros1_noetic_field_readiness.py \
      --request /approved/new/ROS1_FIELD_REQUEST.json \
      --authority /approved/new/ROS1_FIELD_AUTHORITY.json \
      --authority-size-bytes AUTHORITY_BYTES \
      --authority-sha256 AUTHORITY_SHA256 \
      --workspace /approved/audited/workspace \
      --output /approved/new/ROS1_FIELD_READINESS.json

That path cannot read ROS2 SQLite/DB3, accept an overlay self-report or promote
a handwritten summary. The host intake is an implemented fail-closed consumer,
not evidence that the required inputs currently exist. Real Noetic
build/install evidence, four independent nonzero scene denominators, GT,
applied TF, XYZ/depth and latency samples are still missing, so final field
consumer acceptance and `delivery_ready` remain false.

The current scene set is also not interchangeable with the binary-presence
set `neither`, `bin-only`, `bottle-only`, `both`. The present contract uses
`background`, `bin_only`, `bottle_in_bin`, `bottle_outside`: it has no
bottle-only scene and splits the both-present case by relation. If the binary
four-way set is the acceptance target, create a new manifest/schema generation
and new denominator; never relabel the current four captures as equivalent.

## 7. Four-scene acceptance remains open

The formal scenes are background, bin_only, bottle_in_bin and bottle_outside.
Each needs at least 30 unique, Header-bound RGB-D observations, independent
truth, depth/XYZ, TF and latency evidence. The current diagnostic bag belongs
to none of them, so the four-scene denominator remains zero. Formal TF and 3D
remain BLOCKED. Until all four scenes, ROS1 build/runtime proof, external
camera-to-base calibration and field metrics pass, delivery_ready=false.

The current machine-readable missing-evidence evaluation is
`evidence/perception_v2_offline_20260813/
formal_readiness_missing_20260814_failclosed_v6_ros1_v3.json`, 4,495 bytes,
SHA-256 95f014b9fdaaa0d4c1cd5c5e1097bfbdc6d373c16d833c2960d04f712b157a74.
It has 37 failures and does not admit any formal scene. Its ROS1-specific gap
summary is `evidence/perception_v2_offline_20260813/
four_scene_rgbd_gap_report_failclosed_20260814_v4_ros1_v3.json`, 3,330 bytes,
SHA-256 b580f32419f239937046571fe26087507d03e82157c6bce264e9a496b73c6022.
That summary fixes every formal scene count at zero and keeps formal ROS1
admission, TF, 3D and delivery BLOCKED.
