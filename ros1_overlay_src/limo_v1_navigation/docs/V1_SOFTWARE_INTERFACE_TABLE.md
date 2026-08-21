# V1 software interface freeze

This table freezes the software-facing V1 localization and navigation contract
for vision, voice, and later orchestration consumers. Compatibility is
additive-only within `limo_v1_software_interface/v1`: existing names, message
types, directions, default safety state, and payload schemas must not change.

The authoritative machine-readable manifest is
`config/v1_software_interface.json`; its draft 2020-12 schema is
`config/v1_software_interface.schema.json`. The supplied fixture is mock-only
and is not real-machine evidence.

## Read-only consumer interfaces

| Name | Type | Nominal period / stale boundary | Meaning |
|---|---|---|---|
| `/v1/localization/ready` | `std_msgs/Bool` | 0.10 s / 0.50 s | Covariance/stability READY gate. It is not proof of absolute localization accuracy. |
| `/v1/localization/status` | `std_msgs/String` JSON | 0.10 s / 0.50 s | `limo_v1_localization_status/v1`; state, reason, chain health, convergence evidence, covariance, and estimate. |
| `/v1/localization/diagnostics` | `std_msgs/String` JSON | 0.10 s / 0.50 s | Same frozen payload schema as localization status, provided as a diagnostics stream. |
| `/v1/navigation/status` | `std_msgs/String` JSON | 0.10 s / 0.50 s | `limo_v1_navigation_status/v1`; arm, READY health, action-server state, active request, cancellation and guard state. |
| `/v1/navigation/error` | `std_msgs/String` JSON | event-only / not a heartbeat | `limo_v1_navigation_error/v1`; latest fail-closed rejection/error record. Its age or absence cannot establish current health. |
| `/v1/cmd_guard/stop_latched` | `std_msgs/Bool` | 0.10 s / 0.50 s | Native software stop-latch heartbeat. It is not a physical emergency stop or power disconnect. |
| `/cleanup/navigation/bridge_status` | `std_msgs/String` JSON | 0.05 s / 0.25 s | Integrated-only `cleanup_navigation_bridge/v3` internal status/result heartbeat. It is read-only and is not an action ingress. |

Consumers should subscribe only to the entries above. They must treat a
missing/stale status, `ready=false`, `guard_latched=true`, or a non-READY state
as unavailable. Unknown fields may be ignored for additive compatibility, but
missing required fields, invalid JSON, an unknown discriminator, or a stale
heartbeat must be interpreted as `NOT_READY/BLOCKED`. Monotonic timestamps are
process-local and must not be compared across processes. Covariance READY must
never be presented as centimetre-level absolute accuracy.

Freshness uses the consumer's monotonic receipt time: a heartbeat is fresh
only while `0 <= receipt_age_s < freshness_timeout_s`; equality is stale.
The first sample from a latched native heartbeat is only a snapshot and does
not establish publisher liveness; require a following live heartbeat before
declaring it fresh. Integrated bridge status is not latched, so its first
healthy received frame can establish liveness. Consumers should use the
gateway/adapter's fail-closed aggregate fields instead of re-deriving scan,
TF, READY, or guard freshness from unrelated topics.

## Controlled command interfaces

| Name | Type | Default | Boundary |
|---|---|---|---|
| `/v1/navigation/goal` | `geometry_msgs/PoseStamped` topic | Disabled | Native only; requires gateway enabled, forwarding enabled, fresh READY, fresh unlatched guard, and explicit arm. May cause motion. |
| `/v1/navigation/cancel` | `std_msgs/Bool` topic | Disabled | Requests cancellation; software cancellation is not a physical e-stop. |
| `/v1_navigation_gateway/arm` | `std_srvs/Trigger` service | Disabled | Opens one READY/guard-gated native goal path. May enable motion after a goal. |
| `/v1_navigation_gateway/cancel` | `std_srvs/Trigger` service | Disabled | Requests cancellation and leaves the gateway disarmed. |
| `/v1_localization_manager/authorize_initial_pose` | `std_srvs/Trigger` service | Disabled | One-shot authorization; does not move the robot. |
| `/initialpose` | `geometry_msgs/PoseWithCovarianceStamped` topic | Disabled | Accepted only after explicit one-shot authorization; no pose is guessed. |

Vision, voice, and orchestration must not call controlled command interfaces
unless a later, separately authorized integration explicitly grants that role.
The read-only fixture contains none of these calls.

## Private action ownership

| Mode | Action prefix | Sole action client | Forbidden owner | Stop/READY boundary |
|---|---|---|---|---|
| native | `/v1/private_move_base` | `/v1_navigation_gateway` | bridge adapter | Fresh localization READY plus fresh unlatched V1 guard; READY loss or stop cancels and disarms. |
| integrated | `/move_base` | `/cleanup_ros1_navigation_adapter` | V1 gateway | Adapter navigation health plus exact bridge/watchdog topology; health loss invalidates/cancels. |

The integrated `/move_base` namespace is an internal channel created inside
the bridge runner's private launch. It is not a public consumer entry. The two
action owners and action namespaces are mutually exclusive, and wrong, double,
or missing ownership is fail-closed.

## Accuracy boundary

AMCL estimation error, navigation control endpoint error, physical total
endpoint error, and repeatability are separate measurements. The status
fixture demonstrates only schema consumption; it cannot establish any of
those real-machine metrics or complete V1 field acceptance.
