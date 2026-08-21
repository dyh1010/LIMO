# V1 zero-motion field preparation package

Status: prepared offline. This document does not authorize connecting to the
robot, opening serial devices, starting sensors, or moving the base. The
current hard boundary is no physical motion: no navigation request, no
nonzero velocity, no rotation scan, and no recovery behavior.

## 1. Authorization classes

| Class | Examples | Required authorization |
|---|---|---|
| Offline only | Tests, JSON/schema checks, report generation from existing files | None |
| Real-machine read-only | Process/port audit, sensor/base launch, scan/odom/TF preflight, localization with nonzero disabled, subscriber-only capture | Fresh hardware/read-only authorization for that session; on-site operator present |
| Real-machine administrative, zero motion | One-shot initial-pose authorization, RViz `2D Pose Estimate`, localization reset | Fresh hardware/read-only authorization; verify no motion-capable ingress is enabled |
| Real-machine motion | Any navigation request, arm/rearm that opens motion authority, teleop, rotation, recovery, obstacle or cancel timing run | A separate explicit authorization for that exact run plus clear area and an on-site person holding the physical main switch/e-stop |

Software cancel, a zero message, and the V1 stop latch do not replace the
physical e-stop or power disconnect.

## 2. Required values before a future session

Record these before any hardware command is run:

```text
authorization_id=
operator_name=
observer_at_main_switch=
robot_id=
active_map_id=
absolute_map_yaml=
absolute_existing_capture_directory=
session_id=
```

The map path must be absolute, frozen, non-vendor, and its stem must equal
`active_map_id`. The capture directory must already exist. Each capture tool
run creates a new exclusive timestamped file and never overwrites evidence.

## 3. Safe startup sequence

These are future operator steps, not commands to run under the current
offline-only boundary.

1. Lift the wheels/tracks clear of the floor or apply a verified physical
   restraint, and clear people and objects from the mechanism. Keep a person
   at the physical main switch/e-stop even though the intended stage is zero
   motion.
2. Perform the read-only process, ROS graph, ROS2 graph, and serial-owner audit
   from `V1_FIELD_RUNBOOK.md` section 4. Stop if any unexpected driver,
   teleop, SLAM, navigation, bridge, or serial owner exists.
3. After fresh hardware/read-only authorization only, first execute the
   isolated sensing-only procedure in `V1_PERCEPTION_ONLY_FIELD_PACKAGE.md`.
   Preserve its zero-output result and SHA-256; do not continue unless it
   proves the expected sensor owners and no velocity-capable endpoint.
4. Start `v1_base_sensors.launch` with the one-time authorization ID. Do not
   start teleop or any navigation request source.
5. Run `v1_runtime_preflight.launch stage:=scan samples:=30`. Continue only on
   the exact `V1_SCAN_ODOM_TF_PREFLIGHT_PASS` marker.
6. Validate the frozen map offline with `validate_v1_profile.py --stage
   localization` before starting localization.
7. Start localization-only for AMCL convergence evidence. Do not start the
   navigation wrapper. If a later, separately authorized zero-output topology
   audit needs it, the navigation zero stage must keep all motion authority
   explicitly off:

   ```text
   allow_nonzero=false
   driver_timeout_verified=false
   enable_goal_gateway=false
   allow_goal_forwarding=false
   ```

8. Start the subscriber-only diagnostic capture for a finite duration before
   the explicit initial-pose sequence.
9. Verify READY is false and the manager reports that an explicit initial pose
   is required. Open one one-shot initial-pose authorization window and issue
   exactly one RViz `2D Pose Estimate`. Do not issue `2D Nav Goal`.
   Do not manually call or loop `/request_nomotion_update`; the localization
   manager is the sole scheduler for those bounded no-motion updates.
10. Observe convergence and READY only. Do not arm/rearm a motion path. Stop on
   any unexpected nonzero command, wrong owner, stale chain, or process drift.

## 4. Subscriber-only diagnostic collection

Future authorized invocation:

```bash
rosrun limo_v1_navigation v1_diagnostic_capture.py \
  --duration-s 120 \
  --output-dir /absolute/existing/capture_directory \
  --label v1_zero_motion
```

Contract:

- finite wall-clock duration, maximum 3600 seconds;
- subscribers only: localization/navigation status, AMCL, scan, and odom;
- no publisher, service proxy, action client, navigation request, Twist, or
  velocity topic;
- absolute existing output directory, safe label, exclusive new timestamped
  JSONL file, no overwrite;
- construction/runtime errors close the file and unregister subscriptions on
  a best-effort basis.

Recommended captures are one file per cold start, plus a separate fixed-pose
post-READY capture of at least 30 AMCL samples. The current status stream
provides aggregate no-motion successes/failures and `nomotion_call_active`; it
does not provide an authoritative timestamp/latency record for each individual
service call. Do not reconstruct or claim exact per-call latency from the 10 Hz
status observations. Preserve the printed `V1_DIAGNOSTIC_CAPTURE_PASS` path,
compute SHA-256 for the new JSONL, and record both in the worksheet.

## 5. Zero-motion convergence worksheet

Use one row per cold start. Target: `3/3` reach READY within `45 s`.

| Session/run | Map ID + YAML SHA256 | Accepted initial-pose wall time | First strictly newer AMCL time | READY time | Convergence seconds | Successful no-motion count | Failed/time-out count | Max covariance x/y/yaw | Stable samples/duration | Final reason | PASS/BLOCKED |
|---|---|---|---|---|---:|---:|---:|---|---|---|---|
| | | | | | | | | | | | |
| | | | | | | | | | | | |

The diagnostic JSONL stores AMCL quaternion fields. Preserve it unchanged as
raw evidence, then derive a separately checksummed `x,y,yaw` CSV for the
repeatability report; record the conversion command/version in the session
notes.

READY thresholds remain variances `cov_xx/cov_yy/cov_yawyaw <= 0.010`, at
least 8 samples spanning 3 seconds, position span `<=0.05 m`, yaw span
`<=0.05 rad`, and 10 successful no-motion updates. These thresholds must not
be loosened to hide absolute error. READY is a convergence/chain gate, not a
claim of centimetre-level absolute accuracy.

## 6. Stationary repeatability worksheet

For each known fixed physical mark, collect at least 30 `x,y,yaw` AMCL samples
after READY. Store the exact CSV consumed by the offline report tool.

| Mark ID | Run ID | Sample count | Mean x/y/yaw | Stddev x (m) | Stddev y (m) | Circular yaw stddev | Absolute truth available? | PASS/BLOCKED |
|---|---|---:|---|---:|---:|---:|---|---|
| | | | | | | | no/yes | |

Thresholds: `stddev x/y <=0.05 m`, circular yaw stddev `<=5 degrees`.
Repeatability is spread, not absolute localization accuracy.

Offline report command:

```bash
rosrun limo_v1_navigation v1_acceptance_report.py repeatability \
  --csv /absolute/input/amcl_samples.csv \
  --output /absolute/new/repeatability_report.json
```

Complete
`docs/examples/v1_repeatability_provenance_manifest_template.json` beside the
report. It binds the unmodified source JSONL and SHA-256 to the conversion
tool, version/SHA, exact command, derived CSV and SHA-256, fixed physical mark,
sample window, and the status evidence proving READY remained true. Select
exactly one measurement class:

```text
within_run_stationary_jitter
cross_relocalization_repeatability
```

Do not aggregate the two classes into one PASS. Missing source hashes,
conversion provenance, fixed-mark identity, or READY evidence makes the record
`BLOCKED`, not an estimated result.

## 7. Zero-motion absolute-localization worksheet

Repeatability alone cannot answer whether AMCL is correct at a surveyed
physical location. Record that independent evidence in
`docs/examples/v1_zero_motion_absolute_localization_evidence_template.json`.
This measurement keeps the base stationary at a surveyed mark and does not
start the navigation wrapper or use any motion ingress.

The surveyed truth pose and stationary AMCL pose must be comparable in the
same `map` frame. If the surveying instrument works in another frame, bind the
raw survey, calibrated frame transform, calibration record, and SHA-256 for
each artifact. Record the exact robot reference point and heading fixture so a
map pose is not compared with a different point on the chassis.

Use only AMCL samples inside one checksummed window where localization READY
and chain health remained continuously true. Preserve the raw diagnostic
capture and the extracted sample artifact separately, with their SHA-256 and
the aggregation rule that produced the stationary AMCL pose. Missing truth,
transform, calibration, raw capture, READY-window, or hash evidence makes the
record `BLOCKED`.

The signed error definition and position decision are frozen as:

```text
absolute localization error = surveyed truth pose - stationary AMCL pose
position error = hypot(error_x, error_y)
position PASS threshold = 0.10 m
```

Yaw error is recorded for inspection, but no yaw PASS threshold is frozen;
the template therefore requires `yaw_not_thresholded=true`. Covariance and
repeatability do not prove absolute localization accuracy. This zero-motion
absolute-localization PASS is independent of repeatability, navigation control
endpoint, physical total endpoint, static-avoidance, and dynamic-avoidance
PASS, in both directions.

## 8. Motion-era error worksheet (frozen, do not execute yet)

Keep these fields ready for a later separately authorized run:

| Run | Requested endpoint x/y/yaw | Final AMCL x/y/yaw | Independent physical truth x/y/yaw | AMCL estimation error | Navigation control endpoint error | Physical total endpoint error | Controller result | Contact? |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

Definitions:

```text
AMCL estimation error             = physical truth - AMCL final
navigation control endpoint error = requested endpoint - AMCL final
physical total endpoint error     = requested endpoint - physical truth
```

Default report thresholds are `0.10 m`, `0.10 m`, and `0.15 m` respectively.
The configured controller `xy_goal_tolerance=0.15 m` is an estimated-frame
success contract and is not an AMCL accuracy guarantee.

The exact five-field `limo_v1_endpoint_measurement/v1` input remains frozen.
For each input, complete the separate
`docs/examples/v1_endpoint_evidence_manifest_template.json`. The companion
manifest binds one session/trial/request ID to:

- goal, final AMCL, and independent truth frame and time evidence;
- raw status/pose/physical-measurement paths and SHA-256;
- the truth instrument, calibration, measurement method, and robot reference
  point;
- the stationary stop window and rule used to select `amcl_final`;
- the exact endpoint input and derived report paths and SHA-256.

All three poses must be expressed in the same documented `map` frame. If the
physical instrument measures in another frame, preserve the calibrated
transform evidence and its SHA-256. Hash raw evidence before producing the
five-field input or report; never overwrite it.

The current endpoint report thresholds position only. It calculates yaw
differences for inspection but has no frozen yaw PASS threshold. Every
companion manifest must therefore retain `yaw_not_thresholded=true`; an
endpoint `overall_passed=true` must never be described as a yaw acceptance.

## 9. Static and dynamic avoidance worksheet (frozen, do not execute yet)

Avoidance evidence is recorded independently in
`docs/examples/v1_avoidance_evidence_worksheet_template.json`. Do not insert
avoidance observations into the endpoint input or infer avoidance from an
endpoint report.

A static trial is valid only when the soft obstacle placement is measured,
intersects the frozen nominal path corridor, is observed by the navigation
sensor chain, and has independently recorded contact and minimum-clearance
evidence. Target: `3/3` valid trials with zero contact. A robot that never
approached and encountered the obstacle while the recorded request was active
is `BLOCKED`, not a zero-contact PASS.

A dynamic trial is valid only when the soft obstacle crosses the frozen path
and protective boundary and all timing evidence is present in one authorized
motion rosbag. Target: `5/5` valid trials, zero contact, and
`response_s <=0.8`. The timing definition is fixed as follows:

```text
clock domain = record timestamps from one rosbag recorder
t0 eligibility = the recorded request is active and the sole driver command
                 is finite planar nonzero throughout [t0-0.25 s, t0)
t0 = first rosbag record time at which full-scan geometry proves the obstacle
     entered the predeclared, checksummed protective boundary
t1 = first rosbag record time at or after t0 at which the topology-validated
     mode-specific sole driver command is exactly planar zero and remains
     uninterrupted zero for at least 0.25 s
response_s = t1 - t0
```

For native mode the sole driver command topic is `/v1/driver_cmd_vel`; for
integrated mode it is `/cleanup/base/driver_cmd_vel`. Missing full scan ranges,
missing command evidence, a clock-domain mismatch, a missing zero hold, or an
unexercised obstacle makes the timing result `BLOCKED`. A command already zero
at t0 cannot be credited as a zero-second response; absent t0 eligibility is
`BLOCKED`. The existing
subscriber-only JSONL diagnostic capture records scan timing/sample count but
not ranges or the driver command, so it cannot by itself prove avoidance. Do
not extend or replace that frozen zero-motion tool here; a later full rosbag
capture requires explicit authorization for the exact motion trial.

The worksheet separates common sensor/TF topics from mode-specific status and
sole driver-command topics. Native evidence requires the V1 localization,
gateway, guard, and `/v1/driver_cmd_vel` chain. Integrated evidence requires
the bridge status and `/cleanup/base/driver_cmd_vel` chain and must not invent
or require a V1 guard that is forbidden in integrated topology.

Zero-motion absolute localization, endpoint, repeatability, static-avoidance,
and dynamic-avoidance decisions are independent. PASS in any one class implies
no PASS in another. Each trial must bind its authorization,
software/map/config hashes, request ID where applicable, raw evidence hashes,
derived artifacts, result, and block reason. Missing provenance is fail-closed.

## 10. Authorization-gated items still NOT_RUN/BLOCKED

- real sensor/base startup and serial access;
- three cold-start zero-motion convergence captures;
- fixed-mark repeatability and absolute ground-truth measurement;
- independent driver-timeout stopping proof;
- any gateway arm/rearm that can open motion authority;
- point-to-point navigation, endpoint measurement, explicit cancellation
  timing, static/dynamic avoidance, scan/odom/TF loss stopping;
- any teleop, automatic rotation, recovery behavior, or nonzero velocity.

When the user later authorizes a read-only real-machine session, perform only
sections 2-7. Every motion-era item requires a fresh, narrower authorization
for that exact test; permission for sensors or localization does not carry
over to movement.
