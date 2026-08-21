# LIMO DaBai ROS2 migration-only launch

This ament/Foxy package is retained only for offline migration and source
comparison. The LIMO field runtime is ROS1 Noetic; this package, its Python
launch file and rosbag2 tooling are not an on-robot camera entry and cannot
establish field PASS. Use the audited astra_camera/dabai_u3.launch procedure in
docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md.

Historically this package was proposed as a camera startup entry. It contains
no detector, task subscriber, navigation, base, arm,
gripper, bridge, action, service, UART, or static base transform.

The launch is deliberately fixed to DaBai DC1 serial `CC1WC520183`. It checks
the installed vendor launch SHA-256 before returning any launch action and
then includes only that vendor camera launch with fixed RGB/depth parameters.
It also forces `ROS_LOCALHOST_ONLY=1` and ROS domain `137`.

```bash
ros2 launch limo_cleanup_dabai_sensor \
  dabai_cc1wc520183_sensor_only.launch.py
```

This command must not be used on the ROS1 field robot. It publishes no measured
`base_link -> camera_link` transform. Therefore a healthy camera-only run is
still insufficient for formal six-topic/base-frame readiness until an
independently measured external transform is provided by a separately audited
sensor-only owner.
