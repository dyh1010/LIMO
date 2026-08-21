# Mechanical arm and gripper staged acceptance matrix

Status: offline preparation only. No item in this document authorizes opening
an actuator port or moving the arm or gripper. Software STOP is not a
safety-rated emergency stop and does not replace physical energy isolation.

## Release gates

| Stage | Allowed work | Required evidence | Pass rule | Current state |
|---|---|---|---|---|
| A0 source contract | Static review, fake clients, dry-run | Python 3.8 parse; unit tests; forbidden-call scan | No default vendor import/device open; hardware factories blocked | PASS LOCALLY FOR THE EXISTING FAKE-ONLY SURFACE; FINAL-TOOL BACKEND/PARSER/OWNER NOT PRESENT |
| A0-P protected safety latch | Pure-local filesystem contract and hostile-input tests only | exclusive/atomic issuance and update; non-rollback monotonic session identity; one-time clearance IDs; no-follow ordinary-file sidecars; crash/power-loss durability; protected authenticity | stale, replayed, forged, truncated or rolled-back records/credentials cannot clear a newer physical-isolation requirement | BLOCKED: LOCAL TESTS NOW FAIL CLOSED ON STALE SESSIONS, CLEARANCE-ID REPLAY, SINGLE-SIDED LEDGER/GENERATION TAMPER, COMMIT-UNCERTAIN PUBLICATION, SIDECAR HARDLINKS AND TESTED PATH/INODE SWAPS; HOSTILE STORE-DIRECTORY REPLACEMENT, COORDINATED FULL-STORE ROLLBACK, PROTECTED AUTHENTICITY AND POWER-LOSS DURABILITY REMAIN UNPROVEN, SO THIS CANNOT AUTHORIZE CONNECTION, MOTION OR A SOFTWARE STOP SUCCESS CLAIM |
| A1 ROS1/Noetic dry-run | Local isolated Catkin interfaces and fake-only arm/gripper adapters | source manifest; Catkin build/test logs; ROS-free callback log; isolated-master smoke, ownership and exact cleanup logs | Noetic interfaces and adapters exist; Action/STOP/ACK/state mappings pass; one owner per mechanism; backend is fake-only; zero hardware commands; no vendor overlay; cleanup is proven | BLOCKED: NO ARM/GRIPPER CATKIN INTERFACES OR `rospy`/`actionlib` ADAPTER EXISTS |
| A2 installed assembly, power isolated | Visual/static inspection and measurements | frozen revision, fasteners, mass/CoM/inertia, cable routing, energy-isolation diagram | all fields reviewed; gripper transport remains disconnected | BLOCKED |
| A3 arm read-only | Separately authorized read-only window only | device identity/sole owner, Transponder, finite fresh state, controller limits, frame/end/TCP readback | repeated legal samples; no motion/init/clear/power calls | BLOCKED / NOT PART OF OFFLINE RUN |
| A4 gripper read-only | Final-tool-specific passive protocol only | actuator/controller identity, electrical/protocol spec, sole transport owner, timestamped legal feedback | no `255`/magic invalid values; read cannot initialize or move | BLOCKED |
| A5-G first gripper motion | Requires a new gripper-specific, one-time user authorization | final tool frozen; arm fixed; cleared jaw envelope; one bounded no-load command; observer and logs | direction, current, opening and STOP evidence stay inside reviewed thresholds | PROHIBITED IN CURRENT TASK |
| A5-A first arm motion | Requires a separate arm-specific, one-time user authorization | final installed load/TCP frozen; cleared arm envelope; one bounded lowest-risk command; observer and logs | measured speed, stopping distance and final stationary evidence stay inside reviewed thresholds | PROHIBITED IN CURRENT TASK |

Stages must be completed in order. Failure or missing evidence at one stage
blocks all later stages without blocking unrelated offline engineering.
A5-G and A5-A are separate authorizations: approval for one never covers the
other, and neither approval may be reused for a later command or session.

For A0, fake timing alone is not backend deadline evidence. A real transport
cannot leave `DISABLED/BLOCKED` until its release package exactly binds the
runtime release, acceleration profile, approved speed-grade set and execution
safety artifact, and proves native bounded calls/cancellation plus an
independent STOP channel. A Python timeout thread or a STOP that shares the
normal-command adapter lock fails this gate. If that topology cannot be
proved, STOP must escalate to persistent physical-isolation-required and must
not be reported as software success.

The normative A1 runtime baseline is now ROS1/Noetic.  The current
`limo_cleanup_executor`, `limo_cleanup_interfaces`, launch files and generated
interfaces are ROS2/Foxy wrappers; the pure-Python cores, manifests and latches
are reuse candidates, but there is no arm/gripper Catkin package, `rospy` /
`actionlib` adapter, ROS1 launch/config or independent ROS1 STOP owner.  The
fail-closed implementation and future isolated-run checklist is
`docs/arm_gripper_ros1_noetic_dry_run_checklist.md`.  ROS2 source/callback tests
remain useful regression evidence only and are not Noetic compatibility or
field-entry evidence.

The one-and-only historical target Foxy v3 evidence is preserved under
`docs/evidence/arm_foxy_dryrun_20260813_v3`. The runner checked `ros2` before
sourcing the Foxy setup and exited with `status=2`; it never entered build,
test, launch-argument inspection or Action/STOP/ACK smoke. V3 is a recorded
failed ROS2 attempt, not the A1 Noetic gate, and must not be rerun or
reinterpreted as pending. Any future
isolated target build remains prohibited by the current permanent no-target,
no-SSH boundary. The preserved evidence proves its exact root and bundle were
cleaned, but it has no independent broad residual-process log; broad target
zero-residual status is therefore `UNKNOWN/BLOCKED` and must not be filled by
another connection.

Current evidence disposition is intentionally narrow:

| Evidence area | Current disposition | What must not be inferred |
|---|---|---|
| Local static and pure-fake contracts | PASS only for the tested in-memory/source surface | no ROS1/Noetic or ROS2/Foxy runtime, vendor transport, actuator or physical STOP evidence |
| ROS1/Noetic arm/gripper integration | `BLOCKED_NO_ROS1_ARM_GRIPPER_ADAPTER`; build/test/smoke `NOT RUN` | ROS2 types, launch files, callback fixtures or Foxy evidence do not prove Catkin, `rospy`, `actionlib`, ROS1 ownership or shutdown semantics |
| Historical Foxy v3 attempt | `FAIL-before-build (status=2)`; build/test/smoke `NOT RUN` | no package build, `colcon test`, in-memory ROS smoke, Noetic compatibility or cleanup-wide zero-residual claim |
| ROS runtime/graph in the current task | `SKIPPED/BLOCKED` by the permanent local-only boundary | source-level callback tests are not a running ROS graph |
| Real arm/gripper backends and transport owners | `DISABLED/BLOCKED` | a fake deadline, Python timeout thread or shared adapter lock is not native cancellation or an independent STOP channel |
| Software STOP, stationary proof and physical isolation | `BLOCKED` for hardware | a STOP return or fake stationary samples are not physical standstill, emergency stop or zero-energy proof |
| Persistent physical-isolation latch | `BLOCKED` pending protected storage and independent supervision | local tests cover clearance-ID replay, stale sessions, ledger-only/generation-chain tamper, commit-outcome ambiguity, hardlinks and tested same-bytes inode swaps; local hashes still do not provide operator authenticity, rollback-proof monotonic state or power-loss durability, and hostile parent/store-directory replacement or privileged coordinated replacement of the complete valid store remains a release blocker |
| A2 and all read-only/energized/field stages | `BLOCKED`; motion stages are prohibited in this task | no blank, `TBD`, historical or estimated field may be treated as accepted |

## Machine-readable stage-entry contract

The frozen local matrix is
`src/limo_cleanup_executor/config/arm_gripper_field_acceptance_matrix.json`.
It is evaluated by the ROS- and vendor-independent
`arm_gripper_field_acceptance.py` verifier.  This is an entry-precondition
contract, not an actuator command, a physical safety function or proof that a
stage was completed.

The matrix is not its own authority.  Every evaluation requires a
caller-owned exact boundary mode and SHA-256 of the complete matrix.  Under
the current `PERMANENT_LOCAL_ONLY` trusted boundary, every A2--A5 field record
is rejected before any field authority, release, transport, latch, physical
isolation, evidence or authorization-consumption callback can run.  Editing a
candidate JSON document to say `FIELD_AUTHORIZED_POLICY` cannot supersede that
trusted boundary.

The verifier now has a third, distinct boundary:
`ROS1_NOETIC_FAKE_ONLY`.  It permits only an isolated ROS graph and requires
SSH, target, device, vendor runtime, real Action/Service, hardware connection,
field activity and motion permissions to remain exact false.  A1 may be
`ELIGIBLE` only in that boundary and only after its structured prerequisite and
required-evidence validators return exact `True`.  The current frozen matrix
remains `PERMANENT_LOCAL_ONLY`, so A1 remains
`BLOCKED_NO_ROS1_ARM_GRIPPER_ADAPTER`.

`FIELD_AUTHORIZED_POLICY` cannot execute A1.  It may reference A1 as
`PASS_LOCAL` only as a prior Noetic fake-only completion whose exact result is
validated as prerequisite evidence.  An eligible field stage is rejected at
matrix validation when any offline prerequisite, including A1, is still
blocked; an unconditional prerequisite callback cannot repair that state.
FIELD stages must never use `PASS_LOCAL`: their admissible policy states are
`BLOCKED`, `ELIGIBLE`, or `PROHIBITED`, with execution enabled only for
`ELIGIBLE`.

A future field-policy release, if separately authorized outside this task,
must satisfy all of the following machine-readable gates:

- `external_authority` is the exact JSON boolean `true`, and the injected
  policy and one-time-authorization validators each return the singleton
  Python value `True`; truthy integers or objects do not pass;
- the authorization binds one stage, session and operation ID, has exact
  `one_time=true` and native-integer `max_uses=1`, and is inside a strict UTC
  not-before/expiry window;
- a recomputed scope digest binds the trusted policy, stage, operation,
  session, optional command, exact runtime release and profile, selected speed
  grade, transport evidence, latch snapshot and physical-isolation evidence;
- ARM and GRIPPER release/profile bindings remain separate, and A5-A and
  A5-G are sibling stages with distinct scopes rather than prerequisites or
  interchangeable approvals;
- the transport declaration forbids Python timeout-thread substitution and
  requires native bounded calls/deadlines/cancel, a STOP channel and lock
  domain independent from normal commands, STOP not queued behind them, and a
  hung-send report proving STOP completed before the send was released;
- A3, A4 and both A5 stages bind a current `CLEAR` persistent-latch snapshot
  to the same release/profile, plus protected external-authority evidence;
- release, transport, persistent-latch, physical-isolation, prerequisite and
  stage evidence are not accepted from self-declared booleans or hashes: each
  bound authority callback must return exact `True`; and
- the one-time authorization is admitted only when an injected persistent
  consumer atomically validates and consumes the complete frozen record.

Even a fully valid future record only states that software entry preconditions
were satisfied.  It cannot replace the observer, physical E-stop, energy
isolation, cleared envelope, final stationary evidence or post-stage evidence
record required below.

## Arm values that must be measured or frozen

| Item | Required artifact / measurement | Acceptance rule |
|---|---|---|
| Joint limits J1..J6 | controller min/max plus collision-reviewed project min/max | project interval is a strict subset of controller interval; no generic brochure values |
| Speed grades | commanded grade, measured joint deg/s, TCP mm/s and repeatability | approved maximum is tied to a versioned profile ID |
| Acceleration | measured ramp/transient for each approved speed/pose/load case, bound to the frozen runtime release and acceleration-profile artifact | no real policy unless `runtime_release_id`, `release_manifest_sha256`, `acceleration_profile_manifest_sha256` and `acceleration_profile_runtime_release_id` agree exactly with the runtime policy |
| STOP behavior | request timestamp, last motion timestamp, stopping distance, final multi-sample joint stability, per-call deadline evidence and a hung-motion-send probe | software STOP return alone never passes; `bounded_call_capability.enforced=true` and `independent_stop_channel_capability.enforced=true` must be bound to reviewed artifacts proving STOP has an independent execution/lock domain and is not blocked by a hung motion call; timeout escalates to physical response |
| TCP | `arm_flange -> gripper_tcp` 6D transform, tool revision, uncertainty | controller end type/tool reference and project transform agree |
| Base extrinsic | `base_link -> arm_base` measured transform and uncertainty | reviewed independent measurements; no photo/zero placeholder |
| Named poses | six joint values, tool revision, collision result, cable envelope and purpose | all values inside reviewed project limits; arbitrary targets remain unavailable |
| Path modes | moveJ/moveL trajectory and failure observations | each allowed mode separately reviewed; no automatic fallback |
| Error recovery | fault code, cause, stationary evidence, human authorization and post-ACK samples | ACK clears only local latch; never auto power/enable/clear/resume |

## Gripper values that must be measured or frozen

| Item | Required artifact / measurement | Acceptance rule |
|---|---|---|
| Opening calibration | native command/feedback versus measured clear jaw opening across the approved range | direction and nonlinear table are measured; hysteresis, repeatability and uncertainty are recorded |
| Grip force/current | calibrated jaw force and supply/motor current versus command, opening, temperature and approved bottle | maximum command/current/force limits are versioned; stall or force saturation cannot be treated as grasp success |
| Bottle deformation | change in bottle diameter or wall displacement at the approved grasp band, plus buckle/crack/leak observations | numeric millimetre and percentage limits remain `TBD_MEASURED`; buckle, crack, puncture or leak count must be zero |
| Hold and release | hold duration, slip distance/rate and residual contact after open | numeric limits remain `TBD_MEASURED`; position feedback alone cannot pass grasp or release |
| Thermal duty | motor/controller temperature and current over the approved cycle count and dwell | temperature, duty-cycle and cool-down limits are taken from reviewed data or measurement, never guessed |

## Final gripper selection and protocol freeze

The current project gate is `COMPLETE_REPLACEMENT_ONLY`. In the existing
`final_gripper_release_manifest` schema this is encoded by the exact internal
value `tool_architecture=COMPLETE_REPLACEMENT`, with complete replacement true,
legacy AG components retained false and the AG retention-map hash null. This
does not approve a particular replacement tool; it only prevents the retired AG
path or its parameters from entering this release package.

The two conceptual paths remain documented below, but only path 2 is available
to the current machine-readable release gate. Path 1 requires a separate,
not-yet-implemented AG-specific schema/backend and therefore stays blocked:

1. Original AG retained: provide a frozen BOM/section view proving the original
   actuator, Atom/control chain and wiring are retained. Only then may the
   legacy API be reconsidered. Historical `get_gripper_value(1) == 255` is
   INVALID/DISCONNECTED, never open.
2. Complete replacement gripper: provide a dedicated controller and transport
   that are independent of the arm's `/dev/elephant` owner. Do not inherit
   `gripper_type=1`, `0..100`, direction, calibration, torque/current values or
   any AG method name.

Do not represent path 1 by editing replacement-manifest booleans or weakening
its denylist. A future Original-AG package must independently encode the
retention map, shared transport ownership, exact reviewed protocol and all
non-inherited limits; until then the project selection remains
`COMPLETE_REPLACEMENT_ONLY` and the manifest's exact architecture value remains
`COMPLETE_REPLACEMENT`.

Required freeze package:

- unique tool and assembly revision; BOM and AG-retained/replaced mapping;
- actuator, gearbox, controller and firmware part numbers;
- nominal/peak/stall voltage and current, supply, fuse/current limit, grounding;
- connector and pinout, polarity, signal levels, baud/bitrate/frame format;
- address/register/opcode map, byte order, checksum/CRC, units, ACK/NAK,
  sequence/command-ID and duplicate/replay handling;
- power-on default, watchdog, communication timeout and disconnect-safe state;
- timestamped state schema with explicit validity, position/opening, moving,
  limits, current/force/temperature if supported, and complete invalid/fault
  dictionary;
- raw-to-opening calibration method and nonlinear table; no assumed range;
- mass, center of mass, inertia, jaw axis/limits and swept collision envelope;
- `arm_flange -> gripper_mount -> gripper_tcp` measurements, including opening
  dependence when the jaw contact center moves;
- contact-pad material/compliance/retention, reachable pinch/shear/crush and
  sharp-edge/entanglement controls;
- brake/self-locking/back-drivability, loss-of-power retained-load/drop behavior
  and any secondary retention or exclusion-zone requirement;
- rated cycle life/duty, gear/bearing load and wear limits, lubrication,
  fastener locking/torque marks, inspection intervals and replacement criteria;
- finite positive deadlines and cancellation/bounded-abandonment semantics for
  every final-backend method (`read_state`, `command_position`, `stop`,
  `close`), with a pure-fake hung-command test report;
- an independent STOP executor and lock domain; STOP must not queue behind a
  normal command and a missed STOP deadline must fail closed;
- one transport owner and an auditable STOP/fault/ACK contract.
- a field-by-field feedback support matrix aligned to `GripperState`, including
  timestamps/sequence, invalid values, fault dictionary, restart semantics and
  exact supported Action target kinds.

For either selected gripper path, a generic evidence PDF is not sufficient to
bind every safety claim. Every declared non-derived SHA-256 value must equal a
digest recomputed from an ordinary file below the explicitly selected artifact
or CAD root. Missing roots, fabricated files, hash-only declarations and
undeclared CAD files fail closed.

This field matrix is a staged acceptance summary. The normative detailed input
and measurement inventory is
`docs/final_gripper_release_input_checklist.md`; any field present there but
not expanded here remains required and fail-closed.

Current CAD revision warning (2026-08-14): the unique `.SLDASM` assembly under
`C:\Users\DYH\Desktop\v1gripper` is no longer the archived
2026-08-11 revision. The archived inventory records 2,094,719 bytes and SHA-256
`01F5DD433030E86D47A06104C8489D3C24131236CFF79125D5A6EBF43B5AB5AC`;
the current file is 2,035,041 bytes and SHA-256
`D5F513C69B3590378791CFEC8E0853567F8377676429772ED7E38D1653E94D98`.
The current directory contains 35 files: 1 SLDASM, 33 SLDPRT and 1
`Macro1.swp`, totalling 8,058,955 bytes; all 35 file hashes are unique.
`Macro1.swp` is tooling, not geometry, mass, protocol or collision evidence.
The directory contains no STEP/Parasolid neutral assembly, controlled drawing,
PDF, BOM, actuator/controller datasheet, protocol manual or electrical
specification.
It must be exported, reviewed and frozen again before geometry, mass, TCP or
collision evidence can be inherited. The CAD directory contains no controller
code or protocol specification.

Current replacement-CAD closure matrix:

| Unknown / missing evidence | Required controlled material or measurement | Current state |
|---|---|---|
| Product/tool identity and installed configuration | tool model/revision/serial, immutable BOM, labels and zero-unexplained-part reconciliation | `UNKNOWN/BLOCKED` |
| Neutral assembly and assembly semantics | frozen AP242 STEP or Parasolid with open/mid/closed configurations; readable assembly tree, instances, mates and configuration | `MISSING/BLOCKED` |
| AG retain/remove mapping | signed architecture decision and a field-by-field AG/Atom retain/remove/replace map; current replacement package must retain none | `COMPLETE_REPLACEMENT_ONLY`; Original AG package `NOT IMPLEMENTED/BLOCKED` |
| Arm flange and adapter interface | controlled arm/tool drawings plus three independently re-fixtured measurements of hole positions/PCD, locating features, mounting face, adapter thickness, engagement, anti-rotation and cable exit | `UNKNOWN/BLOCKED` |
| Joint model and mechanism | active/passive joints, axes, gear ratio, linkage/mimic relation, hard/soft limits, backlash and safe open/mid/closed configurations | `UNKNOWN/BLOCKED` |
| Units and mesh/link ownership | confirmed source/export unit and scale; every retained component assigned to a rigid link or explicitly excluded | `UNVERIFIED/BLOCKED` |
| Visual/collision/sweep evidence | separate reviewed visual and simplified collision meshes per rigid link; open/mid/closed plus full mechanism/cable sweep | staging copies only; release `BLOCKED` |
| Mass, CoM, inertia and load | material/density coverage, per-link and full-tool six-term inertia; at least three zeroed mass readings and three independent CoM fixture orientations; installed tool/cable/object load review | `UNKNOWN/BLOCKED` |
| Mount and TCP | three independent 6D measurements for `arm_flange -> gripper_mount -> gripper_tcp`, uncertainty, contact depth and opening-dependent TCP disposition | `UNKNOWN/BLOCKED` |
| Opening/contact geometry | approved bottle/contact band, static clear opening where safely measurable, contact-pad material/compliance/retention and pinch/shear/crush/sharp-edge review | `UNKNOWN/BLOCKED`; energized calibration deferred |
| Actuator/controller/electrical identity | exact part/revision/firmware, voltage and idle/start/rated/peak/stall current, protection, connector/pinout, grounding and power-loss behavior | `MISSING/BLOCKED`; no numeric guess allowed |
| Protocol, feedback and STOP | transport/electrical levels, complete frame/register/CRC/ACK/sequence/replay rules, feedback/fault dictionary, watchdog/disconnect state and independent gripper STOP channel | `MISSING/BLOCKED`; generic arm STOP is not evidence |
| Durability and maintenance | rated life/duty, gear/bearing load basis, wear/backlash/lubrication limits, fastener locking, inspection interval and replacement criteria | `MISSING/BLOCKED` |

All de-energized measurements above require an approved static procedure,
calibrated instruments, raw readings, uncertainty and reviewer. Any item that
cannot be obtained without connection, power or motion remains
`FIELD_BLOCKED_REQUIRES_SEPARATE_AUTHORIZATION`; this matrix does not authorize
performing it.

Values from the prior generated ROS assets are not hardware evidence. In
particular `gripper_torque: 500`, `protect_current: 200`, native pymycobot
claims, calibration calls and assumed 0/100 direction are forbidden defaults;
their source and units were not proven.

## On-site staged power checklist

Checking a box records a separately authorized field action; this document does
not itself authorize connection, energization or motion. Software STOP never
replaces the physical emergency response or energy isolation.

### A2 de-energized/static inspection

- [ ] Record the physical isolation/lockout method and independently verify the
  applicable electrical, pneumatic, spring/gravity and stored-energy state; a
  software state or STOP return is not zero-energy evidence.
- [ ] Reconcile tool, actuator, controller, adapter, fasteners, cable, labels,
  serials and installed options to the frozen BOM/CAD/protocol revisions.
- [ ] Record calibrated instruments, calibration expiry, datum, three
  independent setups where required, raw readings, uncertainty and reviewer.
- [ ] Inspect fastener locking/torque marks, bearing/gear retention, guards,
  contact-pad retention, visible wear/cracks/corrosion/contamination and
  lubricant leakage without disturbing or manually back-driving the mechanism.
- [ ] Inspect reachable pinch/shear/crush/entanglement points, burrs/sharp edges,
  connector retention, strain relief, cable bend radius and static envelope.
- [ ] Verify point-to-point unpowered wiring, polarity/keying, protective and
  signal grounding, fuse/current-limit identity, insulation condition and
  absence of shorts using only the reviewed static procedure.
- [ ] Confirm that passive power-loss/back-drive/retained-load behavior is
  supported by controlled evidence. Do not suspend a load, force the jaws or
  infer holding safety from static position; dynamic proof remains field-blocked.
- [ ] Complete mass/CoM/inertia, flange/TCP, opening/contact geometry and
  collision-envelope records from the final installed revision, or mark each
  unavailable item explicitly blocked.

### Before connection or energization

- [ ] Record the authorization ID, exact scope, expiry, safety lead, operator
  and observer; confirm whether the window is static, read-only, A5-G or A5-A.
- [ ] Barricade and clear the applicable envelope; mechanically fix the robot
  base and keep the arm in a reviewed stationary condition for gripper work.
- [ ] Identify, reach and separately test the physical E-stop/energy-isolation
  path; record which hazardous energy sources it does and does not remove.
- [ ] Match arm, tool, adapter, fasteners, cables, serial numbers, BOM and CAD
  hash to the frozen revision.
- [ ] Review supply voltage, current limit, fuse, protective earth/ground,
  polarity, conductor size, connector retention and strain relief.
- [ ] Review load, CoM, inertia, TCP, collision envelope, named poses, force,
  current and bottle-deformation limits; no `TBD` field may enter motion.
- [ ] Record source/configuration hashes and evidence directory; snapshot
  processes, ROS endpoints and transport owners before the session.
- [ ] Prove there is one intended owner per transport and no vendor follow,
  teleop, JOG, free-mode, port scan or fallback process.

### Power-up and read-only observation

- [ ] Start with all relevant energy isolated, supply output off and actuator
  torque/enable disabled; connect only the reviewed controller and wiring.
- [ ] Set and independently verify the reviewed voltage/current limit and fuse;
  place the observer at the physical stop before energization.
- [ ] If the design supports separate logic power, energize controller logic
  first while actuator power remains isolated; record inrush and idle current.
- [ ] Confirm zero unexpected motion, sound, heating or current excursion. Any
  anomaly requires immediate physical isolation and ends the stage.
- [ ] Perform only the approved passive identity/status reads. Do not call
  initialization, calibration, homing, clear-error, open, close or motion APIs.
- [ ] Verify timestamp, sequence, validity, position/opening, moving, limit,
  current/force/temperature and fault fields against the frozen protocol.
- [ ] Stop after the read-only gate. Enabling actuator energy requires the
  separate A5-G or A5-A authorization for that exact session and command.

### Power-down and final safe state

- [ ] Withdraw command authorization and prevent new goals; use software STOP
  only as a supplementary action when its reviewed semantics apply.
- [ ] Use the approved physical isolation sequence to remove actuator energy,
  then controller energy; do not infer safe state from an API return.
- [ ] Verify stationary mechanics and measure/confirm residual voltage and
  current below reviewed thresholds before touching or disconnecting wiring.
- [ ] Close the transport, release its owner/lock and confirm that no new test
  process, node, endpoint or device owner remains relative to the baseline.
- [ ] Record final controller/actuator energy state, anomalies and physical
  isolation confirmation, with operator, observer and safety-lead signatures.

Automatic `power_on`, servo focus/release, calibration, clear-error, resume,
retry, regrasp and repeated open/close remain forbidden. Any unexpected motion,
invalid/old feedback, unknown owner, error code, timeout, cable pull or limit
discrepancy ends the stage and requires physical safe handling before software
investigation.

## Required negative acceptance matrix

Run these cases first in a fake/simulation harness. A hardware repetition is
allowed only when the frozen protocol makes the injection non-moving and a
separate field authorization covers it.

| Case | Injected condition | Required fail-closed result | Required evidence | Current state |
|---|---|---|---|---|
| Watchdog loss | suppress heartbeat/state beyond the reviewed timeout | reject new commands; latch fault; enter reviewed disconnect-safe state | timestamps, timeout value, state transition and physical/output observation | CORE STALE/READ-FAIL PATH PASS; PROTOCOL WATCHDOG FIELD BLOCKED |
| CRC/framing error | bad CRC/checksum, length or framing | discard sample; never update valid state or retry a motion command | raw frame, parser result and unchanged command count | BLOCKED: FINAL PROTOCOL/PARSER NOT SELECTED |
| Stale sample | legal payload with expired timestamp | mark invalid and block motion/ACK | source and receive timestamps plus age calculation | OFFLINE PASS: FRESHNESS/HIGH-WATER GATES |
| Duplicate frame/command | repeat sequence or command ID | no duplicate physical command and no extra stationary sample credit | IDs, command count and state sequence | OFFLINE PASS: SEQUENCE/AUTH/COMMAND-ID REPLAY GATES |
| Out-of-order frame | deliver a lower/older sequence after a newer sample | reject regression and preserve the newer state | ordered raw log and gateway state | OFFLINE PASS: HIGH-WATER SNAPSHOT PRESERVED |
| Controller restart | reset session/boot counter during READY or FAULT | invalidate prior session/authorization and require a new readiness review | boot/session IDs and rejected stale request | PURE-FAKE CORE PASS: BOOT-ID DRIFT PERMANENTLY LOCKS THE PROCESS AND OLD SESSION-BOUND AUTHORIZATION IS REJECTED; ROS GATEWAY, FINAL BACKEND AND PASSIVE OWNER/BOOT READBACK FIELD EVIDENCE BLOCKED |
| Power loss/disconnect | remove controller or actuator power/transport in an approved safe fixture | latch fault, issue no automatic init/resume/retry and require physical review | supply/transport timeline, state and command count | CORE DISCONNECT/READ-FAIL PASS; PHYSICAL POWER-LOSS FIELD BLOCKED |
| STOP failure/timeout | STOP raises, is unacknowledged, or stationary evidence misses timeout | latch non-clearable motion uncertainty; escalate to physical response | STOP call/result, timeout, moving/joint samples and final isolation | OFFLINE CORE PASS; REAL STOP/ISOLATION FIELD BLOCKED |
| Hung command and late return | block a pure-fake motion send while STOP, close or a newer fault advances the state epoch | safety interrupt does not wait for the ordinary command path; the late call cannot commit success, revive motion or overwrite the newer STOP/close/fault state | thread barriers, epoch/generation before and after, final state and command count | PURE-FAKE CORE PASS FOR ARM AND GRIPPER; REAL TRANSPORT REMAINS BLOCKED UNTIL NATIVE DEADLINES/CANCELLATION AND AN INDEPENDENT STOP CHANNEL ARE PROVEN |
| ACK race | ACK arrives before stationary proof, with stale session, or while STOP is unresolved | reject ACK; never report the interrupted action as success | session/auth IDs, state sequence and action result | PURE-FAKE CORE AND ROS-CALLBACK CONTRACT PASS; ROS SOURCE IS SIMULATION-ONLY AND NO ROS RUNTIME/GRAPH OR HARDWARE TRANSPORT WAS RUN |
| Invalid feedback | `255`, non-finite, out-of-range, unknown enum or impossible limit combination | mark INVALID and block motion without clamping | raw value and validation error | OFFLINE PASS FOR LEGACY 255, EXACT TYPES AND NORMALIZED POSITION; LIMIT-COMBINATION AND FINAL PROTOCOL BLOCKED |
| Identity/revision drift | change tool/controller/transport identity, firmware revision or controller boot ID during READY/FAULT | invalidate readiness, session and authorizations; send no command until the complete identity package is reviewed again | before/after identities, revisions, boot ID, rejected request and zero command count | PURE-FAKE CORE PASS: EXACT REVIEWED TOOL/REVISION/CONTROLLER/TRANSPORT/PROTOCOL IDENTITY AND BOOT-ID ARE REQUIRED; INVALID OR DRIFTED IDENTITY PERMANENTLY LOCKS THE PROCESS, AND ACTIVE DRIFT ATTEMPTS STOP ONCE THEN REQUIRES PHYSICAL HANDLING; ROS GATEWAY, FINAL BACKEND, EXPLICIT FIRMWARE-REVISION FIELD AND PASSIVE OWNER/IDENTITY FIELD EVIDENCE BLOCKED |
| Owner change | transport owner changes or a second endpoint appears | revoke readiness and send no new command | before/during/after owner and endpoint snapshots | BLOCKED: NO RELEASED TRANSPORT OWNER MONITOR |
| Persistent-latch restart/tamper | restart after ACTIVE/CLEAR, replay a clearance ID, truncate or roll back one ledger/generation component, inject a publication failure, hardlink a sidecar, or swap a same-bytes inode between metadata check and open | old sessions cannot clear; replay is rejected; incomplete or inconsistent publication remains `COMMIT_UNCERTAIN/BLOCKED`; linked or identity-swapped files are rejected; no tentative CLEAR is exposed after an exception | canonical record/ledger or generation chain, pending marker, path/open inode and link-count evidence, session epochs/nonces, clearance registry and reopen result | PURE-LOCAL PASS FOR TESTED STALE-SESSION, REPLAY, SINGLE-COMPONENT TAMPER, HARDLINK/PATH-INODE AND POST-PUBLICATION FAILURE CASES; HOSTILE STORE-ROOT REPLACEMENT, PRIVILEGED FULL-STORE ROLLBACK, SIGNED AUTHORITY, PROTECTED STORAGE AND POWER-LOSS DURABILITY BLOCKED |

## Required field evidence record

Every A2 or later session must fill all applicable fields; blank fields mean
the stage did not pass.

| Field | Recorded value |
|---|---|
| Date, start/end time and site | |
| Safety lead / operator / observer names and signatures | |
| Authorization ID, scope, issue time and expiry | |
| Arm, gripper, controller and firmware serial/revision | |
| BOM, protocol and CAD revision; assembly SHA-256 | |
| Source revision/tree hash and configuration SHA-256 | |
| Evidence/log directory and immutable archive hash | |
| ROS1 master URI/isolated namespace, gateway session/boot ID and command/action IDs | |
| Supply voltage/current limits, measured inrush/idle/peak and temperatures | |
| Transport identity and owner before/during/after | |
| Instrument IDs, calibration expiry, datums, raw static readings and uncertainty | |
| Physical isolation/zero-energy method and stored-energy disposition | |
| Fastener/retention/guard/contact surface/wear/lubrication static inspection | |
| Passive power-loss/back-drive/drop-hazard evidence and restrictions | |
| Maintenance interval, life/cycle counter and safety-relevant replacement state | |
| Approved opening, force/current and bottle-deformation thresholds | |
| STOP/stationary/ACK evidence and negative-case results | |
| Deviations, anomalies and disposition | |
| Final actuator/controller energy state and residual voltage/current | |
| Final process/node/endpoint/owner cleanup result | |
| Physical isolation confirmation and final signatures | |
