# V1 deployment, diagnostics, and rollback audit

Status: audited offline on 2026-08-14. Formal frozen-release field acceptance
and execution records remain NOT_RUN and BLOCKED. Separate real-machine user
observations are classified in section 7.1. This document does not authorize
starting ROS, opening a serial device, starting a sensor, sending a navigation
request, publishing a velocity, or moving the base.

The software release result and the field-delivery result are deliberately
separate. A complete offline regression PASS may establish
software_release_pass, but it cannot set field_acceptance_complete or
delivery_ready. The companion field-session record therefore starts with
template_only=true, status=NOT_RUN, and delivery_ready=false.

## 1. Authority and entry-point hierarchy

Use the following hierarchy. A lower item may not override a higher one.

1. The current direct user instruction and physical safety boundary.
2. V1_FIELD_AUTHORIZATION_STATE_MACHINE.md and the companion field
   authorization checklist. The checklist is template data and is not an
   authorization validator.
3. V1_ZERO_MOTION_FIELD_PREPARATION.md for a future stationary localization
   session.
4. V1_FIELD_RUNBOOK.md for the frozen native topology and later motion-era
   acceptance procedure.
5. This document for deployment selection, diagnostic evidence, and rollback.

The historical file
C:\Users\DYH\Desktop\limo_graphtest\V1_REAL_MACHINE_HANDOFF_2026-08-13.md
is evidence of earlier field observations only. It contains older vendor
launch, parameter, terminal, and teleoperation procedures. It is not an
execution entry point and must not be used to bypass the hierarchy above.

The offline release evidence entry is:

    python3 scripts/run_v1_frozen_offline_regression.py --report NEW_FILE.json

It is Linux/POSIX-only for the complete matrix, creates a new report
exclusively, and does not start ROS or access hardware. Its PASS is software
evidence only.

## 2. Deployment disposition

| Mode | Audited entry | Current field disposition |
|---|---|---|
| native | limo_v1_navigation launch files, in the staged order below | BLOCKED until a fresh exact-scope field admission exists and all preflight evidence passes |
| integrated | zero-stage safety-chain runner plus bridged-navigation runner | software design PASS; field execution remains BLOCKED until fresh authorization and real-machine preflight pass |

There is no autostart deployment in the audited V1 or bridge scope. The
required policy is NO_AUTOSTART: no boot service, login task, scheduled task,
respawn wrapper, or automatic restart is an approved entry. Every future
session must be started manually under on-site supervision, with a new
session record. Do not add an autostart mechanism as a deployment shortcut.

### 2.1 Native safe defaults

The native entry is inert when arguments are omitted:

- v1_base_sensors.launch defaults enable_hardware=false.
- v1_navigation.launch defaults allow_nonzero=false,
  driver_timeout_verified=false, enable_goal_gateway=false, and
  allow_goal_forwarding=false.
- move_base.yaml disables recovery behavior and clearing rotation.
- A public RViz navigation control is not an approved high-level request
  ingress.

These defaults are safety gates, not proof of authorization. The current
field-authorization checklist remains NOT_RUN/BLOCKED because the frozen
release has no dedicated orchestrator that verifies and atomically consumes a
fresh grant bundle. Filling a template or changing a launch boolean cannot
make the field stage execution-ready.

### 2.2 Future native manual sequence

The following is a gated order, not authorization to execute it:

1. OFFLINE_EVIDENCE: preserve the exclusive frozen-regression report and its
   SHA-256. Require all software checks to pass, while leaving
   delivery_ready=false.
2. FIELD_ADMISSION: create a new session record and satisfy the exact grant
   class in V1_FIELD_AUTHORIZATION_STATE_MACHINE.md. Recheck identity, scope,
   expiry, revocation, physical restraint, and the on-site physical-stop
   observer immediately before the boundary.
3. OWNER_AUDIT: record process, ROS graph, ROS2 graph, and serial-owner
   evidence. Any unknown owner is RECORD_AND_BLOCK; do not terminate it.
4. HARDWARE_READ_ONLY: only after its fresh admission, follow the sensing-only
   procedure. Preserve owner and zero-output evidence.
5. ZERO_MOTION_LOCALIZATION: only after a new hardware_read_only plus
   zero_motion_localization admission, run the frozen scan preflight,
   localization-only sequence, and finite subscriber-only diagnostic capture.
   Keep every motion-capable ingress disabled.
6. REAL_MOTION: remains a separate future stage. It requires a new three-class
   admission for one exact trial, a clear physical envelope, and an on-site
   observer at the physical main switch/e-stop. No earlier PASS carries into
   this stage.

At every boundary, a missing value, stale evidence, owner mismatch, expired or
reused grant, unexpected process, or physical-boundary failure returns to
BLOCKED.

## 3. Integrated software blockers are closed; field execution is not ready

Integrated software topology and install-layout blockers are closed by exact,
fail-closed contracts. This is a software disposition only and is not an
authorization to combine or start either runner on a real machine.

### ROS1_TOPOLOGY_VERIFIER_NODE_NAME_COLLISION: CLOSED

The zero-stage monitor now owns the canonical node
/verify_ros1_base_zero_stage_topology and the isolated readiness topic
/cleanup/base/zero_stage_topology_ready. The production PRE_CORE and
continuous monitors own /verify_ros1_base_bridge_topology and the navigation
readiness topic /cleanup/navigation/ros1_topology_ready.

The fix is more than a rename. The phase-aware topology policy permits the
zero-stage monitor to observe the exact transition in which the canonical
production peer joins, while production requires the canonical zero-stage
peer. A missing peer, rogue peer, wrong role, wrong node name, or READY-topic
substitution fails closed. This prevents same-name eviction without weakening
subscriber ownership.

### INSTALLED_RUNNER_WORKSPACE_SCRIPT_PATH_MISSING: CLOSED

The production runner no longer derives or guesses a repository-root script
path. PRE_CORE calls the package-owned installed entry exactly as:

    ros2 run limo_cleanup_base zero_stage_handoff_verifier

The ROS2 package setup declares that console entry and installs the verifier
module. Missing package/entry, nonzero execution, or a result without the
exact PASS marker blocks before the integrated core or adapter is started.
The package runbook V1_INTEGRATED_VERIFIER_INSTALL_ROLLBACK.md defines the
rollback for an installed-layout failure.

The two runners also do not form a verified single supervised entry: the
zero-stage runner owns the external safety chain, while the bridged-navigation
runner assumes that chain already exists and explicitly does not own it.
Stopping the bridged-navigation runner is therefore not proof that the driver
or safety chain stopped.

## 4. Required session evidence before any future field step

Create a copy of
docs/examples/v1_field_session_record_template.json as a new timestamped
record. Never edit the template in place and never overwrite an earlier
record. Bind every path below to a SHA-256:

- frozen release/readiness report;
- current package, map, image, AMCL, profile, and mode-specific bridge release
  artifacts;
- direct approval reference and the authorization admission record;
- boot ID, session ID, robot ID, operator, and physical-stop observer;
- process list, ROS1 graph, ROS2 graph, serial-owner snapshot, and device
  identity;
- exact launch logs and PID/ownership ledger for processes started by this
  session;
- preflight output and required PASS marker;
- subscriber-only diagnostic JSONL and derived reports;
- rollback outcome, UART-owner evidence, final physical state, and unresolved
  owners.

Unknown, blank, unhashed, overwritten, or cross-session evidence is a BLOCKED
result.

## 5. Diagnostic evidence matrix

| Question | Required evidence | What does not prove it |
|---|---|---|
| Who owns the process or port? | process snapshot, exact PID/start time, ROS graph, serial-owner output | a topic message or launch intent |
| Is scan/odom/TF/map valid? | frozen runtime preflight output plus map/profile hashes | AMCL covariance alone |
| Did AMCL converge? | explicit initial-pose record, manager status, covariance/stability window, bounded no-motion counts | a visually small particle cloud |
| Is absolute localization accurate? | surveyed truth in the map frame plus stationary AMCL evidence | READY, covariance, or repeatability |
| Is repeated localization stable? | separately classified fixed-mark samples and provenance | absolute localization evidence |
| Is the controller endpoint accurate? | requested endpoint minus final AMCL pose | physical truth alone |
| Is the physical endpoint accurate? | requested endpoint minus independent physical truth | controller success or covariance |
| Did avoidance work? | authorized motion-era rosbag with full scan geometry, sole driver-command evidence, contact and clearance evidence | subscriber-only zero-motion JSONL |
| Did rollback reach a safe boundary? | known-owner shutdown log, continuous-zero proof, driver exit, UART release, and final physical observation | cancel, a single zero sample, or process exit alone |

v1_diagnostic_capture.py is finite-duration and subscriber-only. It creates a
new exclusive JSONL file in an existing absolute output directory. It does
not prove process ownership, serial ownership, individual no-motion service
latency, full scan ranges, the sole driver command, obstacle response, or
physical position. Those claims require the separate evidence named above.

Recommended diagnostic classifications are:

- AUTH_BLOCKED: grant, identity, expiry, scope, or physical boundary invalid;
- OWNER_BLOCKED: unknown or duplicate process/topic/device owner;
- MAP_BLOCKED: map identity, path, image, or hash mismatch;
- CHAIN_BLOCKED: scan, odom, TF, action owner, heartbeat, or freshness invalid;
- LOCALIZATION_BLOCKED: explicit pose missing, no-motion failures, covariance
  or stability window invalid, or READY lost;
- INTEGRATED_BLOCKED: integrated runtime preflight, exact owner, heartbeat,
  installed-entry execution, field admission, or physical boundary invalid;
- ROLLBACK_BLOCKED: continuous zero, driver exit, UART release, or final
  physical state cannot be proved.

## 6. Rollback state machine

Rollback is ordered and fail-closed:

    STOP_INGRESS -> VERIFY_ZERO -> STOP_NAV -> STOP_DRIVER
                 -> VERIFY_UART -> STOP_SAFETY

STOP_INGRESS
: Reject new high-level work and use only the documented stop/cancel surface
  of processes owned by the current session. Record unknown processes and
  enter BLOCKED; never guess ownership and never terminate an unknown process.

VERIFY_ZERO
: Prove the topology-validated sole driver command is continuously zero for
  the required window. A cancel result, READY loss, or one zero observation
  is insufficient. If zero cannot be proved, the on-site operator uses the
  physical main switch/e-stop and the session becomes ROLLBACK_BLOCKED.

STOP_NAV
: Stop only the known navigation/core/adapter processes recorded in the
  session PID ledger. Integrated mode must remember that its runner does not
  own the external zero-stage safety chain.

STOP_DRIVER
: Stop only the known driver process owned by the session. Do not dismantle
  the guard, watchdog, bridge monitor, or zero-output chain first.

VERIFY_UART
: Prove the driver exited and the UART/device has no owner. If the driver or
  an owner survives, enter retain_safety: keep the guard/watchdog/monitor
  chain alive, keep all ingress closed, use the physical isolation path, and
  record BLOCKED. Software zero or STOP never substitutes for physical energy
  isolation.

STOP_SAFETY
: Stop the known safety-chain processes only after driver exit and UART
  release are both proven. Record the final physical state and every remaining
  process/device owner.

Rollback must not use a broad process-name sweep. If a known process refuses
to exit, ownership becomes uncertain, or the driver survives, preserve the
safety chain and request on-site physical intervention rather than escalating
software termination.

## 7. Formal field acceptance remains independent and NOT_RUN

The session record keeps these decisions separate:

- zero-motion absolute localization error;
- within-run jitter and cross-relocalization repeatability;
- navigation control endpoint error;
- physical total endpoint error;
- cancel and independent driver-timeout behavior;
- static obstacle avoidance;
- dynamic obstacle avoidance;
- scan/odom/TF loss behavior.

No result implies another result. In particular:

- covariance READY is a convergence and chain-health gate, not an absolute
  position-accuracy claim;
- controller endpoint error is requested pose minus final AMCL estimate;
- AMCL estimation error is physical truth minus final AMCL estimate;
- physical total endpoint error is requested pose minus physical truth;
- endpoint success does not prove obstacle avoidance;
- offline software PASS does not prove any field item.

All formal field-acceptance entries remain NOT_RUN/template_only until raw
evidence from the exact authorized session is attached. delivery_ready remains
false until every required independent field decision passes and all
field/runtime blockers are closed.

### 7.1 User-observed facts are a separate evidence layer

`NOT_RUN/template_only` is the formal acceptance-gate state. It must not be
rewritten to hide a real user observation, and a user observation must not be
promoted to formal PASS without the frozen raw evidence and provenance.

The current local classification records the latest real-machine statements
as `USER_OBSERVED`, gate progress `PARTIAL`, formal acceptance
`NOT_ASSESSED`, and archive state `UNSEALED`. The separate machine-readable
increment is
`evidence/v1_field_observation_20260814/user_observed_partial.json`; its
companion audit is `docs/V1_USER_OBSERVED_FIELD_EVIDENCE_AUDIT.md`.

The observed PoseArray concentration, qualitative motion-time concentration,
and one reported successful Nav Goal close only their limited functional
questions. They do not close READY, `3/3` cold starts, 30-sample provenance,
navigation `5/5`, any endpoint threshold, cancel/timeout, avoidance, or
scan/odom/TF-loss stopping. The reported centimeter-level residual remains
numeric null and error-class `UNRESOLVED` until goal, final AMCL, and
independent physical truth are all preserved.

## 8. Current handoff

Offline deployment, diagnostics, rollback, and authorization evidence are now
prepared. The two integrated software blockers in section 3 are closed and
must remain covered by the authoritative Linux regression. Native and
integrated field execution still require a fresh, exact-scope real-machine
admission, real-machine preflight, and on-site physical safety conditions:
software-ready does not make integrated field execution ready. Until those
separate field gates pass, the correct state is idle, fail-closed, and
NO_AUTOSTART.
