# V1 user-observed field evidence audit

Status: local evidence reclassification only. No ROS graph, sensor, serial
device, action endpoint, velocity interface, or hardware was accessed while
producing this audit.

## 1. Classification boundary

The latest user statement contains real field observations, so it must not be
described as if no field information exists. It also lacks a bound session,
observation time, raw artifact, measured pose, trial count, and checksummed
provenance, so it cannot be promoted to a formal PASS.

Use four independent fields:

| Axis | Current value | Meaning |
|---|---|---|
| Observation | `USER_OBSERVED` | A user directly reported the behavior on the real robot. |
| Gate progress | `PARTIAL` | The report closes only the limited functional conclusion stated below. |
| Formal acceptance | `NOT_ASSESSED` | No frozen acceptance threshold can yet be adjudicated from raw evidence. |
| Archive state | `UNSEALED` | No matching raw artifact set has been bound and checksummed. |

The frozen readiness report may therefore continue to show formal field items
as `NOT_RUN/template_only`. That label describes the formal gate, not an
absence of all user observations. The independent increment is stored at
`evidence/v1_field_observation_20260814/user_observed_partial.json`.

## 2. What the latest observations do and do not establish

### PoseArray converged

This closes only the qualitative conclusion that AMCL `/particlecloud` can
concentrate on the real robot at least once. It also supersedes the broad
claim that AMCL is currently incapable of convergence.

It does not prove that the frozen localization manager accepted the initial
pose, that READY became true, that 10 no-motion requests succeeded, that the
covariance/stability window passed, that all `3/3` cold starts completed
inside 45 seconds, or that 30 post-READY samples were collected. A compact
PoseArray does not prove absolute localization accuracy.

The initial-pose ingress is therefore recorded as `UNRESOLVED`; this audit
does not guess that the manager path was used.

### Particle cloud remained converged during navigation

This closes only the qualitative conclusion that at least one reported
navigation run did not show an obvious global delocalization. It does not
prove continuous READY, quantitative covariance stability, scan/odom/TF
continuity, odometry scale, repeatability, or absolute localization accuracy.

### A real Nav Goal succeeded

This closes only the functional conclusion that at least one real move_base
point-to-point run was reported successful. The user's term "Nav Goal" does
not identify whether the approved V1 gateway, RViz, or another ingress was
used, and no action terminal state was archived. The increment therefore uses
`ingress=UNRESOLVED_USER_TERM_NAV_GOAL` and a null terminal state.

This does not close the V1 gateway contract, empty-space navigation `5/5`,
cancel/status/error handling, endpoint accuracy, driver timeout, or static or
dynamic avoidance. Point-to-point functional success is recorded separately
from all three endpoint error decisions.

### Centimeter-level endpoint deviation

This is an unquantified user observation. Its numeric value remains null. It
cannot be assigned to any one of the following without three separately
preserved poses:

```text
AMCL estimation error             = independent physical truth - final AMCL
navigation control endpoint error = requested goal - final AMCL
physical total endpoint error     = requested goal - independent physical truth
```

No PASS or FAIL follows from the word "centimeter-level" alone.

## 3. Frozen thresholds and still-open gates

The frozen position thresholds remain unchanged:

- AMCL estimation error: `<= 0.10 m`;
- navigation control endpoint error: `<= 0.10 m`;
- physical total endpoint error: `<= 0.15 m`;
- repeat localization x/y standard deviation: each `<= 0.05 m`;
- repeat localization circular yaw standard deviation: `<= 5 degrees`.

The 5-degree value is a repeatability dispersion limit. There is no frozen
endpoint or absolute-localization yaw PASS threshold. The move_base
`xy_goal_tolerance=0.15 m` is an estimated-frame controller completion radius;
it is not proof of AMCL accuracy or physical total endpoint accuracy.

Formal evidence is still missing for:

- `3/3` cold starts reaching READY within 45 seconds, including no-motion,
  covariance, stability-window, map, scan, odom, TF, and owner evidence;
- at least 30 fixed-pose post-READY samples for each applicable run;
- empty-space point-to-point navigation `5/5` through a resolved ingress;
- requested goal, final AMCL pose, and independent physical truth for the
  three independent position errors;
- cancel `3/3` and the complete command chain reaching zero within 0.5 s;
- independent driver-timeout stopping;
- static soft-obstacle avoidance `3/3` with zero contact;
- dynamic soft-obstacle avoidance `5/5` with zero contact and response within
  0.8 s;
- scan-loss, odom-loss, and TF-loss stopping.

## 4. Local asset inventory and offline-use boundary

No current successful-run rosbag/DB3/MCAP, diagnostic JSONL, navigation or
AMCL CSV, relevant screenshot/video, or raw runtime log was found under the
audited local workspaces. The historical handoff at
`C:\Users\DYH\Desktop\limo_graphtest\V1_REAL_MACHINE_HANDOFF_2026-08-13.md`
has SHA-256
`1b787fec35df1ad3cf60f88de1749d01b90837fc3b6713a3d72fc69679aed3c5`.
It preserves an older observation but is not raw measurement evidence for the
latest successful run.

The package examples `amcl_repeatability_pass.csv` and
`endpoint_measurement_pass.json` are synthetic format fixtures. They cannot
be used as real-machine PASS evidence.

If an already-existing artifact is later supplied, it can be analyzed without
starting ROS or moving the robot:

| Artifact | Offline conclusions it may support | Important limitation |
|---|---|---|
| Bag with `/particlecloud` | particle spread and qualitative/quantitative concentration over time | does not alone prove READY or absolute accuracy |
| Bag with `/amcl_pose`, READY/status, scan, odom and TF | convergence time, covariance, freshness and whether localization stayed healthy | requires exact topic provenance and complete time window |
| Goal/action/status log or bag | ingress, request identity, terminal state and trial outcome | does not prove physical endpoint or avoidance alone |
| Driver-command trace plus event timestamps | cancel/loss/timeout stop latency | subscriber-only diagnostic JSONL does not record this chain |
| Exact `x,y,yaw` CSV plus provenance | within-run jitter or cross-relocalization repeatability | spread does not prove absolute accuracy |
| Endpoint JSON plus raw goal/AMCL/truth manifests | the three independent endpoint errors | physical truth needs calibrated, frame-bound measurement |
| Screenshot | qualitative particle concentration or displayed state | cannot prove duration, trial count, timing or metric threshold |
| Synchronized video and calibrated measurement | contact, obstacle response and physical truth support | must preserve clock, scale, reference point and calibration |

The current subscriber-only diagnostic collector does not subscribe to
`/particlecloud`, full TF geometry, full scan ranges, or driver commands. It
cannot by itself close PoseArray, avoidance, or complete-stop gates.

## 5. Minimum future authorization

No authorization is needed to classify the current local statement or to
analyze files already present in the user-provided workspace.

- Copying existing artifacts from the robot requires a fresh
  `hardware_read_only` authorization.
- Repeating `3/3` cold starts, collecting 30 samples, and stationary absolute
  localization requires `hardware_read_only + zero_motion_localization` for
  that exact session. This does not authorize base motion.
- Navigation `5/5`, endpoint triad, cancel, timeout, obstacle, and loss-stop
  evidence each require a fresh exact-scope `real_motion` authorization plus
  its prerequisites and an on-site physical-stop observer.

Any missing, stale, reused, or scope-mismatched authorization remains
fail-closed. Software stop is never a substitute for physical isolation.
