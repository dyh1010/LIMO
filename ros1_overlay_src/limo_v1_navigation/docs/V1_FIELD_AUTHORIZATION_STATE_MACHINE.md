# V1 field authorization state machine

Status: prepared offline. All real-machine stages are `NOT_RUN` and
`BLOCKED`. This document and its companion JSON template are checklists only;
they do not authorize opening a device, starting a real-machine process, or
moving the base.

The checklist is an offline approval packet for later human and orchestrator
review. It is not a runtime authorization validator, token, lease, or active
authorization context.

## 1. Current release boundary

The frozen V1 package has safe default gates, but it does not contain a
dedicated field-authorization orchestrator that validates a user grant,
atomically consumes it, binds it to the current robot boot and session, and
rechecks it immediately before a hardware or motion boundary. Therefore all
three field classes have this fixed current result:

```text
status=NOT_RUN
execution_ready=false
decision=BLOCKED
block_reason=dedicated_field_authorization_orchestrator_not_present
```

Editing a checklist, filling a JSON field, or obtaining an offline test PASS
must never change that result. A future trusted orchestrator must produce a
separate runtime record; this template cannot be promoted into one.

## 2. Inputs that are not authorization validators

The following existing controls remain useful local safety gates, but none of
them validates a fresh user grant:

- `hardware_authorization_id` is a launch argument. The current launch checks
  only that it differs from `NOT_AUTHORIZED`; it does not validate issuer,
  boot, session, robot, operator, scope, issue time, expiry, consumption, or
  revocation.
- `/v1_localization_manager/authorize_initial_pose` is a ROS Trigger that
  opens one short, process-local initial-pose window. It does not prove that
  the user granted a zero-motion field session.
- `enable_hardware`, `enable_localization`, `enable_navigation`,
  `allow_nonzero`, `driver_timeout_verified`, `enable_goal_gateway`, and
  `allow_goal_forwarding` are launch/runtime booleans. A true value is not
  evidence of user approval.
- READY, a preflight token, a software stop, a cancellation result, an offline
  PASS, a prior field PASS, or a completed checkbox is not an authorization.

These controls may be necessary after authorization, but they are never
sufficient to establish it.

## 3. Independent grant model

There are exactly three grant classes:

1. `hardware_read_only`
2. `zero_motion_localization`
3. `real_motion`

Every requested stage requires a newly issued one-use bundle. Higher stages do
not inherit authority from a lower-stage grant or PASS:

| Requested stage | Fresh grants required for that stage entry |
|---|---|
| `hardware_read_only` | new `hardware_read_only` grant |
| `zero_motion_localization` | new `hardware_read_only` grant plus new `zero_motion_localization` grant |
| `real_motion` | new grants for all three classes, including a new `real_motion` grant for the exact trial |

The repeated lower-class grants are deliberate. They bind the higher stage to
the current boot, session, robot, operator, scope, and time window; an earlier
consumed grant or PASS cannot be reused as an upgrade.

Each grant record must contain, without placeholders:

- exact authorization class and unique authorization ID;
- direct approval reference;
- current boot ID, field session ID, robot ID, operator, and physical-stop
  observer;
- exact stage scope, permitted operation IDs, map/evidence binding, and trial
  IDs where applicable;
- issue and expiry timestamps in UTC;
- `one_use=true`, `consumed=false`, and `revoked=false` before admission;
- derived freshness checks proving that issue time is not in the future,
  expiry is still strictly later than validation time, and boot/session/robot/
  scope all match.

A blank or unknown value is a failure, not a wildcard. A grant is invalid when
any required field is missing, its approval reference cannot be verified, it
is not yet valid, it is expired, identity or scope differs, `one_use` is not
true, it was already consumed, or it was revoked.

## 4. Fail-closed states and transitions

A future orchestrator should derive grant state; it must not trust a
self-declared `valid` field.

| State | Meaning | Permitted transition |
|---|---|---|
| `NOT_RUN` | Offline template only | Remain blocked |
| `MISSING_OR_INVALID` | Required data, identity, time, scope, physical boundary, or approval evidence failed | Remain blocked; obtain a completely new grant |
| `VALID_UNUSED` | All fields and independent evidence validate for one exact stage entry | Atomic consumption only |
| `ACTIVE_EXACT_SCOPE` | The complete stage bundle was consumed atomically and a separate active context is bound to the same boot/session/robot/scope/expiry | Complete the exact stage, revoke, or expire |
| `CONSUMED` | The token was used once | Never admit another stage or retry |
| `REVOKED` | User or safety lead withdrew authority | Block immediately; require a new grant after physical review |
| `EXPIRED` | Current time reached or exceeded expiry | Block immediately; require a new grant |
| `IDENTITY_OR_SCOPE_DRIFT` | Boot, process session, robot, operator, map, trial, or permitted operation changed | Revoke the active context and block |

Validation is required both at admission and immediately before the boundary
that opens a device, accepts an initial pose, or permits a real movement. The
orchestrator must atomically consume every grant in the requested-stage bundle
before creating the active context. A consumed token may not create a second
context, even in the same process.

No such orchestrator exists in the current release, so `VALID_UNUSED` and
`ACTIVE_EXACT_SCOPE` are design states only and cannot be claimed from the
companion template.

## 5. Class contracts

### `hardware_read_only`

Intended future scope is limited to the exact approved hardware/session audit,
approved sensor and owner observation, and finite subscriber-only evidence
capture. Initial-pose administration, localization reset, motion authority,
manual driving, automatic rotation, recovery, and fault injection are outside
this class.

Required physical boundary: an on-site operator and named observer remain at
the physical e-stop/main switch, the stop/isolation path is identified and
checked for the session, people and loose objects are clear, and the base is
lifted or effectively restrained. Opening a serial device is still a hardware
operation and is not authorized by a read-only host audit alone.

### `zero_motion_localization`

This stage requires a new `hardware_read_only` grant and a separate new
`zero_motion_localization` grant. Its exact scope may include one explicit
initial pose, manager-owned bounded no-motion updates, convergence/status
observation, stationary repeatability, and stationary absolute-localization
measurement. It must keep all motion-capable ingress disabled.

Permission for sensing does not authorize initial-pose administration, and a
successful localization PASS does not authorize movement. The base remains
physically restrained and the physical-stop observer remains present.

### `real_motion`

This stage requires a new three-grant bundle and a separate `real_motion`
grant for one predeclared trial. The scope must name the mode, map, start and
end bounds, trial ID, maximum limits, evidence paths, operator, observer, and
stop criteria. Approval for one point-to-point, cancellation, static-obstacle,
or dynamic-obstacle trial does not cover a retry, another trial type, a new
endpoint, teleoperation, automatic recovery, or fault injection.

Before any movement, the area and full path envelope must be clear except for
the approved soft obstacle setup, the on-site observer must have immediate
control of the physical e-stop/main switch, and the independent physical stop
path must have been checked for that session. Software stop, cancellation,
zero output, READY loss, or process shutdown supplements but never replaces
physical emergency stopping or power isolation.

## 6. Revocation, expiry, and abnormal observations

Revocation or expiry prevents every new stage entry and invalidates any
pending boundary. Identity drift, an unexpected owner/endpoint, missing
heartbeat, scope deviation, unexpected movement, or an unverified physical
stop path has the same fail-closed result.

For a real-machine active context, software should block new work and request
the reviewed stop path, but the on-site operator remains responsible for the
physical e-stop or power isolation when movement is unexpected or software
state is uncertain. Software shutdown is not proof that the machine is safe.

After completion, block, revocation, expiry, or abnormal termination, record
the final physical state and cleanup evidence. A retry always requires a new
one-use bundle; it never reopens the old context.

## 7. Machine-readable checklist

The companion file is
`docs/examples/v1_field_authorization_checklist_template.json`. It deliberately
contains blank grant records, `template_only=true`, `real_machine_evidence=false`,
`status=NOT_RUN`, `execution_ready=false`, and `decision=BLOCKED`.

The template contains no executable ROS invocation or motion transport. Its
stage lists are identifiers for review only. A future implementation should
validate a copied record against a separately frozen schema, verify the direct
approval source, create an immutable evidence record exclusively, and keep the
template itself unchanged.

## 8. Required offline contract tests

Static tests must continue to prove:

- exactly three independent grant classes and no class substitution;
- a fresh bundle for every stage entry and no upgrade inheritance;
- all required identity, scope, issue/expiry, one-use, consumption, revocation,
  and freshness fields exist for each grant class;
- missing, future-issued, expired, reused, revoked, identity-mismatched,
  scope-mismatched, or unverified grants remain blocked;
- lower-stage PASS never authorizes a higher stage;
- the template and all three stages remain `NOT_RUN/BLOCKED` with
  `execution_ready=false` while the dedicated orchestrator is absent;
- the checklist is data only and contains no ROS or movement invocation.
