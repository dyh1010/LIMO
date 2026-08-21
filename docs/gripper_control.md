# Gripper control boundary (simulation-only; runtime prohibited)

## Current repository status

The final end effector is not frozen. The CAD under
`C:\Users\DYH\Desktop\v1gripper` is a complete replacement-gripper candidate,
not evidence that an Elephant Robotics AG actuator, controller or protocol is
retained. No real gripper backend or hardware transport is released.

The current ROS 2 source contains two distinct simulation-only surfaces:

- The legacy `gripper_controller` executable exposes `/cleanup/gripper` with
  `limo_cleanup_interfaces/action/ControlGripper`. It constructs
  `DryRunGripperBackend` only. Selecting another backend leaves the controller
  without a backend; selecting `pymycobot` does not construct a client even if
  `allow_hardware_motion` is true.
- The contract gateway `gripper_gateway` exposes
  `/cleanup/gripper/execute`, `/cleanup/gripper/stop`,
  `/cleanup/gripper/acknowledge_fault` and `/cleanup/gripper/state` using
  `ExecuteGripperMotion`, `StopGripper`, `AcknowledgeGripperFault` and
  `GripperState`. It accepts only `backend=dry_run`, constructs the local
  in-memory `DryRunGatewayGripperBackend`, and requires all identity fields to
  use explicit `DRY_RUN_*` sentinels.

Neither surface contains a gripper hardware transport: there is no serial,
USB, device-path, vendor-socket or actuator-owner implementation.
`DRY_RUN_TRANSPORT` is a sentinel identity string, not a transport
implementation. The full cleanup launch does not start the legacy gripper
controller by default.

These statements describe the reviewed source. They do not claim that a ROS
runtime or ROS graph was started or inspected in this task.

## Permanent task boundary

This task is permanently limited to local pure-fake tests, source/AST/compile
checks, documentation, manifests and hashes. It must not:

- establish SSH or any target-machine connection;
- enumerate, inspect or open device paths, serial ports or USB devices;
- start, inspect or interact with a ROS runtime or ROS graph;
- import, construct or connect a vendor backend;
- send any Action or Service request, including the simulation-only endpoints;
- power, enable, initialize, home, calibrate, clear faults or move a gripper.

The boundary is stronger than the launch defaults. No command example,
interface definition, manifest or future checklist grants permission to run a
ROS node or contact hardware. Software STOP is not a physical emergency stop
and cannot prove removal of stored mechanical energy.

## Simulation-only contracts

The legacy `ControlGripper` action uses a normalized position contract:

```text
0.0 = configured dry-run closed endpoint
1.0 = configured dry-run open endpoint
```

It lacks session, authorization, command-ID, separate STOP and separate ACK
fields. It remains an integration fixture and is not a releasable hardware
contract. Its `allow_hardware_motion` parameter does not create a hardware
path.

The newer gateway source wires the tool-neutral Action/STOP/ACK/state IDL to a
ROS node, but only around an in-memory backend. Its launch and config pin:

```text
backend: dry_run
allow_simulated_motion: false
reviewed_* identity: DRY_RUN_* sentinels
```

The gateway core provides session binding, authorization and command IDs,
timestamped samples, identity and controller-boot checks, `STOPPING`,
multi-sample stationary verification, latched faults and authorization-gated
local ACK. Jaw opening, current, force, voltage and temperature are not
implemented by the dry-run backend and must not be inferred from normalized
position.

The repository contains no released final-tool parser, hardware gateway,
transport owner, firmware binding or physical STOP/ACK implementation.

## Backend and legacy AG policy

`DryRunGripperBackend` and `DryRunGatewayGripperBackend` store state in memory.
They are the only backends constructed by the ROS source.

`PymycobotGripperBackend` is a permanent fail-closed placeholder. It requires
an explicit callable only so tests can prove that the supplied factory is
never invoked; it exposes no command/read/STOP/close protocol methods and
contains no retired device route, actuator selector or command calibration.
No ROS factory constructs it. A generic arm STOP must never be presented as
gripper STOP evidence.

The previous provisional AG values are retired:

```yaml
closed_value: 0
open_value: 100
gripper_type: 1
```

They are not runtime defaults or release evidence. Historical feedback `255`
is INVALID/DISCONNECTED, never fully open. Do not inherit the range, direction,
type, torque, current, TCP or mass assumptions for either a retained AG chain
or the complete replacement candidate.

## Local verification scope

Permitted verification is source-only or pure-fake. Relevant local contracts
include:

- `test_gripper_source_safety.py` for vendor-import, construction and launch
  lockouts;
- `test_gripper_gateway_ros_contract.py` for simulation-only ROS source and
  dry-run launch/config wiring;
- `test_gripper_gateway_callback_contract.py` for Action/STOP/ACK callback
  behavior without importing ROS 2;
- `test_gripper_gateway_core.py` for session, identity, STOP, stationary, ACK,
  timeout and concurrency behavior with fake backends;
- `test_gripper_safety_latch.py` for append-only restart persistence,
  monotonic session epochs/nonces, pre-latch old-session rejection, exact
  runtime/profile binding and forged clearance/hash rejection;
- `test_gripper_interface_contract.py` for tool-neutral IDL and removal of AG
  defaults.

The machine-readable persistence design is documented in
`docs/gripper_persistent_safety_latch.md`. It is not wired into the gateway
STOP path and cannot substitute for protected storage, a bounded supervisor or
physical energy isolation.

Under the current permanent boundary, do not run `ros2 launch`, send an Action
goal, call a Service, inspect a graph or use a vendor tool, even for an
otherwise in-memory configuration.

## Unreleased future evidence

The controlled missing inputs are tracked in
`docs/final_gripper_release_input_checklist.md`,
`src/limo_cleanup_executor/config/final_gripper_release_manifest.json` and
`docs/arm_gripper_field_acceptance_matrix.md`. The checked-in manifest keeps
`release_requested=false` and `release_approved=false`.

Release remains blocked on the exact final tool and assembly revision,
actuator/controller/firmware identity, protocol, sole transport owner,
electrical limits, native units, command/opening calibration, TCP, mass, CoM,
inertia, collision/cable envelope, STOP/stationary/ACK semantics and signed
review evidence. CAD filenames and legacy AG parameters cannot fill those
fields.

Supplier documents may continue to be reviewed locally. Physical measurement,
passive identity read, staged power-up or motion acceptance is outside this
task and is currently unauthorized. This document intentionally provides no
field execution sequence and no path to enable a hardware backend. A future
task would require a new, explicit scope and authorization; the present task
must remain local and disconnected.

Gripper position alone would not prove a successful grasp. Any future release
would also need independent pickup, retention and release evidence without
weakening the transport, STOP or physical-energy-isolation requirements.
