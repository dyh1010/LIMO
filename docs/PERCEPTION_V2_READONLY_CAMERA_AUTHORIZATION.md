# V2 perception read-only camera authorization checklist

This document defines the narrow camera-only authorization. The current V2
session has explicit user approval for ROS1 Noetic camera queries, bounded
sensor-only start/stop, ROS1 bag capture, offline inference and evidence
writes. It never authorizes motion or non-camera control. Current state:

```yaml
authorization_active_in_this_template: true
current_task_authorization_recorded_externally: true
delivery_ready: false
read_only: true
authorizes_motion: false
publishes_control_messages: false
```

## Authorization identity and physical preconditions

All boxes must be completed for one bounded session. A new session requires a
new authorization ID and new evidence paths.

- Authorization ID:
- Authorizing person:
- Operator:
- Robot/camera identity:
- Approved start/end time window:
- Four approved scene capture IDs:
- New, absent evidence root:
- Physical emergency-stop location verified:
- Physical power-disconnect method verified:
- Operator identifies any parallel non-camera nodes without asking this
  procedure to stop or operate them; a shared /tf capture is diagnostic-only:
- The frozen camera launch source/argv dependency audit contains no control
  package, executable, topic, action, service, or bridge:
- No UART, tty, actuator, base, navigation, arm, or gripper device path was
  opened, probed, enumerated, or queried by this camera procedure:
- On-site observer confirms that software stop is not being treated as a
  substitute for physical emergency stop or power isolation:

Authorization is invalid if any identity, time-window, isolation, or physical
safety field is empty. Expiry or a changed graph/source/model/camera setup
requires stopping capture and obtaining a fresh authorization.

## Operations that may be authorized

Only these read-only evidence operations are in scope:

- open the pre-approved RGB-D camera for the bounded time window;
- subscribe to RGB image, raw/aligned depth, both CameraInfo streams, `/tf`, and
  `/tf_static`;
- record a new ROS1 rosbag v2 containing exactly the installed frozen ROS1
  six-topic manifest, with no aliases or additional topics;
- run bottle and trash-bin inference without connecting its outputs to a
  motion consumer;
- normalize stopped ROS1 bag messages into typed observations offline;
- create new collector, raw-index, typed/raw-binding, annotation,
  measurement, evaluator, and readiness evidence files exclusively;
- stop the camera/recorder normally and perform offline ROS1 indexing, hash
  binding, inference replay, evaluation, and readiness checks.

These operations may read sensor/TF messages and write evidence artifacts.
They do not authorize arbitrary ROS graph access or any publisher/action/
service outside an already reviewed, perception-only output surface.

Remote device metadata queries are narrower still. They must come verbatim
from the installed `dabai_camera_query_allowlist.json`, operate on exactly one
pre-identified DaBai persistent link, and use only non-recursive `readlink`,
`stat`, or `udevadm info`. Recursive sysfs traversal, `find -L`, global USB or
process enumeration, and any UART/tty/control-path query are forbidden.

## Operations never authorized here

This checklist never authorizes:

- publishing `Twist`, navigation goals, trajectories, gripper commands, arm
  commands, action goals, services, or any other control message;
- starting or connecting the base, navigation stack, MoveIt, cleanup
  executor, arm, gripper, vendor follow, command bridges, or actuator drivers;
- opening actuator UART/serial devices or sending hardware commands;
- `rosbag play`, replay into a live graph, or routing visual observations to
  navigation, task execution, base, arm, or gripper consumers;
- recording extra or aliased topics instead of the exact frozen six-topic
  set;
- a fabricated TF JSON, `frame_id_override`, string-only frame claim, or any
  substitute for decoded `/tf` and `/tf_static` payloads;
- overwriting, appending to, renaming over, or silently refreshing an existing
  evidence artifact;
- any nonzero real motion, including a seemingly harmless base, arm, or
  gripper probe.

If an operation outside the allowed list becomes necessary, stop and request
a separate explicit authorization. In particular, visual evidence must remain
read-only and must never be used to command motion.

## Per-session closeout

- Camera and recorder stopped:
- No process from this procedure remains attached to hardware:
- No control publisher/action/service was created:
- No motion or actuator command was issued:
- Evidence files were exclusively created and hashed:
- Exact frozen manifest ID/path/size/SHA-256 recorded:
- Four scenes remain independent and each targets at least 30 unique complete
  typed/raw-bound frames:
- Any interruption, duplicate, missing stream, unexpected topic, or safety
  uncertainty recorded as FAIL rather than waived:
- Authorization closed by / at:

Even a fully completed authorization record does not establish perception
delivery readiness. Build, runtime, hardware, four-scene truth/TF/XYZ/depth/
latency evidence and the final fail-closed readiness report must still pass.
