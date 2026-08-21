# Final replacement-gripper release manifest

Status: `FAIL_CLOSED_UNTIL_ALL_REQUIRED_INPUTS_ARE_REVIEWED`

Schema version: `3`

The machine-readable release gate is defined by:

- `src/limo_cleanup_executor/config/final_gripper_release_manifest.json`
- `src/limo_cleanup_executor/limo_cleanup_executor/final_gripper_release_manifest.py`
- `src/limo_cleanup_executor/test/test_final_gripper_release_manifest.py`

The checked-in manifest is an evidence request, not a hardware configuration.
Unknown values remain `null` or `false`. Its CAD file list records a read-only
source snapshot, but that snapshot does not prove the product identity,
installed configuration, kinematics, mass properties or control interface.
The validator therefore reports the manifest as schema-valid and release
blocked.

The validator uses only the Python standard library. It does not import ROS,
vendor libraries or serial libraries, and it does not inspect a ROS graph,
enumerate devices, open a transport or send commands. Do not use its success
as authorization to connect, power, enable, home, calibrate or move a tool.

## Offline invocation

From the workspace root, with the package source on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = 'src\limo_cleanup_executor'
python -m limo_cleanup_executor.final_gripper_release_manifest `
  src\limo_cleanup_executor\config\final_gripper_release_manifest.json `
  --artifact-root C:\absolute\path\to\controlled-artifacts `
  --cad-root C:\absolute\path\to\frozen-cad-root
```

Exit status `0` means that the exact manifest passed the release gate. Exit
status `2` means invalid JSON, a schema failure, an incomplete review or a
release blocker. A report can be persisted with `--report PATH`. The output is
deterministic JSON containing separate `errors` and `blockers` arrays.

Both roots are mandatory for the complete gate. The validator resolves every
declared relative path inside its selected root, requires an ordinary file,
recomputes its byte count and SHA-256, rejects path escape and undeclared CAD
files, and recomputes the canonical CAD inventory digest. Omitting either root
is a release blocker. `validate_manifest_structure()` exists only for schema
diagnostics; a structure-only pass is never release evidence.

Every non-derived SHA-256 claim elsewhere in the manifest must also resolve to
the computed digest of a bound evidence, neutral-assembly or CAD file. A hash
that is merely well formed or internally repeated is not evidence. The sole
derived exception is the canonical CAD inventory digest, which the validator
recomputes from the fully bound CAD inventory.

## Release rules

The validator enforces all of these conditions:

1. Strict JSON is required. Duplicate keys, non-finite numbers, unknown keys,
   missing keys, wrong types and booleans used as numbers are rejected.
2. The exact schema ID and version are required.
3. `release_requested` and `release_approved` must both be `true` before a
   release can pass.
4. Every mandatory section must have an accepted review record naming its
   evidence IDs, reviewer and UTC review time.
5. Every evidence ID must resolve to one accepted evidence record. Evidence
   must state its controlled source, artifact and SHA-256, method, result,
   reviewer, UTC timestamp and exact applicability. The complete gate must
   locate that artifact below the explicit artifact root and reproduce its
   SHA-256 from the ordinary file on disk.
6. Allowed evidence methods are `CONTROLLED_DOCUMENT` and
   `DE_ENERGIZED_STATIC_MEASUREMENT`. An energized or moving test is not valid
   evidence for this offline gate.
7. All hashes are SHA-256 values with exactly 64 hexadecimal characters.
8. Physical quantities use the explicit units declared in the manifest. The
   frozen base units are metre, radian, kilogram, kilogram metre squared,
   newton, volt, ampere and second.
9. The CAD inventory is bound by normalized relative path, role, byte count
   and SHA-256. File count, total bytes, one assembly identity and the
   canonical inventory digest must agree. The complete gate independently
   enumerates the explicit CAD root and rejects missing, changed, escaped or
   undeclared files.
10. A controlled neutral assembly, BOM and drawing remain mandatory. Native
    CAD filenames and `Macro1.swp` are not substitutes.
11. Controller firmware is an explicit mandatory field; it cannot be inferred
    from controller identity or protocol revision.
12. The flange and TCP contract requires named frames, controlled interface
    documents, two normalized 6D transforms and a reviewed opening-dependence
    disposition.
13. Native command range and direction, jaw-opening range, every joint limit,
    velocity, acceleration, open/mid/closed named poses, force limit and
    calibration evidence are mandatory.
14. Installed mass must include the adapter, fasteners and moving cable. CoM
    and a six-term inertia tensor must name a declared frame.
15. Collision and cable evidence must cover open, mid and closed tool
    envelopes, cable envelope, bend radius, strain relief and interference.
16. Electrical evidence must cover rated and absolute voltage ranges, idle,
    startup, rated, peak and stall current, conductor, protection, pinout,
    polarity, grounding, hot-plug policy and an independent energy-isolation
    specification.
17. STOP must define its request, correlated acknowledgement, timeout and safe
    output state. The fault remains latched until a separately authorized local
    ACK. Software STOP never constitutes a physical emergency stop.
18. Stationary requires valid feedback, explicit units and tolerance, at least
    two consecutive samples, a dwell, a sample period and a timeout longer
    than the dwell. Invalid feedback fails closed.
19. ACK cannot initialize the controller, enable output, clear a controller
    fault, resume motion or retry a command. Recovery requires new command and
    session identities where applicable and no automatic re-enable or resume.
20. One reviewed transport owner must have an exclusive ownership mechanism,
    boot/session identity and `sole_owner_verified=true`.
21. Passive power-loss safety must explicitly classify backdrivability, brake,
    self-locking and loss-of-power jaw behavior. Object-drop controls and
    secondary retention or exclusion requirements must be documented, hash
    bound and accepted by a controlled review.
22. Contact/human safety must identify pad material, compliance, retention,
    allowable pressure and cleaning compatibility. Pinch, shear, crush,
    entanglement and sharp-edge/guarding reviews must each pass and bind to
    controlled evidence.
23. Durability/maintenance must define cycle life, duty, gear/bearing basis,
    wear and backlash limits, lubrication, fastener locking, inspection
    interval, replacement criteria and approved-spares revision control. The
    maintenance plan and initial static-condition record must be hash bound,
    and the initial static inspection must pass.
24. Every final-backend method (`read_state`, `command_position`, `stop` and
    `close`) must have a finite positive deadline and an explicit cancellable
    or bounded-abandonment policy. STOP must use an independent executor and
    lock domain, must not queue behind normal commands, and must have a
    hash-bound pure-fake test proving its deadline while a command is hung.
    A missed STOP deadline fails closed.
25. The backend execution section must bind an exact non-empty runtime release
    ID to a lowercase release-manifest SHA-256. Its motion profile must have a
    distinct profile ID and artifact SHA-256, repeat the identical runtime
    release ID, and enumerate unique increasing approved speed grades in the
    range 1--100. Missing, stale, reused or forged binding data blocks release;
    runtime code may not accept a speed outside that exact approved set.
26. This manifest is explicitly the `COMPLETE_REPLACEMENT` release path. It
    requires `complete_replacement=true`, forbids retained AG components and
    rejects an AG retention-map claim. Selecting `ORIGINAL_AG_RETAINED` requires
    a separate AG-specific schema and evidence package; it must not be expressed
    by weakening this replacement validator.
27. Every `GripperState` feedback field must be classified as `SUPPORTED` or
    `UNSUPPORTED`. Connected, valid, enabled, moving, normalized position and
    fault code are mandatory. Supported fields require units, encoding, legal
    range, resolution, update-rate and validity semantics. The source/receive
    timestamps, sequence, invalid values, fault dictionary, latch/recovery,
    command correlation, controller restart and supported command targets are
    evidence-bound release inputs.

## Quarantined legacy inputs

The release path rejects inherited AG assumptions and generic actuator guesses.
Do not populate the manifest with any of the following:

- the retired AG product name or `gripper_type=1`;
- an assumed `0..100` command or feedback range or direction;
- `255` reinterpreted as fully open instead of invalid/disconnected;
- an inherited `20--45 mm` opening or `100 g` mass;
- unreviewed torque or protection-current register values;
- generated `68.84/34.42 mm` geometry;
- the staging TCP translation `(0, 0.0931, 0.0025) m`;
- generated or historical masses of `115 g` or `170 g`;
- SG90, MG90S, MG996R, Atom/shared-arm transport, or another generic/hobby
  servo identity.

Any such value is a release error, even if all review booleans are changed to
`true`. A release reviewer must replace it with controlled evidence tied to the
exact installed tool and controller revision.

## Current evidence and unknowns

The local source snapshot contains 35 ordinary files totalling 8,058,955
bytes: 33 SLDPRT files, one SLDASM file and `Macro1.swp`. The assembly source is
`齿轮箱.SLDASM`; its SHA-256 is
`d5f513c69b3590378791cfec8e0853567f8377676429772ed7e38d1653e94d98`.
The canonical manifest inventory digest is
`d588c4e41008a3f04b8dc3ab40b461c4ba35b0320120f9611b78f04ceed090fe`.

The following release inputs are still unknown and remain blocked:

- exact tool model, revision, serial/lot, frozen assembly configuration and
  explicit `COMPLETE_REPLACEMENT` reconciliation; an Original-AG choice needs
  its separate, still-unimplemented release package;
- actuator, controller and firmware identities and their compatibility matrix;
- transport, physical layer, protocol, addressing, frames, integrity,
  command-ID, replay, ACK/NAK, watchdog and disconnect behavior;
- neutral CAD assembly, controlled BOM, controlled drawing and materials;
- flange drawing, fastener stack, calibrated flange/mount/TCP transforms and
  opening-dependent TCP;
- native range and direction, jaw opening, joint axes, hard limits, velocity,
  acceleration, named poses, force limit and calibration;
- installed mass, measurement uncertainty, CoM, inertia and arm-load review;
- open/mid/closed collision envelopes, cable sweep and bend radius;
- all electrical ratings, pinout, grounding, protection and isolation data;
- brake/self-locking/backdrivability, loss-of-power jaw behavior, object-drop
  controls and secondary retention or exclusion requirements;
- contact-pad material/compliance/retention, allowable pressure and cleaning
  compatibility, plus pinch/shear/crush/entanglement/sharp-edge guarding
  reviews;
- cycle life/duty, gear and bearing life basis, wear/backlash/lubrication,
  fastener retention, inspection interval, replacement criteria and approved
  spare revision control;
- per-method backend deadlines/cancellation, independent STOP executor/lock
  domain, and a controlled hung-command STOP deadline test report;
- exact backend runtime release/profile binding, distinct reviewed hashes and
  the approved speed-grade set;
- complete feedback capability/support matrix, timestamp/sequence/invalid-value
  semantics, fault dictionary and command-to-feedback capability mapping;
- controller-specific STOP, stationary, ACK and recovery behavior;
- exclusive transport-owner identity and proof.

These unknowns must be closed by supplier-controlled documents or an approved,
de-energized static measurement record. If a value can only be learned by
power, communication, enable or motion, leave it blocked and prepare a
separately authorized field test. Software STOP is not a substitute for onsite
physical emergency stop or energy isolation.
