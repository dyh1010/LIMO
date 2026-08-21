# V1 localization and navigation acceptance

Status: software prepared and tested offline; physical motion acceptance is
frozen until a later explicit authorization. Nothing in this document grants
permission to move the robot. Software cancel/zero is not a physical e-stop or
power disconnect.

Evidence classification is independent of the formal readiness fields. The
latest user-reported PoseArray convergence, motion-time qualitative
convergence, and successful real Nav Goal are `USER_OBSERVED` with `PARTIAL`
gate progress and an `UNSEALED` archive. Formal acceptance remains
`NOT_ASSESSED`, and frozen field readiness remains `NOT_RUN`, until exact raw
artifacts, trial counts, measurements, and provenance are bound. See
`V1_USER_OBSERVED_FIELD_EVIDENCE_AUDIT.md`.

## Fail-closed runtime contract

The localization manager is the only public `/initialpose` consumer. Before
using RViz `2D Pose Estimate`, an operator must open one short-lived, one-use
authorization window:

```bash
rosservice call /v1_localization_manager/authorize_initial_pose
```

The manager validates a fresh `map` pose, a normalized planar quaternion and
positive bounded covariance, then republishes it privately to AMCL on
`/v1/validated_initialpose`. It never guesses `(0, 0, 0)` and never publishes a
velocity.

After the validated pose, it calls `/request_nomotion_update` once per second.
The default READY gate requires all of the following:

- exact map/scan/odom/TF and owner chain;
- ten successful no-motion updates;
- fresh `/amcl_pose` in frame `map`;
- variance `cov_xx`, `cov_yy`, and `cov_yawyaw` each no greater than `0.010`;
- at least eight samples spanning three seconds;
- window position span no greater than `0.05 m` and yaw span no greater than
  `0.05 rad`.

Status endpoints:

```text
/v1/localization/ready        std_msgs/Bool
/v1/localization/status       std_msgs/String JSON
/v1/localization/diagnostics  std_msgs/String JSON
```

The covariance fields are variances. A variance of `0.009 m^2` means roughly
`0.095 m` one-sigma, not `0.009 m` error. READY proves configured repeatability
and chain health; it does not prove centimetre-level absolute accuracy.

## Goal, cancel and status boundary

The native move_base action and simple-goal endpoint are private. Do not use
RViz `2D Nav Goal` as a V1 acceptance ingress. The project gateway accepts:

```text
/v1/navigation/goal    geometry_msgs/PoseStamped
/v1/navigation/cancel  std_msgs/Bool (true cancels)
/v1/navigation/status  std_msgs/String JSON
/v1/navigation/error   std_msgs/String JSON
```

The gateway assigns its own monotonic request ID; it does not use the obsolete
`PoseStamped.header.seq` field. `frame_id` must be `map`. A goal is forwarded
only when both launch arguments
are explicitly true, localization READY is fresh, the private move_base action
server exists, and the operator has explicitly armed the gateway:

```text
enable_goal_gateway=true
allow_goal_forwarding=true
rosservice call /v1_navigation_gateway/arm
```

All three controls remain false/disarmed by default. READY loss, a stale READY
heartbeat, private action loss, cancel, a latched guard fault, or a stale or
missing guard heartbeat cancels the current goal, disarms the gateway and
prevents an old goal from resuming. The velocity guard also requires fresh
READY before rearm and on every output cycle.

## Zero-motion localization acceptance

This stage does not require the base to move, but starting robot sensors still
requires the applicable hardware authorization. Record for each of three cold
starts:

- time from accepted initial pose to READY;
- every no-motion request and result;
- raw variances and square-root standard deviations;
- at least 30 fixed-pose samples after READY;
- scan/odom/map/TF freshness and exact owners;
- READY loss reason, if any.

Acceptance thresholds:

- `3/3` runs reach READY inside the configured `45 s` convergence timeout;
- fixed-pose sample standard deviation `x/y <= 0.05 m`;
- circular yaw standard deviation `<= 5 degrees`;
- no guessed initial pose, no automatic rotation and no velocity publication.

Generate a repeatability report offline from an exact `x,y,yaw` CSV:

```bash
rosrun limo_v1_navigation v1_acceptance_report.py repeatability \
  --csv /absolute/input/amcl_samples.csv \
  --output /absolute/new/report.json
```

For read-only ROS status capture during a later authorized sensor-only run:

```bash
rosrun limo_v1_navigation v1_diagnostic_capture.py \
  --duration-s 60 \
  --output-dir /absolute/existing/capture_directory \
  --label v1_diagnostics
```

The capture tool only subscribes to localization/navigation status, AMCL,
scan, and odom. It creates no publisher, action client, or service proxy and
refuses to overwrite an existing output file.

## Physical endpoint error separation

When motion is later authorized, do not report one ambiguous "centimetre
error". Measure the goal, final AMCL pose and independently measured physical
pose, then compute:

```text
AMCL estimation error             = ground truth final - AMCL final
navigation control endpoint error = goal - AMCL final
physical total endpoint error     = goal - ground truth final
```

The offline input schema is:

```json
{
  "schema": "limo_v1_endpoint_measurement/v1",
  "active_map_id": "limo_v1_map",
  "goal": {"x": 0.0, "y": 0.0, "yaw": 0.0},
  "amcl_final": {"x": 0.0, "y": 0.0, "yaw": 0.0},
  "ground_truth_final": {"x": 0.0, "y": 0.0, "yaw": 0.0}
}
```

Run:

```bash
rosrun limo_v1_navigation v1_acceptance_report.py endpoint \
  --input /absolute/input/endpoint.json \
  --output /absolute/new/report.json
```

The JSON key remains `controller_estimated_frame_error` for schema stability;
its interpretation is the navigation control endpoint error. Default report
position thresholds are `0.10 m` for AMCL estimation, `0.10 m` for navigation
control, and `0.15 m` for the independently measured physical total endpoint.
These are acceptance thresholds, not claims derived from covariance alone.

Package-local, synthetic offline examples are under `docs/examples/`. They are
format fixtures only and must never be presented as real-machine evidence.

## Motion acceptance frozen for later authorization

The following remain `NOT_RUN/BLOCKED` under the current no-motion boundary:

- odometry distance/yaw scale against physical measurement;
- empty-space point-to-point navigation `5/5`;
- cancel `3/3` with the complete command chain at zero within `0.5 s`;
- static soft obstacle `3/3` zero contact;
- dynamic soft obstacle `5/5` zero contact and response within `0.8 s`;
- scan/odom/TF loss stopping and independent driver timeout stopping.

Before any later nonzero test: clear the area, keep an on-site person at the
physical main switch/e-stop, confirm the software gate is not treated as the
physical stop, and request a fresh explicit authorization for that test.
