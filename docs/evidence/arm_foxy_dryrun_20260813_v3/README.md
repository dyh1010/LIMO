# Arm Foxy dry-run v3 evidence

This directory preserves the local copy of the one-and-only target v3 dry-run
evidence. The run was fake/dry-run only and did not access an actuator device,
start a vendor node, send an action/service motion command, or modify the
target's existing ROS 1 processes.

Target paths:

- summary: `/tmp/arm_foxy_dryrun_20260813_v3_summary.log`
- evidence: `/tmp/arm_foxy_dryrun_20260813_v3_evidence`
- runner: `/tmp/run_uploaded_arm_foxy_dry_run_v3.sh`

Bundle:

- size: 46,912 bytes
- SHA-256: `1fbd5d6cefbbe8abb6f009ed89faae34670704c8f93396f20540a16a976ab72e`

Runner:

- size: 5,374 bytes
- SHA-256: `325eec2bc95098aa51b9459ba6ce932e8a88a1cac5c9f174f10759c1eda151ce`

Result:

- runner exit status: `2`
- failure: `ros2` was checked before `/opt/ros/foxy/setup.bash` was sourced
- build/test/smoke: not entered
- target fixed root removed: yes
- uploaded bundle removed: yes
- summary/evidence preserved: yes
- task-specific residual processes: `UNKNOWN/BLOCKED` because the preserved
  manifest has no independent broad process-audit log
- rerun permitted: no

After the run, handoff notes reported that a bounded read-only shell observed
these commands after sourcing Foxy:

- `/opt/ros/foxy/bin/ros2`
- `/usr/bin/colcon`
- `/usr/bin/python3`

No separate raw log for that post-source observation is present in this local
manifest. It is contextual handoff information only and must not be treated as
release evidence.

The target summary SHA-256 at capture time was
`edc2432b2148affae3a4112556fd2971c92e9f68117238f0a85c2f95ed2027e8`.

After local capture, handoff notes recorded fixed-path and process observations,
but no separate raw log for runner deletion or the broad process audit is
present in this local manifest. Those observations must not be promoted to
release evidence. The runner's own directly preserved cleanup evidence is
summary line 4 plus the empty manifest-covered narrow runner PID/cleanup files.
Consequently runner deletion and broad task-process zero-residual status remain
`UNKNOWN/BLOCKED` for this evidence package. No further target connection is
permitted to fill that evidence gap.

Before the permanent no-target/no-SSH boundary was issued, bounded SSH sessions
were established for fixed v3 path-existence checks and ordinary process-list
inspection only. The conditional runner-delete branch did not execute because
the runner was already absent. No device path, USB/serial interface, ROS graph,
vendor backend, action/service, power, enable or motion operation was accessed.
Two additional read-only audit attempts failed in remote shell parsing (one
Python command quoting error and one `awk` syntax error); their audit logic did
not execute and remote state did not change. Other transient process-list
observations from those sessions are intentionally not treated as evidence and
do not change the `UNKNOWN/BLOCKED` status above.

The local verifier has since been corrected to source Foxy before checking ROS
commands. Its regression suite is `61 tests: 60 passed / 1 skipped`; the skipped test is
the local ROS smoke because this Windows host has no `rclpy`. This source fix
does not change the recorded v3 result: v3 remains `FAIL-before-build`, and no
build/test/smoke stage may be claimed as passed. The current permanent
no-target/no-SSH boundary prohibits any new isolated target build in this
task; this document provides no future connection or rerun authorization.

That `60 passed / 1 skipped` result is the frozen post-fix gate requested for
the v3 handoff. Later local fake-only safety work has added more tests; those
larger local counts are supplemental regression evidence, not target Foxy
build/test/smoke evidence and not a reinterpretation of v3.

The top-level `README.md` and `SHA256SUMS.txt` are local explanatory/index
files. `SHA256SUMS.txt` has 12 entries: 11 target-captured evidence files plus
the summary log. It intentionally does not self-hash or hash this README.
After editing explanatory text, recalculate and report their local file hashes
separately instead of changing the preserved target evidence hashes.

The script contains literal strings such as `pymycobot` and the split
`'/' + 'dev/'` only inside a source-code rejection gate. They are not runtime
backend configuration, device discovery or device access.
