# V1 perception-only field package

Status: prepared locally; robot execution `NOT_RUN`; runtime ownership remains
`PROVISIONAL/BLOCKED_ON_VENDOR_INCLUDE`.

This is the next field stage after the native-only V1 contract review. It may
start the ROS1 base and YDLidar drivers, but it never starts teleop, Gmapping,
Cartographer, map_server, AMCL, move_base, a bridge adapter, or a velocity
publisher. Expected robot motion is **none**. Opening the base UART is still a
hardware action, so it requires a fresh authorization immediately before use.

## What the user must prepare before the execution request

- An on-site operator at the robot for the whole session, with immediate
  access to the main power switch/e-stop.
- Clear floor around the robot. Prefer wheels safely lifted or use effective
  wheel chocks for this first sensing-only run; do not rely on software alone.
- Stable robot power, charged battery, YDLidar connected at `/dev/ydlidar`,
  base UART present as `/dev/ttyTHS0`, and no ROS2 base driver.
- The ROS1 vendor workspace and the separately built V1 overlay workspace.
- Three independent absolute-path artifacts: the verified recursive source
  manifest, installed static-TF publisher pin, and TF rules manifest. The
  installed blocker must be independently hash-anchored and already
  `VERIFIED`. The loader rehashes the three manifests, every referenced raw
  launch file, and the pinned executable bytes, then requires exact
  callerid/edge/topic/behavior agreement. A well-formed fake hash,
  `provenance_verified=true`, historical node name, or runtime observation
  cannot create this proof.
- The future blocker/release approval package must archive `rospack find`
  package roots and exact `roslaunch --files`, `roslaunch --nodes`, and
  `roslaunch --dump-params` outputs for the selected arguments. These are
  release-review-only evidence, not loader inputs, and never create an
  automatic PASS. The runtime machine gate separately verifies the trusted
  blocker hash, three manifests and referenced raw bytes, the strict supported
  XML subset, each live `rospack find` package root, and one unique
  `roslib.packages.find_node` executable matching the pin. Any unmodelled
  include argument, remap, namespace/condition/substitution, `launch-prefix`,
  ambiguous executable, or package-path mismatch fails closed before hardware.
- A local terminal on the robot or an already approved operator-controlled
  terminal, plus an absolute directory with space for the JSON result.
- No teleop/joystick, Gmapping, Cartographer, AMCL, move_base, map_server,
  bridge navigation, or unrelated ROS master running.
- Expected time: 10-15 minutes if all prechecks pass. A BLOCK should stop the
  session rather than extending it through live repairs.

Before execution the main task must be told explicitly:

```text
This stage opens the ROS1 base UART and YDLidar, but creates no velocity
publisher and is expected not to move the robot. It will run for about
10-15 minutes and then stop its own process group and verify both devices are
released. May this one perception-only hardware session start now?
```

No earlier general “continue” instruction counts as this one-time permission.

## Single ordered command list

First source the three workspaces. This only changes the current shell:

```bash
source /opt/ros/noetic/setup.bash
source ~/agilex_ws/devel/setup.bash
source ~/limo_v1_overlay_ws/devel/setup.bash
```

Default dry-run; this starts nothing:

```bash
rosrun limo_v1_navigation v1_perception_only_field.py
```

Read-only host precheck; this starts/stops nothing and opens no device:

```bash
rosrun limo_v1_navigation v1_perception_only_field.py \
  --read-only-precheck
```

Only after the fresh main-task authorization, run the action form from an
interactive on-site terminal:

The action form remains prohibited while the vendor include/publisher pin is
missing. Authorization does not override `BLOCKED_ON_VENDOR_INCLUDE`.

```bash
rosrun limo_v1_navigation v1_perception_only_field.py \
  --execute-hardware \
  --authorization-id <ONE_TIME_AUTHORIZATION_ID> \
  --vendor-tf-rules-file /absolute/verified/vendor_tf_rules_v2.json \
  --vendor-source-manifest-file /absolute/verified/vendor_source_manifest.json \
  --vendor-publisher-pin-file /absolute/verified/vendor_publisher_pin.json \
  --confirm-exact START_PERCEPTION_ONLY \
  --result-file /absolute/existing/result-dir/v1_perception_<timestamp>.json
```

The script then requires the operator to type a second exact
`START_PERCEPTION_ONLY`. Piped input, missing/short authorization, an existing
result file, or any precheck blocker fails before hardware launch.
Missing paths, missing referenced bytes, a blocker/artifact status other than
`VERIFIED`, trust-anchor mismatch, include-child mismatch, unresolved launch
namespace/substitution/condition/remap, or any byte/semantic mismatch returns
`TF_VENDOR_CONTRACT_UNVERIFIED` before authorization or hardware startup.

## What the script verifies

Pre-start:

- no matching ROS/base/lidar/navigation process;
- no existing ROS master (the procedure must own its lifecycle);
- `/dev/ttyTHS0` and `/dev/ydlidar` both present and unowned;
- no cmd_vel-like publisher if a master unexpectedly exists.

Runtime, with no command publication:

- exactly `/ydlidar_lidar_publisher -> /scan`;
- 30 scans at `4.8-7.2 Hz`, every frame `laser_link`;
- angle min/max `-100/+100 degrees` within `0.5 degree`;
- finite strictly increasing scan stamps and source age `[-0.1, 0.5) s`;
- exactly `/limo_base_node -> /odom`, with 10 strictly increasing
  `odom/base_link` messages;
- every transform in each `TFMessage` is attributed by normalized parent,
  child, connection-header `callerid`, exact callback-bound `/tf` or
  `/tf_static` topic, source stamp, monotonic receipt time, and geometry
  fingerprint;
- `odom -> base_link` has exactly one parent/authority/topic, with target
  authority `/limo_base_node`, dynamic `/tf`, and fresh advancing stamps;
- `base_link -> laser_link` has static semantics and matches exactly the
  verified vendor pin. Its historical candidate authority
  `/base_link_to_laser_link` is not accepted until the pin verifies it;
- a legacy pinned `/tf` static edge repeats invariant geometry with advancing
  stamps; a pinned latched `/tf_static` edge may have a zero/old source stamp
  but must be observed in-session, remain geometrically invariant if repeated,
  and retain its graph owner;
- each protected child (`odom`, `base_link`, `laser_link`) has one parent and
  one authority, and no edge appears across both `/tf` and `/tf_static`;
- segment TF lookup succeeds; `map -> odom` is absent;
- public `/cmd_vel` has zero endpoints, `/v1/driver_cmd_vel` has no
  publisher and only `/limo_base_node` as subscriber;
- teleop, SLAM, localization, navigation, bridge and V1 guard nodes absent.

Stop:

- sends signals only to the process group it started;
- confirms the ROS master and matched child processes disappeared;
- confirms `/dev/ttyTHS0` and `/dev/ydlidar` are unowned again.

## PASS/BLOCK

`V1_PERCEPTION_ONLY_PASS` requires precheck, every runtime measurement, and
cleanup all PASS in the same session, plus a verified vendor include and
static-publisher pin bound into the structured result as blocker/source/pin/
rules/raw-launch/executable paths and actual SHA-256 values. Any missing sample,
unknown/alias owner, wrong parent/child, cross-topic duplicate, transport or
static/dynamic behavior mismatch, unexpected velocity endpoint/node, process
exit, stale/rollback timestamp, angle/rate mismatch, failed TF segment, or
unreleased process/device produces `V1_PERCEPTION_ONLY_BLOCKED`.

This bounded field capture proves only the recorded session. It is not a
continuous guard or localization-READY monitor, and TF lookup alone is never
authority evidence.

Dry-run and read-only outputs are never on-robot sensing PASS. On BLOCK, do not
kill or alter unknown work; retain the JSON/log evidence and return control to
the main task/on-site operator.
