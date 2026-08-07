# myCobot Gripper AG control boundary

## Purpose

The confirmed end effector is the Elephant Robotics myCobot Gripper AG
(`mycobot_gripper_ag`) mounted on a myCobot 280 M5. The repository previously
contained only mock `grasping` and `dropping` states. It had no bounded
gripper command interface, hardware-motion interlock, position verification,
timeout, or failure contract.

This implementation adds a standalone action:

```text
/cleanup/gripper
limo_cleanup_interfaces/action/ControlGripper
```

The public position is normalized:

```text
0.0 = calibrated closed position
1.0 = calibrated open position
```

`COMMAND_SET_POSITION` is intentionally supported. An empty plastic bottle is
deformable, so the first real grasp must use a measured partial-close position
instead of blindly driving to the mechanical closed limit.

## Safety defaults

- The default backend is `dry_run`.
- `allow_hardware_motion` defaults to `false`.
- Selecting `backend:=pymycobot` without motion authorization does not import
  pymycobot, open the serial device, or transmit a command.
- Real connection also requires
  `confirmed_gripper_model:=mycobot_gripper_ag`.
- Calibration, initialization, zeroing and repeated close commands are never
  issued automatically.
- A timeout aborts the action without an automatic retry or recovery movement.
- The full cleanup launch does not start the gripper controller by default.

These rules protect against an incorrect serial device, mismatched driver API,
unverified jaw direction, crushing an empty bottle, and repeated closing after
a jam.

## Backends

`dry_run` stores and reports the commanded normalized position. It is suitable
for action integration and task-state tests before hardware arrival.

`pymycobot` is a deliberately thin optional adapter around
`set_gripper_value` and `get_gripper_value`. It supports pymycobot variants
whose methods either include or omit the `gripper_type` argument. The package
is loaded dynamically, so development and dry-run tests do not require it.

The provisional raw calibration is:

```yaml
closed_value: 0
open_value: 100
gripper_type: 1
```

These values are not yet hardware acceptance results. Confirm them against the
installed pymycobot version and the physical gripper before enabling motion.

## Dry-run

```bash
ros2 launch limo_cleanup_bringup gripper_control.launch.py
```

Open:

```bash
ros2 action send_goal /cleanup/gripper \
  limo_cleanup_interfaces/action/ControlGripper \
  "{command: 1, position: 0.0, speed: 0.2, verify: true}"
```

Partial close:

```bash
ros2 action send_goal /cleanup/gripper \
  limo_cleanup_interfaces/action/ControlGripper \
  "{command: 3, position: 0.35, speed: 0.15, verify: true}"
```

## Hardware acceptance sequence

Do not enable `pymycobot` until all of the following are complete:

1. Verify the arm and gripper nameplates, supply, grounding, mounting and
   emergency power removal.
2. Confirm the Jetson serial path, permissions, pymycobot version, constructor
   class and `gripper_type` required by that version.
3. Keep the arm stationary and clear the gripper workspace.
4. Confirm which raw value opens and closes the jaws using the vendor tool at
   minimum speed. Update `closed_value` and `open_value`.
5. Measure the safe jaw range and calibrate `gripper_tcp`.
6. Use a weighed empty bottle. Sweep partial-close values slowly and record the
   first repeatable hold position, slip rate and release success.
7. Only after those checks, launch with both
   `backend:=pymycobot` and `allow_hardware_motion:=true`.

Gripper position alone does not prove a successful grasp. A bottle may slip,
buckle, or remain between the jaws. The parent cleanup executor must later use
vision, arm load/current data, or another sensor to verify pickup and release.
