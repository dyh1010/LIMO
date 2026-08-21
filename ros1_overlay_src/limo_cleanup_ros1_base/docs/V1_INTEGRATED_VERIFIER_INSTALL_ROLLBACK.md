# Integrated zero-stage verifier install and rollback contract

This contract closes only the installed-layout dependency for the integrated
navigation runner. It does not authorize ROS startup, hardware access, or
motion, and it does not by itself make integrated deployment field-ready.

## Owned install layout

The verifier implementation is owned by the ROS2 `limo_cleanup_base` package
as `limo_cleanup_base.zero_stage_handoff_verifier`. Its `setup.py` declares the
`zero_stage_handoff_verifier` console entry point, so source, build, and
install-space execution use the same ament package-owned program name. No
ROS2 Python import or dependency is added to the ROS1 catkin package.

`run_v2_bridged_navigation.py` resolves it only through this exact command:

```text
ros2 run limo_cleanup_base zero_stage_handoff_verifier
```

There is no caller-supplied path, workspace-root fallback, or guessed relative
path. The ROS1 and ROS2 deployment environments still both have to be sourced
as required by the reviewed session runbook so that `rosrun`, `rclpy`, and the
installed `limo_cleanup_base` Python package are available.

## Fail-closed behavior

If the package, installed program, ROS2 Python dependency, endpoint metadata,
or exact zero-stage owner proof is absent or invalid, the verifier command is
nonzero and PRE_CORE raises `RuntimeError`. This happens before the integrated
core, navigation adapter, or ROS2 navigation intent process is spawned. No
alternate file is searched and no PASS token is inferred from prior evidence.

The package test suite checks the positive install declaration and exact
package lookup command. Its negative subprocess fixture returns an installed-
program-not-found result and requires PRE_CORE to block.

## Rollback

On an install-layout failure:

1. Keep integrated navigation BLOCKED; do not copy a verifier into an ad-hoc
   path and do not change `ROS_PACKAGE_PATH` to shadow the reviewed package.
2. Stop only processes created and owned by the integrated runner. Do not kill
   an unknown process and do not remove the external zero-stage safety chain.
3. Restore the reviewed ROS2 base package source/install artifact, rebuild the
   ROS2 workspace, and prove `ros2 run limo_cleanup_base
   zero_stage_handoff_verifier` resolves the declared console entry point.
4. Rerun the complete frozen offline regression before preparing a new field
   session. A software PASS remains separate from field authorization and
   delivery readiness.

Software stop is not a substitute for the on-site physical emergency stop or
main-power disconnect. No autostart unit is authorized by this contract.
