# ROS1 Noetic V1 field runbook

Status: this runbook was prepared offline and has not itself been executed as
a sealed V1 field-acceptance protocol. Later user-reported real-machine facts
are preserved separately as `USER_OBSERVED/PARTIAL/UNSEALED`; they are not a
formal PASS and do not authorize any step below.

This runbook is evidence and a future operator procedure. It does not grant
permission to connect to the robot, start nodes, open serial devices, or move.
Every hardware or motion stage requires a fresh authorization from the main
task and an on-site person at the main switch.

## 1. Provisional ownership target

This table is a target contract, not proof of the current vendor include or
live graph. `limo_start.launch` and its installed static TF publisher remain
`BLOCKED_ON_VENDOR_INCLUDE`; the historical laser-TF node name and transport
must not be treated as an allowlist.

```text
/ydlidar_lidar_publisher -> /scan
/limo_base_node          -> /odom
/limo_base_node          -> odom -> base_link on dynamic /tf (target)
<verified vendor pin>    -> base_link -> laser_link on exactly one pinned
                            static transport (/tf periodic or /tf_static latched)
/move_base               -> /v1/nav_cmd_vel
/v1_cmd_guard            -> /v1/driver_cmd_vel
/limo_base_node          <- /v1/driver_cmd_vel
```

Forbidden:

```text
/robot_pose_ekf
any ROS2 base driver
any public /cmd_vel endpoint
keyboard/joystick publishers during navigation
vendor limo_navigation_diff.launch
vendor map fallback
```

The laser edge authority/topic is not closed until the raw recursive include
chain and installed publisher pin are archived. Missing edge evidence, a
present `/robot_pose_ekf`, a wrong parent, an alias authority, the same edge on
both `/tf` and `/tf_static`, or any extra protected-child owner is a hard
block. A tf2 lookup proves connectivity only, not edge authority or topic.

## 2. Offline-only checks

Run from the package directory:

```bash
python3 scripts/audit_v1_overlay.py
python3 scripts/validate_v1_profile.py --stage scan
python3 ../../scripts/test_ros1_v1_navigation_offline.py
```

Expected markers:

```text
V1_OVERLAY_STATIC_PASS
V1_PROFILE_STATIC_PASS
ROS1_V1_NAVIGATION_OFFLINE_TEST_PASS
```

Representative negative checks must fail:

```bash
python3 scripts/validate_v1_profile.py --stage navigation --allow-nonzero
python3 scripts/validate_v1_profile.py --stage localization \
  --map-file /vendor/path/map1017.yaml --active-map-id map1017
```

## 3. Future deployment layout

Do not copy into or edit `~/agilex_ws`. Build a separate catkin workspace:

```text
~/limo_v1_overlay_ws/
  src/
    limo_v1_navigation/
```

Future build-only commands, after deployment authorization:

```bash
source /opt/ros/noetic/setup.bash
source ~/agilex_ws/devel/setup.bash
cd ~/limo_v1_overlay_ws
catkin_make
source ~/limo_v1_overlay_ws/devel/setup.bash
rospack find limo_v1_navigation
```

Building is not hardware authorization. All launch defaults remain false.

## 4. Pre-hardware read-only audit

Before every native/current ROS1 stage:

```bash
pgrep -af 'ros|limo|ydlidar|teleop|move_base|amcl|slam_gmapping|nav2'
rosnode list
fuser -v /dev/ttyTHS0
fuser -v /dev/ydlidar
```

If a master is absent, `rosnode list` may report that it cannot communicate.
If any base driver, teleop, SLAM, navigation process, or serial owner exists,
stop the procedure without changing that process.

This native/current checklist intentionally contains no ROS 2 CLI, Foxy or
Humble setup, ROS 2 build tooling, or global ROS 2 graph enumeration. It must
never inherit an integrated-bridge command. Dynamic command positions,
command substitutions, eval/exec, and shell `-c` wrappers are also forbidden
in this native/current checklist.

### 4.1 Explicit integrated bridge exception (not a native stage)

This exception requires a fresh, independent integrated-bridge authorization
and is never inherited by a native/current ROS1 stage. Only these two existing
entry points are allowlisted:

- `scripts/ros1_base_bridge_preflight.sh`
- `scripts/run_ros1_base_bridge_zero_stage.sh`

Any separately authorized bridge diagnostic must remain inside those scripts'
existing read-only/zero-chain scope and use the exact domain and localhost
policy already enforced by those scripts. This runbook adds no alternate DDS
scope. Direct ROS 2 CLI, setup, build, or global graph commands are not
accepted in this runbook. This exception does
not expand either script's existing one-time authorization or safety gates,
and its output is not native Noetic field or delivery evidence.

## 5. First scan stage: no motion

Only after fresh hardware-start authorization:

Before using the command below, close `V1_ROS1_VENDOR_INCLUDE_BLOCKER.json`.
Required inputs include the raw recursive launch chain and the installed
static-TF publisher package/version, executable path and SHA-256, resolved
node name/callerid and arguments, parent/child frames, selected topic, and
periodic-versus-latched semantics. If any field is missing, do not start the
vendor include; remain `BLOCKED_ON_VENDOR_INCLUDE`.

The automated perception-only field orchestrator is additionally hard-blocked
with `TF_VENDOR_RUNTIME_BINDING_UNVERIFIED`. The current loader verifies paths
and bytes but does not make `roslaunch` consume an immutable sealed snapshot;
therefore authorization, precheck, and `Popen` are deliberately unreachable.
The command below remains a future template only until a reviewed runtime
binding fixes the package roots, wrapper, complete include closure, publisher
executable, launcher path, and environment to the exact verified bytes. Moving
the hash check closer to launch or repeating it is not sufficient.

```bash
roslaunch limo_v1_navigation v1_base_sensors.launch \
  enable_hardware:=true \
  hardware_authorization_id:=<ONE_TIME_AUTHORIZATION_ID> \
  odom_tf_owner:=/limo_base_node
```

This includes vendor base/sensors but forces `pub_odom_tf=true` and remaps the
driver away from public `/cmd_vel`. Do not start teleop, Gmapping, AMCL, or
move_base.

Run the read-only preflight:

```bash
roslaunch limo_v1_navigation v1_runtime_preflight.launch \
  stage:=scan samples:=30 \
  vendor_tf_rules_file:=/absolute/verified/vendor_tf_rules_v2.json \
  vendor_source_manifest_file:=/absolute/verified/vendor_source_manifest.json \
  vendor_publisher_pin_file:=/absolute/verified/vendor_publisher_pin.json
```

Required output token:

```text
V1_SCAN_ODOM_TF_PREFLIGHT_PASS
```

It requires 30 scan samples, 4.8-7.2 Hz, scan frame `laser_link`, range
0.02-16 m, `/odom` frames `odom/base_link`, both TF links, exact scan/odom
publishers, no `/robot_pose_ekf`, and no public `/cmd_vel` endpoint. It must
also emit a structured edge report built from every `TFMessage` transform:
parent, child, connection `callerid`, callback-bound topic, source stamp,
monotonic receipt time, and geometry fingerprint. For each protected child it
requires one parent, one authority, and one topic; cross-topic duplicates,
wrong edges, aliases, and unverified vendor owners block. The checker creates
subscribers only and never publishes Twist.

The three vendor artifacts are independent inputs. The installed package
blocker must already be `VERIFIED`; it pins the SHA-256 of all three. The
checker reads and rehashes all three manifests, every referenced raw launch
file, and the pinned executable bytes. It parses the archived include graph
and static-transform nodes, then requires their
callerid/edge/topic/periodic-or-latched semantics to equal the pin and rules
manifest exactly. A 64-character fake hash, `provenance_verified=true`, a
missing path, `BLOCKED` status, or any byte/semantic mismatch is
`TF_VENDOR_CONTRACT_UNVERIFIED`.

The future blocker/release approval package must also archive `rospack find`
package roots and the exact `roslaunch --files`, `roslaunch --nodes`, and
`roslaunch --dump-params` outputs for the reviewed arguments. These dumps are
release-review-only evidence: the runtime loader does not consume them, and
their presence never creates an automatic PASS. A reviewer uses them to decide
whether a new trusted blocker/release may be approved.

The runtime machine gate instead requires the trusted installed-blocker hash,
three independent manifests plus their referenced raw bytes, and a strict
supported ROS launch XML subset. It resolves every manifest package root with
`rospack find` and requires a unique `roslib.packages.find_node` executable
matching the pinned path and SHA-256. Any unmodelled include argument, remap,
namespace/condition/substitution, `launch-prefix`, ambiguous executable, or
package-path mismatch is `TF_VENDOR_CONTRACT_UNVERIFIED`. A matching path
string, package/type pair, or runtime callerid alone is insufficient.

Dynamic `map -> odom` and `odom -> base_link` evidence is `/tf`-only and uses
source plus receipt freshness. The pinned laser edge is static: legacy `/tf`
requires repeated invariant geometry with advancing stamps, while latched
`/tf_static` permits a zero or old source stamp and instead requires one
session observation, invariant repeated geometry, and a still-present graph
owner. The PASS token without this structured edge decision and its vendor-pin
binding is not ownership evidence.

## 6. Mapping stage

Mapping still requires a separate motion authorization because it ultimately
needs one low-speed operator input. The package intentionally does not include
teleop.

After the scan preflight token:

```bash
roslaunch limo_v1_navigation v1_mapping.launch \
  enable_mapping:=true \
  preflight_token:=V1_SCAN_ODOM_TF_PREFLIGHT_PASS \
  enable_rviz:=true
```

Project Gmapping explicitly uses `map/odom/base_link`, `/scan`, 0.05 m cells,
and more frequent conservative updates. Only after the separate motion grant
may the already field-proven single teleop be started. No navigation process
may coexist with Gmapping.

Save while Gmapping is still active:

```bash
V1_FIELD_AUTHORIZATION=YES rosrun limo_v1_navigation v1_map_artifact_check.sh save \
  /absolute/non_vendor/map/directory/<NEW_V1_MAP_ID>
```

Record YAML/image SHA-256. Never overwrite a vendor map.

## 7. Standalone map reload and localization

First validate files without ROS:

```bash
python3 scripts/validate_v1_profile.py \
  --stage localization \
  --map-file /absolute/path/<FROZEN_MAP_ID>.yaml \
  --active-map-id <FROZEN_MAP_ID>
```

Then use `rosrun limo_v1_navigation v1_map_artifact_check.sh reload` only in an otherwise empty
ROS1 graph. After its file-load check passes, start localization in zero-motion
mode:

```bash
roslaunch limo_v1_navigation v1_localization.launch \
  enable_localization:=true \
  preflight_token:=V1_SCAN_ODOM_TF_PREFLIGHT_PASS \
  map_file:=/absolute/path/<FROZEN_MAP_ID>.yaml \
  active_map_id:=<FROZEN_MAP_ID> \
  enable_rviz:=true
```

The map path has no default. Relative paths, vendor directories, rejected map
IDs, missing images, and map ID/stem mismatches block before launch.

## 8. Navigation zero stage

Start with nonzero disabled:

```bash
roslaunch limo_v1_navigation v1_navigation.launch \
  enable_navigation:=true \
  preflight_token:=V1_SCAN_ODOM_TF_PREFLIGHT_PASS \
  map_file:=/absolute/path/<FROZEN_MAP_ID>.yaml \
  active_map_id:=<FROZEN_MAP_ID> \
  allow_nonzero:=false \
  driver_timeout_verified:=false
```

Then run the navigation topology preflight:

```bash
roslaunch limo_v1_navigation v1_runtime_preflight.launch \
  stage:=navigation samples:=30 \
  map_file:=/absolute/path/<FROZEN_MAP_ID>.yaml \
  active_map_id:=<FROZEN_MAP_ID> \
  vendor_tf_rules_file:=/absolute/verified/vendor_tf_rules_v2.json \
  vendor_source_manifest_file:=/absolute/verified/vendor_source_manifest.json \
  vendor_publisher_pin_file:=/absolute/verified/vendor_publisher_pin.json
```

The guard remains startup-latched and publishes only zero. The gateway remains
disabled because `enable_goal_gateway` and `allow_goal_forwarding` both default
to false. No goal may be sent.

`v1_navigation.launch` includes `v1_navigation_core.launch` exactly once and
is permanently native-only. Passing `mode:=integrated` is an invalid argument
and cannot start the core. Integrated navigation is owned exclusively by the
bridge runner's private immutable-snapshot launch and is never a public V1
launch path.

## 9. Nonzero navigation gate

Nonzero remains blocked until the base/firmware independently stops after the
sole command publisher disappears. That test requires an on-site person and a
separate motion authorization. A software guard cannot prove safety after its
own process is forcibly lost.

Only after that evidence is accepted may both launch arguments be true:

```text
allow_nonzero=true
driver_timeout_verified=true
```

The guard still requires fresh scan, odom, both TF links, its graph-level
topology checks, a fresh move_base command, and an explicit rearm service call
while the requested command is zero:

```bash
rosservice call /v1_cmd_guard/rearm
```

Any stale/missing sensor, TF, command, wrong frame, wrong owner, NaN/Inf,
non-planar Twist, or speed limit violation latches zero and requires a new
explicit rearm. It never resumes an old goal automatically.

The edge-level authority/topic proof above is a bounded preflight/field
snapshot, not a continuous guard guarantee. Neither guard health nor
localization READY proves that the TF edge ownership remains unchanged after
the capture. Any observed process/graph drift invalidates the snapshot and
requires stop plus a new authorized preflight; it must not be repaired by
silently accepting a new owner.

## 10. Explicit initial pose and zero-motion READY procedure

This procedure never commands rotation. Starting sensors/ROS against the real
robot still needs the applicable read-only hardware authorization; do not run
it under the current offline-only boundary.

1. Verify `/v1/localization/ready` is false and the manager reports
   `waiting_for_explicit_initial_pose`.
2. Open exactly one short authorization window:

   ```bash
   rosservice call /v1_localization_manager/authorize_initial_pose
   ```

3. In RViz, send one `2D Pose Estimate` on public `/initialpose`. The manager
   must be its sole consumer and AMCL must consume only
   `/v1/validated_initialpose`.
4. Record manager JSON until READY. The first no-motion success may be counted
   only after a valid post-initialpose `/amcl_pose`. Ten successful
   `/request_nomotion_update` calls, fresh chain evidence, covariance limits,
   and the three-second stability window are all required.
5. A timeout, stale/invalid scan/odom/map/TF/AMCL message, covariance breach,
   service failure, or topology mismatch must keep or revoke READY. Do not add
   an automatic spin or recovery behavior.

READY proves the frozen localization convergence and chain-health conditions
only. It does not prove continuous per-edge TF authority/topic/cardinality and
does not close the vendor include blocker.

Capture per cold start: accepted-pose time, READY time, no-motion request/result
count and latency, covariance variances plus square-root standard deviations,
fixed-pose samples, and every fail-closed reason. Target `3/3` cold starts READY
within `45 s`; after READY collect at least 30 stationary samples and require
`stddev x/y <=0.05 m` and circular yaw stddev `<=5 degrees`.

## 11. Goal/cancel/status procedure (frozen until motion authorization)

The only public goal ingress is `/v1/navigation/goal`; do not use the private
move_base action or private simple-goal topic. RViz `2D Nav Goal` is not an
accepted ingress in this package. The gateway generates request IDs internally.

Even after a later movement authorization, forwarding requires all of:

```text
enable_goal_gateway=true
allow_goal_forwarding=true
fresh localization READY
fresh unlatched /v1/cmd_guard/stop_latched heartbeat
available /v1/private_move_base action server
rosservice call /v1_navigation_gateway/arm
```

Cancel remains available on `/v1/navigation/cancel` and
`/v1_navigation_gateway/cancel`. READY loss, guard stop/staleness, action loss,
or explicit cancel invalidates a pending send before cancellation, so a goal
accepted by policy cannot be sent late. Status/error JSON remains observable
while forwarding is disabled. None of these software controls replace the
physical e-stop/main switch.

For future data capture, record goal pose/time/request ID, action state changes,
cancel reason/latency, final AMCL pose, and an independently measured physical
pose. Report separately:

```text
AMCL estimation error             = ground truth final - AMCL final
navigation control endpoint error = goal - AMCL final
physical total endpoint error     = goal - ground truth final
repeat localization error         = stationary AMCL spread across repeats
```

Default offline report thresholds are respectively `0.10 m`, `0.10 m`,
`0.15 m`, and stationary `x/y stddev <=0.05 m` plus yaw stddev `<=5 degrees`.
Do not infer absolute AMCL accuracy from repeatability or covariance alone.

## 12. Conservative first-field parameters

```text
max linear speed       0.18 m/s
max angular speed      0.45 rad/s
max linear acceleration 0.35 m/s^2
max angular acceleration 0.8 rad/s^2
move_base controller   5 Hz
local costmap frame    odom
local costmap update   5 Hz
scan freshness         <0.5 s and 4.8-7.2 Hz
odom/TF freshness      <0.5 s
command lease          <0.25 s
inflation radius       0.35 m
automatic recovery     disabled
reverse escape         disabled
```

The vendor 0.6 m/s value is not accepted anywhere in the V1 overlay.

## 13. Stop order

For a future authorized navigation run:

1. cancel the current move_base goal;
2. confirm `/v1/driver_cmd_vel` remains continuously zero;
3. stop move_base/AMCL/map_server/RViz while the guard remains alive;
4. stop the base/sensor launch;
5. verify `/dev/ttyTHS0` and `/dev/ydlidar` are released;
6. stop the guard last.

Until independent driver timeout proof passes, an on-site main-switch observer
is mandatory and V1 cannot be accepted.
