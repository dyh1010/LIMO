# limo_v1_navigation

Project-owned ROS1 Noetic overlay for LIMO V1 2D mapping, localization, and
navigation. It does not modify or include the vendor navigation launch and it
does not import or start any ROS1/ROS2 bridge implementation.

ROS1 Noetic is the authoritative default field runtime. ROS2/Foxy is limited
to offline source or an explicitly selected bridge mode and must never create
a second driver, TF owner, velocity chain, navigation stack, or goal owner.
The provisional expected-owner table is
`docs/V1_ROS1_RUNTIME_OWNERSHIP.md` with a machine-readable JSON companion.
It remains `BLOCKED_ON_VENDOR_INCLUDE` until the current vendor
`limo_start.launch` bytes and recursive roslaunch expansion are archived and
verified; wrapper remaps do not close that evidence gap.

Safety properties:

- every hardware, mapping, localization, and navigation launch is inert by
  default;
- `map_file`, `active_map_id`, `preflight_token`, and `odom_tf_owner` have no
  unsafe fallback;
- `/limo_base_node` is the only accepted `odom -> base_link` owner and is
  launched with `pub_odom_tf=true`; `robot_pose_ekf` is forbidden;
- the installed `v1_navigation.launch` and `v1_navigation_core.launch` are
  native-only; neither accepts an integrated mode or the bridge request topic;
- the core owns exactly one project map_server, AMCL, and move_base and always
  maps move_base to `/v1/nav_cmd_vel`; the V1 guard is the sole publisher to
  `/v1/driver_cmd_vel`;
- the core never starts a driver, guard/watchdog, bridge adapter, or RViz;
- 6 Hz scan, odom, TF, command freshness, exact ownership, finite planar Twist,
  conservative velocity, and acceleration limits are fail-closed;
- nonzero output defaults off and cannot be enabled until independent driver
  timeout stopping has been field-verified;
- AMCL accepts only manager-validated explicit initial poses, performs bounded
  no-motion convergence, and exports a covariance/stability READY heartbeat;
- the public goal gateway is disabled by default, requires fresh READY plus an
  explicit arm, and owns goal/cancel/status while move_base endpoints remain
  private;
- vendor maps, including the currently hardcoded demonstration map, are
  rejected as V1 active maps.

AMCL `transform_tolerance` is fixed at `0.05 s`, matching the bridge expected
value and remaining below its `0.10 s` source-future hard cap.

Reusable include contract:

```xml
<include file="$(find limo_v1_navigation)/launch/v1_navigation_core.launch">
  <arg name="map_file" value="$(arg map_file)" />
  <arg name="active_map_id" value="$(arg active_map_id)" />
  <arg name="preflight_token" value="$(arg preflight_token)" />
</include>
```

Only `/v1/nav_cmd_vel` is accepted by installed V1 launch files. V2 integrated
navigation must be generated inside the bridge runner's private immutable
snapshot launch; it must not invoke either installed V1 navigation launch.

Offline checks:

```bash
python3 scripts/audit_v1_overlay.py
python3 scripts/validate_v1_profile.py --stage scan
python3 ../../scripts/test_ros1_v1_navigation_offline.py
```

No command above starts ROS or publishes velocity. See
`docs/V1_LOCALIZATION_NAVIGATION_ACCEPTANCE.md` for the current convergence,
goal/cancel/status contract and `docs/V1_FIELD_RUNBOOK.md` for future,
separately authorized field stages.

`v1_diagnostic_capture.py` is a subscriber-only future field data collector.
Starting ROS against sensors still requires the applicable authorization, but
the tool itself has no publisher, action client, service proxy, or motion API.
