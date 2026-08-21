# Arm/gripper local safety evidence — 2026-08-14

> **STALE / SUPERSEDED / NOT RELEASE EVIDENCE:** later concurrency audits
> reproduced the original four STOP/close/command-activation commit-point
> windows, then additionally reproduced (1) gripper `moving=True` combined
> with unhealthy or identity-drift feedback taking an ordinary-fault path
> without STOP/physical escalation, and (2) old arm stationary credit masking
> a newer moving sample and in-flight STOP. The 524-run result and every hash
> in this directory are retained only as historical execution evidence and
> must not be used to release a real backend, claim STOP closure, or enter a
> field stage. A replacement report requires the new negative tests plus a
> fresh full regression and source freeze.

This package freezes the final local-only arm and gripper safety audit for this
task. It is evidence for source, contract and pure-fake behavior only. It is
not a ROS/Foxy build result, hardware authorization, software STOP guarantee
for an unproven transport, or permission to connect an actuator.

## Result

- Local arm/gripper suite: **524 run / 519 passed / 0 failed / 5 skipped**.
- Real arm and gripper backends: **DISABLED/BLOCKED**.
- Physical STOP and energy isolation: **BLOCKED; independent hardware/vendor
  capability evidence is still required**.
- Final gripper architecture: exact `COMPLETE_REPLACEMENT`; no legacy AG
  component is retained. The manifest remains release-blocked with 227
  blockers because the final tool, controller, protocol, electrical data,
  limits, profile and field evidence are not frozen.

## Hard-boundary audit

Since the permanent local-only boundary was issued, this task established no
SSH session and performed no target, process, device-path, USB/serial, ROS
graph, vendor runtime/backend, action/service, power, enable, home, probe or
motion operation.

Before that permanent boundary, bounded SSH sessions had been established for
the single v3 isolated dry-run and later fixed-path/process-list read-only
checks. The preserved v3 evidence records command availability checks for
`awk`, `colcon`, `grep`, `ps` and `python3`; `ros2` was checked before Foxy was
sourced and was therefore missing. Two later read-only audit attempts failed
in remote-shell parsing, so their intended audit logic did not execute and
remote state did not change. No device or actuator interface was accessed.
Residual task-process status remains `UNKNOWN/BLOCKED`; no later connection is
permitted to fill that gap.

The authoritative historical details are in
`../arm_foxy_dryrun_20260813_v3/README.md`.

## Final local change in this closure

The documentation and project policy already selected the complete-replacement
path, but the machine-readable input manifest still recorded an unresolved
architecture. This closure changed only:

- `src/limo_cleanup_executor/config/final_gripper_release_manifest.json`:
  `tool_architecture=COMPLETE_REPLACEMENT`, `complete_replacement=true`.
- `src/limo_cleanup_executor/test/test_final_gripper_release_manifest.py`:
  asserts the exact replacement-only values while retaining release blocking.

The resulting manifest is schema-valid, has zero structural errors, is not
release-ready, and reports 227 blockers. Native command range, jaw-opening
range, installed mass, rated current, runtime release ID and approved speed
grades remain `null`; no retired AG numeric value was substituted.

## Test evidence

Bundled Python:

`C:\Users\DYH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`

Commands and final results:

1. From `src/limo_cleanup_executor`:
   `python -m unittest discover -s test -p 'test_arm*.py'`
   — 235 run / 231 passed / 0 failed / 4 skipped.
2. From `src/limo_cleanup_executor`, with that directory as `PYTHONPATH`:
   `python ../../audit_tools/run_pytest_style_tests.py test/test_gripper_core.py test/test_gripper_gateway_core.py test/test_gripper_backends.py test/test_gripper_source_safety.py`
   — 145 collected / 145 passed / 0 failed.
3. From `src/limo_cleanup_executor`:
   `python -m unittest test.test_final_gripper_release_manifest test.test_gripper_gateway_callback_contract test.test_gripper_gateway_ros_contract test.test_gripper_gateway_ros_smoke test.test_gripper_interface_contract test.test_gripper_safety_latch`
   — 144 run / 143 passed / 0 failed / 1 skipped.

The five skips are four tests requiring unavailable local ROS support or a
Windows symlink privilege, plus one gripper ROS smoke test requiring `rclpy`.
No running ROS graph was created.

Three invocation corrections occurred before the final commands above:

- Two fake-runner starts used a module search path that did not expose the
  executor package; both stopped at `ModuleNotFoundError` before collecting or
  executing a test.
- One broad unittest glob imported three pytest-style modules on a host without
  pytest and reported three collection errors. Those modules were then run by
  the intended offline fake runner and passed 145/145. These were harness
  invocation errors, not product-test failures.

## Static and concurrency gates

- Scoped files checked: 59 (58 hashed payload files plus the non-self-hashed
  `SHA256SUMS.txt`).
- `git diff --check`: pass; only CRLF conversion warnings were emitted for
  existing tracked files.
- Conflict markers / trailing whitespace / Tab lines / missing final newline:
  0 / 0 / 0 / 0.
- Python 3.8 AST / in-memory compile: 32/32 and 32/32.
- Dynamic import or timeout-thread calls in production backends: 0.
- Backend file-open/enumeration calls: 0.
- ROS factory/vendor/device-entry hits: 0.
- Core/node lock blocks and forbidden external-call violations:
  arm core 38/0, gripper core 41/0, arm node 2/0, gripper node 3/0.
- Local `bash -n`: skipped because no `bash` executable is installed.

The core generation/epoch tests cover blocked send, concurrent STOP, close,
fault, ACK, refresh and late success/failure. A late result cannot restore an
old state. STOP does not wait for the ordinary core lock. If a real transport
cannot prove bounded native deadlines, native cancellation and a genuinely
independent STOP channel/lock domain, the request escalates to persistent
physical-isolation-required and software STOP success is not reported.

## Persistent latch and release binding

Arm and gripper local latch tests cover exclusive creation, session/epoch
binding, stale-session rejection, replayed clearance IDs, forged credentials,
single-component rollback, incomplete publication, writer exit/unlock failure,
hardlinks and same-bytes inode swaps. Release/profile binding requires exact
runtime release IDs, distinct manifest hashes and exact approved speed grades.

Still blocked: hostile parent/store replacement, privileged full-store rollback
or truncation, operator authenticity, signed/TPM monotonic authority, Windows
power-loss directory durability, protected storage and independent physical
STOP/energy isolation.

## Gripper and CAD facts

- Architecture: `COMPLETE_REPLACEMENT_ONLY` policy and exact
  `COMPLETE_REPLACEMENT` manifest value.
- Retired AG assumptions are denylisted, not executable defaults:
  `gripper_type=1`, `0..100`, `255=open`, inherited torque/current registers,
  TCP, mass and opening range.
- CAD directory: 35 files / 8,058,955 bytes / 35 unique hashes.
- Types: 33 SLDPRT / 1 SLDASM / 1 SWP; STEP/STP 0; PDF 0.
- Unique assembly: 2,035,041 bytes; SHA-256
  `d5f513c69b3590378791cfec8e0853567f8377676429772ed7e38d1653e94d98`.

The final actuator/controller model, electrical ratings, protocol, feedback,
limits, TCP, mass properties, collision envelope and durability evidence remain
explicit measurement/data-sheet tasks, not inferred values.

## Frozen Foxy v3 fact

The one permitted v3 run remains `FAIL-before-build`, status 2. Build, test and
smoke were not entered and must not be reported as passed. Its bundle, runner
and summary hashes are respectively:

- `1fbd5d6cefbbe8abb6f009ed89faae34670704c8f93396f20540a16a976ab72e`
- `325eec2bc95098aa51b9459ba6ce932e8a88a1cac5c9f174f10759c1eda151ce`
- `edc2432b2148affae3a4112556fd2971c92e9f68117238f0a85c2f95ed2027e8`

No rerun or target connection is authorized in this task.
