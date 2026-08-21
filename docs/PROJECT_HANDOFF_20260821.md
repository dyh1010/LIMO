# LIMO AI Scout project handoff — 2026-08-21

## Executive status

The workspace preserves the source, contracts, tests and operator documents for
the V1–V3 development line. It is not a field-ready robot release. The default
runtime baseline is ROS1/Noetic; retained ROS2/Foxy packages and launch files
are legacy, offline or bridge-side assets unless an individual document proves
otherwise.

```text
V1 navigation: BLOCKED_FOR_FIELD_RELEASE
V2 voice/dialogue: BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY
V2 perception: BLOCKED_FIELD_EVIDENCE_AND_RUNTIME_ADMISSION
V3 arm/gripper: REAL_EXECUTION_BLOCKED
integrated autonomous cleanup: NOT_ACCEPTED
```

No offline test, private ROS master, mock graph, Catkin build, prerecorded WAV,
static image or read-only hardware observation authorizes nonzero robot motion.
Software STOP/cancel is a high-level safety request and never replaces physical
emergency stop or power isolation.

## Repository checkpoint

- GitHub: `https://github.com/dyh1010/LIMO`
- Default branch: `main`
- Voice handoff commit: `f6f0c57`
- Remote-history merge: `a28718b`
- This checkpoint commits project source, tests, machine-readable contracts and
  compact reviewed evidence documents.
- Generated archives, caches, runtime output, large field captures and temporary
  render products are intentionally excluded by `.gitignore`.

## Capability matrix

| Area | Implemented and retained | Honest remaining blocker |
| --- | --- | --- |
| V1 base/navigation | ROS1 base, navigation and map-binding overlays; protocol, watchdog, topology and zero-stage contracts; bridge-side safety assets; offline tests and runbooks | Active map and `trash_bin_staging` are not frozen; production runner/admission remains blocked; no accepted nonzero autonomous run |
| V2 voice | “小莫小莫” wake gate; confirmation/timeout/cancel; high-level intents; independent STOP contract; Vosk evidence tooling; ROS1 offline adapter and Catkin preview | ROS1 production owner, stop gate, real navigation cancel relay/ACK and live topology acceptance are not implemented/accepted |
| V2 perception | Strict RGB-D, typed-frame, target, evidence-lineage and readiness contracts; ROS1 DaBai source/overlay; evaluator and field intake tools | Field RGB-D alignment/synchronization, frozen camera/model binding, four-scene evidence and production runtime admission remain blocked |
| V3 arm/gripper | Pure cores; fake-only gateways; Action/Service contracts; release manifests; persistent safety latches; ROS1 manipulation preview | Final tool/transport owner, protected latch authority, real backend, IK/trajectory/collision, field adapter and physical motion acceptance remain blocked |
| Integration | Bringup safety defaults, high-level interfaces, mock/dry-run paths and cross-component contracts | No accepted navigation→perception→grasp→transport→release chain; ordinary voice intent remains mock-only |

## V1 base and navigation

The intended production ownership is ROS1-native:

```text
YDLidar -> /scan -> SLAM/localization -> move_base
  -> ROS1 safety watchdog/mux
  -> private /cleanup/base/driver_cmd_vel
  -> sole limo_base_node owner -> /dev/ttyTHS0
```

The ROS1/ROS2 bridge path is intentionally narrow and fail-closed. Public
`/cmd_vel` must not bypass the ROS1 watchdog, and ROS1/ROS2 base drivers must
never own the UART concurrently. Existing zero-output, map binding, generation,
lease, nonce, cleanup and topology code is software evidence only.

Hard blockers include a non-frozen map/waypoint, unresolved production
runner/admission findings, unaccepted owner/freshness/cleanup evidence and no
measured driver-level disconnect stop bound. V1 field completion therefore
remains 0%; manual driving history is not autonomous-navigation PASS.

Primary documents:

- `docs/product_roadmap_v1_v3.md`
- `docs/ros1_noetic_base_bridge_implementation.md`
- `docs/ros1_ros2_base_bridge_contract.md`
- `docs/tracked_base_control.md`
- `ros1_overlay_src/limo_v1_navigation/docs/V1_FIELD_RUNBOOK.md`

## V2 voice and dialogue

Voice publishes only high-level intent. Ordinary requests require the exact
wake word, an unambiguous supported semantic candidate and explicit
confirmation. Unwoken, negated, quoted, reported, metalinguistic, ambiguous or
expired input fails closed. “停下/紧急停止” bypasses wake/confirmation and
does not wait for the semantic Agent.

The final hash-bound offline evidence records:

- four-WAV first-complete candidate: exact `4/4`, micro CER `0`;
- 37 human-voice evaluation: exact `28/37`, micro CER `0.081081`, semantic
  safety `37/37`;
- human STOP endpoint: `4/4`;
- 80 human negative cases: `0/80` STOP false triggers;
- endpoint-after-word p50/p95/max: `375/430/430 ms`;
- ordinary and production publish count: `0`.

Partial STOP is not promoted: it detected `0/4` and produced `1/80` negative
false triggers. These are offline acoustic/software measurements, not physical
robot stop latency. See
`src/limo_cleanup_voice/docs/VOICE_V3_HANDOFF_20260821.md` for hashes and exact
reproduction commands.

## V2 perception and DaBai

The repository contains strict source/admission layers for camera identity,
RGB-D synchronization, typed raw bindings, target schema, evidence lineage,
readiness bundles, rosbag1 admission and field evidence production. The DaBai
sensor-only package and ROS1 perception overlay are designed to fail closed
without creating motion interfaces.

Confidence-first target selection and conservative bin filtering have local
software evidence, but production acceptance still needs current robot camera
identity/model hashes, aligned and synchronized depth, four independent scene
classes, transparent/reflective bottle coverage, frame/extrinsic checks and
end-to-end latency. Perception must not admit arm/base motion while required
evidence is missing or stale.

Primary documents:

- `docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md`
- `docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md`
- `docs/REAL_CAMERA_READONLY_ACCEPTANCE_TEMPLATE.md`
- `src/limo_cleanup_dabai_sensor/README.md`

## V3 arm and gripper

The retained implementation is deliberately fake-first. It includes strict
command validation, single-owner gateway cores, STOP/epoch barriers, release
manifest validation and persistent local safety-latch contracts. Real backend
selection remains disabled until the exact arm, final tool revision,
controller, transport owner, TCP, limits, acceleration profile and physical
verification artifacts are frozen together.

The replacement gripper candidate cannot inherit old AG protocol or parameters.
Historical `255` feedback is invalid/disconnected, not an opening measurement.
No real arm/gripper Action, homing, calibration, fault clear or motion is
authorized by local fake tests.

Primary documents:

- `src/limo_cleanup_executor/ARM_GRIPPER_V3_LOCAL_HANDOFF_20260817.md`
- `docs/v3_pick_place_acceptance.md`
- `docs/arm_gripper_field_acceptance_matrix.md`
- `docs/arm_gripper_ros1_noetic_dry_run_checklist.md`
- `docs/arm_persistent_safety_latch.md`
- `docs/gripper_persistent_safety_latch.md`

## Source included in this checkpoint

- tracked updates under `docs/`, `scripts/`, base, bringup, executor,
  interfaces and perception;
- ROS1 overlays for base, navigation, perception and manipulation;
- DaBai sensor-only package;
- pure-software audit/evidence tools;
- offline fixtures, compact reviewed `docs/evidence`, and machine-readable
  release/admission contracts.

Excluded generated/local material:

- `build/`, `install/`, `log/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`;
- root `evidence/` (large field/runtime captures), `output/` and `tmp/`;
- generated `arm_foxy_dryrun_*.tar.gz` archives;
- external model, recording and evaluation laboratories outside this Git root.

Exclusion means “not suitable for normal Git source history”, not deletion. The
files remain local and should be archived separately with hashes when needed.

## Validation at handoff

This checkpoint is a source-preservation handoff, not a field release. The
following ROS-free checks were observed before staging:

- Python source parsing: `406/406` files parsed successfully;
- base/navigation policy tests: `79 passed` in the previously completed
  ROS-free suite;
- executor/arm/gripper tests: `649 passed, 10 skipped` in the previously
  completed ROS-free suite;
- V1 navigation direct stdlib discovery on the bundled Windows runtime:
  `159/164 passed`, with three Windows temporary-directory descriptor errors
  and two deliberately frozen source/hash inventory mismatches;
- ROS1 manipulation isolated discovery: `17/17 passed` with only the package
  source root supplied on `PYTHONPATH`;
- DaBai camera sensor-only source contract: `8/8 passed` in the bundled
  ROS-free test runner;
- perception's historical frozen inventory is **not green**: the current
  generation contains `178` statically counted tests while its old manifest
  expects `144`; Python source inventories also changed. The broad perception
  run additionally depends on generated ROS messages, NumPy and three exact
  historical temporary evidence artifacts that are not present on this host.

Those perception/V1 failures are recorded as blockers requiring a deliberate
new frozen baseline or the exact historical environment. They are not silently
reclassified as PASS and do not indicate field readiness. Final staged-path,
large-file, credential-pattern and `git diff --cached --check` inspections are
reported with the resulting commit IDs in the task handoff.

## Next safe execution order

1. Freeze and review one ROS1/Noetic source baseline per subsystem.
2. Close V1 runner/admission blockers, then perform separately authorized
   read-only and zero-output topology acceptance.
3. Freeze a real map and measured `trash_bin_staging`; only then test navigation
   under a new on-site nonzero-motion authorization.
4. Complete voice ROS1 production ownership and independent STOP gate while
   ordinary intents stay mock-only.
5. Complete perception field evidence and source/runtime admission without
   connecting it to motion.
6. Freeze final gripper hardware and real arm/gripper safety release; progress
   from power-isolated to read-only to one-axis/one-step motion, never directly
   to the full pick-and-place chain.
7. Attempt integrated V3 only after every upstream gate is independently green.

Every future real-motion session must identify the robot, operator, safety
observer, physical emergency-stop/power-isolation method, cleared area, unique
hardware owners, exact command and abort criteria. Authorization is per session
and per action; previous approval is not reusable.
