# Final gripper release input checklist

Status: `FAIL_CLOSED_UNTIL_ALL_REQUIRED_INPUTS_ARE_REVIEWED`

Current metadata-only CAD inventory snapshot: 35 primary files totalling
8,073,617 bytes: 33 SLDPRT files (6,017,584 bytes), 1 SLDASM
(2,035,041 bytes) and `Macro1.swp` (20,992 bytes). There are no
subdirectories. SolidWorks currently holds all 34 SLDPRT/SLDASM files open and
has created 34 hidden four-byte `~$...` owner/lock sidecars. Consequently the
34 CAD payload hashes could not be refreshed without bypassing another
process's file lock, which this audit did not attempt.

The previous 8,058,955-byte snapshot and its hash set are now stale. In
particular, `后板.SLDPRT` and `上盖板.SLDPRT` have 2026-08-14 modification
timestamps, and the primary-file byte total has increased by 14,662 bytes.
The previously recorded `齿轮箱.SLDASM` SHA-256
`D5F513C69B3590378791CFEC8E0853567F8377676429772ED7E38D1653E94D98`
is retained only as historical evidence and is not a current release binding
until all CAD files are closed, rehashed and frozen as one controlled
snapshot. `Macro1.swp` is tooling, not geometry, mass or collision evidence.

The current directory contains no STEP/Parasolid neutral assembly, PDF,
controlled drawing, BOM, actuator/controller datasheet, protocol manual or
electrical specification. Part names identify bearings, fasteners, a generic
`舵机`, gears, links, fingers and plates, so they support classification as a
complete replacement gripper candidate only. They do not prove a product
model, installed configuration, material, mass, kinematics or control path.

This checklist turns the remaining final-tool unknowns into explicit supplier
documents or de-energized measurements. It does not authorize connection,
power, enable, calibration, homing or motion. Historical AG values and servo
guesses are not substitutes for evidence.

## Evidence record convention

Every row in the matrices below must be closed with all of these fields. A
checkbox without an evidence record does not pass the release gate.

| Field | Required content |
|---|---|
| Evidence ID | Stable identifier unique to this tool revision |
| Source | Supplier/manufacturer, controlled CAD revision or measurement owner |
| Artifact | Document title/part number/revision/hash, or raw measurement log |
| Method | Datasheet review or de-energized instrument/fixture procedure |
| Result | Value, units, tolerance/uncertainty and explicit pass/fail |
| Reviewer | Name, review timestamp and disposition |
| Applicability | Tool, actuator/controller and assembly serial/revision |

Allowed evidence methods in this checklist are `CONTROLLED_DOCUMENT` and
`DE_ENERGIZED_STATIC_MEASUREMENT`. If an item needs power, communication,
enable or motion, mark it `FIELD_BLOCKED_REQUIRES_SEPARATE_AUTHORIZATION`; do
not attempt to close it during static inspection.

## Machine-readable safety sections

Schema version `4` adds exact backend runtime/motion-profile binding to the
machine-readable safety sections and keeps this
manifest explicitly replacement-only. These section and
field names are exact; aliases and additional keys are rejected. `null`, an
unaccepted review, a missing local artifact, a mismatched hash, or a `false`
required pass assertion keeps release blocked.

| Section | Exact controlled fields |
|---|---|
| `passive_power_loss_safety` | `backdrivability`, `brake`, `self_locking`, `loss_of_power_jaw_behavior`, `object_drop_hazard`, `secondary_retention_or_exclusion`, `loss_of_power_hazard_analysis_sha256`, `passive_safety_static_inspection_sha256`, `controlled_review_passed`, `review` |
| `contact_human_safety` | `pad_material`, `pad_compliance`, `pad_retention`, `allowable_contact_pressure`, `cleaning_and_chemical_compatibility`, `pinch_hazard_review_passed`, `shear_hazard_review_passed`, `crush_hazard_review_passed`, `entanglement_hazard_review_passed`, `sharp_edge_guarding_review_passed`, `contact_interface_specification_sha256`, `hazard_guarding_inspection_sha256`, `review` |
| `durability_maintenance` | `rated_cycle_life_cycles`, `rated_duty_cycle`, `gear_bearing_load_life_basis`, `wear_limit_specification`, `backlash_limit_specification`, `lubrication_specification`, `fastener_locking_and_torque_mark_policy`, `inspection_interval`, `replacement_criteria`, `approved_spares_revision_control`, `maintenance_plan_sha256`, `initial_static_condition_sha256`, `initial_static_inspection_passed`, `review` |
| `backend_execution_safety` | `release_binding` (`runtime_release_id`, `release_manifest_sha256`); `motion_profile_binding` (`profile_id`, exact same `runtime_release_id`, distinct `profile_manifest_sha256`, unique increasing `approved_speed_grades` in `1..100`); `method_deadlines_s` (`read_state`, `command_position`, `stop`, `close`); `method_timeout_handling` (same exact methods); `stop_isolation` (`independent_executor`, `independent_lock_domain`, `not_queued_behind_normal_commands`, `hung_command_stop_deadline_s`, `hung_command_stop_deadline_verified`, `deadline_miss_fails_closed`); `backend_method_contract_sha256`, `stop_isolation_architecture_sha256`, `hung_command_stop_test_report_sha256`, `review` |
| `feedback_contract` | `field_capabilities` for every `GripperState` feedback field, each with explicit `SUPPORTED`/`UNSUPPORTED`; supported fields require unit, encoding, range, resolution, update rate and validity semantics. Also required: source/receive timestamp, sequence, invalid-value, fault-latch/recovery, command-correlation and restart specifications; fault-dictionary and command-capability hashes; normalized/jaw-opening command support; `review` |

`tool_identity.tool_architecture` is exactly `COMPLETE_REPLACEMENT` in this
schema. `complete_replacement` must be true,
`legacy_ag_components_retained` must be false, and
`ag_retention_map_sha256` must remain null. If the project selects Original AG,
freeze that decision in a separate AG-specific release package. Do not paste AG
names, Atom/shared-arm transport or historical AG parameters into this
replacement manifest.

The four passive classifications are controlled enums. Backdrivability is
`BACKDRIVABLE`, `NOT_BACKDRIVABLE` or `CONDITION_DEPENDENT`; brake is
`PRESENT` or `ABSENT`; self-locking is `SELF_LOCKING`, `NOT_SELF_LOCKING` or
`CONDITION_DEPENDENT`; loss-of-power jaw behavior is `RELEASES`, `RETAINS` or
`MOVES_TO_DEFINED_SAFE_POSITION`. These values classify reviewed evidence;
they do not authorize an energized loss-of-power or retained-load test.

Backend timeout handling is exactly `CANCELLABLE` or
`BOUNDED_ABANDONMENT`. Merely placing a timeout around a caller is insufficient
if the blocked call retains the STOP lock or executor. The accepted artifact
set must include a pure-fake hung-command test showing STOP is independently
scheduled and completes within `hung_command_stop_deadline_s`; no device or
vendor backend may be used to close this offline gate.

Runtime/profile binding is exact, not descriptive metadata. The release
manifest hash and motion-profile hash must identify two distinct, locally
bound, reviewed artifacts. The profile repeats the exact runtime release ID
and lists the only speed grades eligible for a future release. A missing or
stale ID/hash, hash reuse, duplicate/out-of-order grades, or a requested grade
outside the approved set leaves the real backend `DISABLED/BLOCKED`.

## Unknown-to-evidence closure matrix

| Unknown | Controlled document request | De-energized/static measurement | Pass artifact | Current state |
|---|---|---|---|---|
| Tool identity and configuration | Release certificate naming tool model, revision, assembly configuration and serial/lot; immutable BOM and current assembly hash | Photograph labels and markings on the complete tool, actuator and controller; reconcile every installed item to BOM without opening powered equipment | Signed identity/BOM reconciliation with zero unexplained parts | BLOCKED: CAD filename is not product identity |
| Actuator identity | Manufacturer datasheet and drawing for exact manufacturer part number and hardware revision; shaft/spline specification | Record label/laser marking, body dimensions, output shaft/spline tooth count and keyed orientation with calibrated tools | Marking photos plus dimensional match to one controlled datasheet | BLOCKED: generic `舵机.SLDPRT`; SG90/MG90S/MG996R guesses forbidden |
| Controller and firmware identity | Controller part number, hardware revision, firmware release note and compatibility matrix for the selected actuator | Record controller label, connector designators, switch/address settings and wiring labels; firmware cannot be inferred statically | Controller identity record; firmware remains field-blocked if no label/controlled record exists | BLOCKED |
| Gripper architecture selection | Signed project decision selecting Original AG or complete replacement; Original AG additionally needs its own exploded view/BOM and retain/remove map | Compare visible installed parts and interfaces with the selected architecture | This manifest may proceed only for zero retained AG/Atom parts and `COMPLETE_REPLACEMENT`; Original AG stays blocked pending a separate schema | BLOCKED: current CAD is only a replacement candidate and no Original-AG release package exists |
| Transport and protocol | Complete PWM/UART/RS-485/CAN/other specification: levels, timing, addressing, frames/registers/opcodes, units, CRC, ACK/NAK, sequence, command ID, duplicate/replay/out-of-order behavior and STOP | Trace each unpowered conductor connector-to-connector; record connector type, pin number, wire colour, shield and chassis/signal ground continuity | Reviewed protocol spec plus signed point-to-point wiring/netlist; transport remains disabled | BLOCKED |
| Electrical ratings and protection | Rated/absolute voltage, idle/start/rated/peak/stall current, ripple, wire gauge, fuse/current limit, polarity, grounding, insulation, clearance/creepage, thermal, EMC/ESD and hot-plug rules | Verify connector keying, wire gauge, fuse/current-limit part/rating, grounding/bonding continuity, insulation condition and absence of shorts with energy isolated; do not perform a powered dielectric test in this stage | Electrical interface control document and static inspection log | BLOCKED; no numeric supply/current may be guessed |
| Power-on, watchdog and disconnect safety | Power-on default, enable/reset behavior, heartbeat/watchdog period and tolerance, communication timeout, disconnect output state, restart rule and independent energy-isolation design | Inspect physical isolation device, contact ratings, wiring boundary and residual-energy discharge components; dynamic behavior remains field-blocked | Reviewed safety-state table plus isolation schematic/inspection | BLOCKED; dynamic watchdog test requires later authorization |
| Feedback schema | Field dictionary for connected/valid/enabled/moving/limits/position/opening/current/force/temperature/fault; units, encoding, resolution, update rate, timestamp/sequence, invalid values and controller restart semantics | Identify fitted sensors, part numbers, wiring and mechanical limit devices without assuming a sensor exists from software fields | Versioned schema and sensor inventory; unsupported fields explicitly marked unsupported | BLOCKED; `255`, `-1` and magic values forbidden |
| Mechanical joints and hard limits | Frozen assembly tree/mates, joint axes, gear ratio, linkage/mimic relation, safe open/mid/closed configurations and tolerance stack | With energy isolated and actuator mechanically decoupled only if the approved service procedure permits it, measure hard-stop geometry and clear opening without forcing a mechanism; otherwise document-only | Joint/limit drawing and measurement log with uncertainty | BLOCKED; no forced manual back-driving |
| Passive power-loss and retained-load behavior | Controlled statement of brake/self-locking/back-drivability, residual stored energy, loss-of-power jaw behavior, object-drop hazard and any secondary retention or exclusion-zone requirement | Inspect springs, brakes, latches, guards and secondary retention with energy isolated; do not prove holding by hanging a load or manually back-driving an unreviewed transmission | Reviewed loss-of-energy hazard analysis and later authorized dynamic test plan | BLOCKED; software STOP or static jaw position does not prove retained load |
| Opening calibration | Native command/feedback definition and sensor transfer function | Measure only present unpowered clear jaw opening/contact geometry at approved references; command-to-opening direction/nonlinearity/hysteresis remains field-blocked | Static geometry record plus later authorized calibration table | BLOCKED; old AG 20--45 mm and `0..100` prohibited |
| Finger/contact interface and human hazards | Contact-pad material, hardness/compliance, attachment, allowable pressure, cleaning/chemical compatibility, pinch/shear/crush points, sharp-edge limits and guarding requirements | Inspect and dimension contact surfaces, pad retention, reachable gaps, exposed gears/linkages, burrs/sharp edges and entanglement points without moving the mechanism | Reviewed contact-interface specification and hazard/guarding inspection | BLOCKED; filename geometry does not prove safe contact or guarding |
| Mass, CoM and inertia | CAD material/density coverage report and six-term inertia tensor in a named frame for each rigid link and complete installed tool | Calibrated scale mass of tool, adapter, fasteners and moving cable; de-energized multi-orientation balance/fixture CoM measurement with repeats | CAD-versus-measured reconciliation, uncertainty and payload/torque review | BLOCKED; 100 g, model 115 g and text 170 g are not release values |
| Flange and fasteners | Controlled arm flange/tool adapter drawings, tolerance, material, fastener class, engagement, torque and anti-rotation method | Measure hole diameter/position, PCD, locating features, mounting-face flatness, adapter thickness, engagement depth and cable exit three times from one datum | Dimensioned interface inspection report | PARTIAL: nominal 4×M2/PCD≈30.8 mm is integration input, not manufacturing proof |
| TCP and opening dependence | Coordinate-frame drawing defining `arm_flange -> gripper_mount -> gripper_tcp`, approved bottle/contact band and revision | Three independent 6D static measurements; repeat at approved static openings only when they can be set safely without power; otherwise defer opening dependence | Mean transform, per-run data, uncertainty and `tcp_offset(opening)` disposition | BLOCKED; model `(0,0.0931,0.0025) m` is not calibrated TCP |
| Collision and cable envelope | Versioned visual/collision meshes, link mapping and frozen open/mid/closed configurations | Measure connector/cable protrusion, minimum bend radius and static envelopes; photograph interference checks | Hash-bound mesh/manifest plus static envelope report | BLOCKED; generated meshes are staging evidence only |
| Durability, maintenance and retention | Rated cycle life/duty, gear/bearing load ratings and fits, wear/backlash limits, lubrication, fastener locking/torque-mark policy, inspection interval, replacement criteria and approved spare revisions | Inspect for loose/missing fasteners, retention features, torque marks, contamination, corrosion, cracked/worn parts and lubricant leakage without disturbing the assembly | Versioned maintenance/inspection plan plus initial static condition record | BLOCKED; one successful motion cannot establish service life |

No row may be closed by an AI-generated description, reseller listing,
filename, photograph alone, geometric estimate alone or historical AG data.

## Controlled identity and BOM

- [ ] Tool model, tool revision and assembly configuration.
- [ ] Assembly SHA-256 and immutable source snapshot reference.
- [ ] Complete BOM including manufacturer, manufacturer part number, hardware
  revision, quantity and material for actuator, reducer, controller, bearings,
  gears, links, fingers, adapter, cable, connector and fasteners.
- [ ] Material, heat treatment/coating and manufacturing revision where these
  affect strength, wear, friction, corrosion, insulation or mass properties.
- [ ] Serial/lot and firmware revision for each controlled actuator/controller.
- [ ] Explicit retain/remove/replace map for every legacy AG/Atom component.
- [ ] Supplier datasheet and drawing revision for every bought-in actuator and
  controller.

Current evidence does **not** identify the actuator or controller. A CAD part
named `舵机` proves only that an actuator-shaped component exists. `SG90`,
`MG90S`, `MG996R` and similar models remain guesses unless the controlled BOM,
part marking and supplier data all agree.

## Electrical and power evidence

- [ ] Rated and absolute supply voltage range.
- [ ] Idle, startup, rated, peak and stall current.
- [ ] Allowed ripple, wire gauge, connector/pinout and protective earth scheme.
- [ ] Fuse/current limit, reverse-polarity, short-circuit, undervoltage,
  overvoltage, surge and thermal protection.
- [ ] Insulation system, clearance/creepage, dielectric/isolation rating and
  applicable EMC/ESD/environmental limits.
- [ ] Hot-plug prohibition/permission and residual-energy discharge time.
- [ ] Independent actuator energy isolation path and physical emergency response.
- [ ] Power-on default output, enable semantics and reset/restart behavior.

## Transport and protocol evidence

- [ ] Transport type: PWM, UART, RS-485, CAN or another frozen interface.
- [ ] Signal levels, frequency/baud/bitrate, address or node ID and unique owner.
- [ ] Full frame/register/opcode map, byte order, units, CRC/checksum and
  ACK/NAK rules.
- [ ] Command ID, sequence, boot/session identity, idempotency, duplicate/replay
  and out-of-order handling.
- [ ] Heartbeat/watchdog period, timeout, disconnect-safe state and reset rule.
- [ ] STOP wire/protocol semantics independent of generic arm STOP.
- [ ] Close/shutdown semantics and behavior after a blocking or failed call.

The retired AG assumptions `gripper_type=1`, `0..100`, `255=fully open`,
100 g and 20--45 mm are forbidden release inputs. Historical `255` is treated
as invalid/disconnected by the offline fixture. Unverified historical YAML
values such as `gripper_torque: 500` and `protect_current: 200` are likewise
forbidden. They have no reviewed source or unit/scale contract.

Additional generated-asset values are also quarantined from release:
`68.84 mm` opening, `34.42 mm` single-side equivalent stroke, TCP
`(0, 0.0931, 0.0025) m`, URDF mass `115 g` and AI-text mass `170 g`. They may
be retained only as explicitly labelled staging hypotheses and must never
populate a hardware backend, limit, payload, collision or TCP configuration.

## Retired AG and unreviewed-value denylist

| Value or claim | Required runtime/release treatment | Evidence required before reconsideration |
|---|---|---|
| `mycobot_gripper_ag`, `gripper_type=1` or Atom/shared-arm transport | No fallback or auto-detection in this replacement manifest | A separate, not-yet-implemented Original-AG release schema plus frozen BOM/section view and controlled protocol evidence |
| `0..100` command or feedback range and assumed open/close direction | Reject as unspecified for the replacement tool | Exact native protocol plus separately authorized direction and nonlinear calibration |
| `255=fully open` | Always invalid/disconnected; never clamp or reinterpret | None for the retired path; a new protocol must define its own explicit validity |
| `100 g`, `20--45 mm` and inherited AG TCP/load claims | Do not load into URDF, payload, limits, planning or acceptance | New-tool measurements tied to the frozen complete assembly |
| `gripper_torque: 500`, `protect_current: 200` | Remove from executable hardware defaults or keep motion gate false; units and semantics unknown | Manufacturer-controlled register definition plus selected actuator/controller ratings and reviewed limit calculation |
| `68.84/34.42 mm`, TCP `(0,0.0931,0.0025) m`, `115 g` or `170 g` | Staging-only, `UNREVIEWED`; never treated as actual measurement | Controlled CAD revision plus physical reconciliation described in the closure matrix |
| SG90, MG90S, MG996R or another generic servo guess | No purchasing, pinout, voltage/current, spline, torque or control decision | Exact installed marking/BOM/datasheet agreement |

Any legacy value entering a release artifact without its required evidence is
an automatic `FAIL_CLOSED_LEGACY_INPUT_DETECTED` result.

## Feedback and safety-state evidence

- [ ] Timestamp source, receive timestamp, sample sequence and update rate.
- [ ] Connected, valid, enabled, moving, limit, position/opening and fault fields.
- [ ] Current, force, temperature and supply feedback where supported, each with
  units, resolution, accuracy, range, latency and validity flag.
- [ ] Complete invalid/fault dictionary and latched/recoverable classification.
- [ ] Command-feedback correlation and behavior across controller restart.
- [ ] Stationary definition: sample count, dwell, position tolerance and timeout.
- [ ] Local ACK rule; ACK must never initialize, enable, clear the controller,
  resume motion or override unresolved STOP uncertainty.

## De-energized mechanical measurements

- [ ] Approved flange drawing, locating feature, bolt pattern and fastener stack.
- [ ] Three independent 6D measurements of flange to mount and mount to TCP.
- [ ] Finger contact surfaces, grasp depth and approved bottle diameter/band.
- [ ] Contact-pad material/compliance/retention and reachable pinch, shear,
  crush, entanglement, burr and sharp-edge inspection.
- [ ] Joint axes, linkage/mimic relation, gear ratio and mechanical hard limits.
- [ ] Minimum/maximum clear opening and opening-dependent TCP offset.
- [ ] Cable/connector sweep and open/mid/closed collision envelopes.
- [ ] Fastener locking/torque marks, bearing/gear retention, visible wear,
  corrosion, contamination and lubricant leakage condition.
- [ ] Instrument, calibration certificate, repeats and measurement uncertainty.

Use the following static worksheet for each measurement set:

| Field | Recorded value |
|---|---|
| Tool/adapter/fastener/cable revision and serial | |
| Assembly SHA-256 and CAD configuration | |
| Datum and coordinate-frame drawing revision | |
| Energy-isolation method and independent verification | |
| Instrument ID, calibration expiry and resolution | |
| Ambient conditions where relevant | |
| Measurement 1 / 2 / 3 | |
| Mean, spread and stated uncertainty | |
| Photograph/raw-data evidence paths and hashes | |
| Reviewer, timestamp and disposition | |

For hole positions, PCD, mounting faces and 6D transforms, three independent
setups are required, not three readings without re-fixturing. For mass, record
at least three zeroed readings. For CoM, use at least three independent fixture
orientations or a reviewed CAD/pendulum/balance method. Never force a
de-energized actuator through a gearbox or hard stop to obtain a measurement.

These items are de-energized/static only. If a value cannot be obtained without
power or motion, record it as `FIELD_BLOCKED_REQUIRES_SEPARATE_AUTHORIZATION`.

## Mass, inertia and load evidence

- [ ] CAD material/density coverage and mass-property report.
- [ ] Physical mass for tool, adapter, fasteners, moving cable and approved bottle.
- [ ] Center of mass and full six-term inertia tensor with reference frame.
- [ ] CAD-versus-measured discrepancy and uncertainty.
- [ ] Worst-case horizontal load/torque and acceleration review against the arm
  limit with an explicit project safety margin.

No new-tool mass may inherit the old 100 g claim. The arm payload budget must
include the complete installed tool, cable and object.

## Durability, maintenance and passive-safety evidence

- [ ] Rated mechanism/actuator cycle life, duty cycle and environmental range.
- [ ] Gear and bearing load/life basis, fit/preload where applicable, allowable
  backlash/wear and lubrication specification.
- [ ] Fastener torque, locking method, torque-mark inspection and replacement
  rule for safety-relevant fasteners and retention parts.
- [ ] Inspection/maintenance interval, wear limits, approved spares and
  configuration-control rule after service.
- [ ] Power-loss, disconnect and shutdown jaw behavior, including whether the
  mechanism back-drives, releases, retains or unpredictably transfers load.
- [ ] Object-drop and stored-energy hazard analysis, physical exclusion/guarding
  controls and any secondary retention requirement.

De-energized inspection may identify installed springs, brakes, latches,
guards, retention features and visible condition. It must not claim retained
load capability from jaw position, suspend a test load, force a gearbox, or
manually back-drive an unreviewed mechanism. Dynamic power-loss/holding tests
remain separately authorized field work.

## Energized measurements frozen for later authorization

- [ ] Direction and monotonic/nonlinear command-to-opening calibration.
- [ ] Hysteresis, backlash, repeatability and safe software limits.
- [ ] Idle/peak/stall current, force, temperature and duty-cycle limits.
- [ ] Maximum approved bottle deformation, slip and release thresholds.
- [ ] Watchdog/disconnect, restart/power-loss, STOP failure and ACK-race tests.
- [ ] Loss-of-power retained-load/drop behavior and recovery without automatic
  re-enable, re-close or resume.

All numeric force, current, deformation and hold/release thresholds remain
`TBD_MEASURED`. Buckle, crack, puncture and leak tolerance is zero. These tests
require a future staged field plan and a fresh explicit authorization; software
STOP does not replace physical emergency stop or power isolation.

## Release gate

Release remains blocked until every applicable item above has a controlled
evidence reference, reviewer, review time and revision/hash. The final ROS
interface, backend and configuration must be generated from that frozen input;
they must not infer missing values or fall back to legacy AG parameters.
