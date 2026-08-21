# Hardware readiness authority redirect / 硬件就绪权威重定向

> [!CAUTION]
> **`NON_AUTHORITATIVE_DO_NOT_RUN` — current field authority is ROS1 / Noetic.**
>
> The frozen document identified below is retained only as historical
> ROS2/Humble/Foxy migration and hardware provenance. Its commands are not
> current operating instructions and must not be copied or executed.

## Frozen historical source

- path: `docs/hardware_readiness.md`
- size_bytes: `13274`
- sha256: `6d48815b660c3f6b0c00fb36dc633d403b540e5a95f0bdedaddc37f33093fd9b`
- status: `NON_AUTHORITATIVE_DO_NOT_RUN`
- lifecycle: `FROZEN_HISTORICAL_ROS2_PROVENANCE`

The historical marker `REAL_PERCEPTION_GATE_ACCEPTANCE_PASS` does not prove or
authorize the current ROS1/Noetic build/install, camera runtime, formal
four-scene denominator, TF/3D, latency, field acceptance, delivery, or motion.

## Only current operational route

1. Start with this redirect; do not enter through the frozen document or its
   retired wrapper.
2. Continue only with
   [`docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md`](PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md).
3. That runbook's only camera-driver role is the host-owned
   `audit_tools/ros1_camera_only_atomic_launcher.py` interface. The launcher
   remains fail-closed until independently anchored Noetic runtime-install
   evidence exists.

This redirect is a task-scoped documentation safety artifact. It is not a
release-selection authority, formal field evidence, a delivery predecessor, or
permission to start ROS, a camera, inference, a network connection, or hardware.
