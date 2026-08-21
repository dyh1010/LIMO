# Perception V2 current operations index / 当前操作索引

> [!CAUTION]
> This task-scoped index is the only current human-entry route for the frozen
> hardware-readiness material. It is not release authority, field evidence, or
> permission to start ROS, a camera, inference, networking, or hardware.

## Exact route

1. Read
   [`docs/HARDWARE_READINESS_ROS1_NOETIC_REDIRECT.md`](HARDWARE_READINESS_ROS1_NOETIC_REDIRECT.md)
   first. It demotes the frozen ROS2/Humble/Foxy hardware document and binds
   that document's immutable path, size, and SHA-256.
2. Only after that redirect, continue to the frozen ROS1/Noetic runbook:
   [`docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md`](PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md).
3. The runbook's only camera-driver role is the host-owned
   `audit_tools/ros1_camera_only_atomic_launcher.py` interface, which remains
   fail-closed until independent Noetic runtime-install admission is bound.

Frozen runbook identity:

- path: `docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md`
- size_bytes: `20759`
- sha256: `44e72bb4ec686ee76d816814b26eda4c18adf8145fa2bec05ace5b69aa31be2d`

The frozen `docs/hardware_readiness.md`, its retired wrapper, and historical
ROS2 PASS markers are never current entry points. This index is
`TASK_SCOPED_NON_FORMAL`, is not a delivery predecessor, and leaves formal
denominator, field-consumer acceptance, and delivery readiness false.
