# Mechanical arm motion release manifest

This is an offline evidence contract, not an authorization to connect or move
the robot. The executable ROS gateway remains dry-run only. The example at
`src/limo_cleanup_executor/config/arm_motion_release.example.json` is
intentionally incomplete and must evaluate as `release_ready=false`.

The validator is
`limo_cleanup_executor.arm_motion_release_manifest`. It uses only the Python
standard library, rejects duplicate/unknown fields, booleans in numeric
fields, non-finite values and malformed hashes, and derives `release_ready`.
The input schema deliberately has no `release_ready` field. Schema version 2
also requires an explicit absolute `artifact_root`; a schema-only in-memory
document can never be release-ready.

## Required release evidence

- Source binding: SHA-256 values for the reviewed API contract, acceptance
  contract, final gateway policy and collision model.
- Runtime binding: exact `runtime_release_id` and
  `release_manifest_sha256`. The acceleration profile must carry the same
  runtime release ID and bind an independently parsed profile artifact through
  `acceleration_profile_manifest_sha256`. The release artifact itself is
  strict JSON and must repeat the exact arm model, profile ID, acceleration
  artifact hash/runtime ID, and all backend capability booleans. Execution
  safety evidence must also repeat the exact runtime-release hash,
  acceleration-profile hash and complete approved speed-grade set; missing,
  stale, forged, case-changed or partially overlapping bindings fail closed.
  An arbitrary hashed file cannot satisfy this gate.
- Final tool: exact model/revision, assembly hash, mass, centre of mass and
  inertia. Motion profiles and every named pose must bind to that revision.
- Coordinates/TCP: controller reference frame/end type, endpoint frame,
  controller tool reference, measured flange-to-TCP transform, uncertainty,
  controller readback and base-extrinsic evidence. Frame and endpoint
  declarations must agree with Cartesian limits.
- Controller state: exact integer connected/power/moving/paused/error/servo/
  fresh-mode readback, including `moving=0` and `paused=0`; multi-sample
  stationary evidence, dwell, joint-change tolerance and freshness window.
  Boolean lookalikes never satisfy integer gates.
- Dynamics: a versioned profile, explicit approved vendor grades and measured
  joint/TCP speed, acceleration and stopping distance for every approved
  grade, TCP path mode, load and pose case. Each measurement must remain within
  a separately declared approved physical maximum. A non-empty profile name
  alone never passes.
- Real backend gate: bounded calls, native deadline enforcement, native
  transport cancellation, an independent STOP channel, and a persistent
  safety latch must all have `enforced=true` and bind by relative path/SHA-256
  to one strict execution-safety JSON artifact. That artifact must enumerate a
  positive finite deadline for every reviewed vendor method, prove distinct
  motion/STOP execution and lock domains, show that a hung motion send does
  not block STOP, and prove that transport cancellation completes within its
  deadline and prevents late command commit. A Python timeout thread is never
  cancellation. It must also prove exclusive persistent-latch creation,
  atomic generation-chain updates, restart restoration, old-session clearance
  rejection, and mandatory external clearance validation without claiming
  that local hashes authenticate an operator. Timeout, STOP, strictly
  increasing stationary samples, ACK and unsuccessful result must correlate
  by one exact command ID and safe timestamp ordering. A STOP return is never
  stationary evidence.
  The released ROS node has no backend-factory injection point and directly
  constructs the in-memory backend. The core reads capability evidence only
  from an exact static `SAFETY_CAPABILITIES` class dictionary; it never calls a
  backend capability method or accepts an instance override. Per-method
  deadlines, independent STOP execution/lock domains and STOP priority are
  required fields, but even fully matching self-declared real metadata remains
  `DISABLED/BLOCKED` without independently verified release attestation.
- Gateway concurrency: injected clocks, validators, command-ID factories and
  backend calls run outside the short state lock. An epoch captured before an
  external call must still match at commit, and motion/ACK freshness is read
  again after slow validators or ID factories return. A late query/send result
  may never overwrite a newer STOP, close, fault or physical-isolation latch.
  STOP must not wait for a normal command's state lock. If the transport itself
  cannot prove bounded native calls and a genuinely independent STOP path,
  software STOP success must not be reported and the release remains
  `DISABLED/BLOCKED` with physical isolation required.
  While a STOP call is in flight, the core reserves its epoch before releasing
  the lock: new motion and duplicate STOP requests are rejected. Close/fault
  may supersede that epoch, and a later STOP success or exception cannot revive
  or overwrite the newer state.
- Limits: six controller and project joint ranges, with every project range a
  strict subset; a positive minimum named-pose joint margin; six Cartesian
  bounds with workspace and IK/collision review. The limits profile and state
  evidence must name the same fresh-mode requirement.
- Named poses: exactly one reviewed pose for each fixed V3 role, all inside
  project limits with a declared positive limit margin, matching tool
  revision, collision evidence and cable-envelope evidence.
- Review: a review ID, reviewer, UTC timestamp and approval artifact hash.

Hashes may be uppercase or lowercase on input and are normalized to lowercase
in the report. Every hash must contain exactly 64 hexadecimal characters.
Every non-null `*_sha256` must be declared by exactly one `artifacts[]` record
whose normalized relative path remains within the selected root, whose real
ordinary file has the declared digest, and whose `claims[]` explicitly names
the exact `manifest....*_sha256` path. Symlinks, missing/non-files, path
escapes, generic hashes without claim scope, and content tampering all block.

Run locally with an explicitly selected Python interpreter:

```text
python -m limo_cleanup_executor.arm_motion_release_manifest \
  <manifest.json> --artifact-root <absolute-disconnected-evidence-directory>
```

Exit `0` means the document and selected local artifacts satisfy this offline
contract, exit `1` means a well-formed release remains blocked, and exit `2`
means the document or artifact input is malformed. Even exit `0` is only
offline evidence; it does not grant a live connection or motion authorization.

The current `PymycobotArmBackend` is intentionally non-operational. It has no
default or dynamic vendor import and no device-open path, requires an explicit
callable `client_factory` before any further validation, never calls that
factory, and finally rejects the reviewed shared-transport topology. The ROS
factory and launch surface continue to accept only `dry_run`.

## Current unresolved inputs

The project still lacks a frozen final tool revision; reviewed acceleration,
speed and stopping-distance cases; final controller/project limits; measured
TCP and base extrinsic; collision/IK/workspace artifacts; frozen named poses;
and a signed approval artifact. Therefore the checked-in example is expected
to remain blocked and must not be populated from brochure values or legacy
gripper assumptions.
