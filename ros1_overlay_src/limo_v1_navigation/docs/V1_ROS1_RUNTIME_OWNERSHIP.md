# V1 ROS1/Noetic provisional runtime ownership contract

Status: `PROVISIONAL_BLOCKED / BLOCKED_ON_VENDOR_INCLUDE`. This is an offline
design contract, not proof of the current vendor include chain or live owner
state. It does not authorize connecting to the robot, starting ROS, opening
serial devices, querying a live ROS graph, or moving the base.

## Runtime baseline

- The default and authoritative field runtime is ROS1 Noetic.
- Native mode is the default. ROS2/Foxy is not assumed to be running.
- ROS2/Foxy may exist as offline source or in an explicitly selected,
  separately verified integrated bridge mode. It may not introduce a second
  base driver, TF owner, velocity chain, navigation stack, or goal owner.
- Exactly one session-owned ROS1 master is permitted. An existing, unknown,
  or duplicate master is `RECORD_AND_BLOCK`.

The machine-readable companion is `V1_ROS1_RUNTIME_OWNERSHIP.json`.

## Vendor include blocker

`launch/v1_base_sensors.launch` includes the external
`$(find limo_bringup)/launch/limo_start.launch`. The current allowed local
workspaces do not contain that vendor file, its recursively included
`limo_base.launch` and `Tmini.launch`, or a current roslaunch expansion.
Therefore the rows below are expected owners, not a claim that the current
installed vendor package has been closed or that the live graph was checked.

A 2026-08-11 historical record reports `limo_start.launch` as 1061 bytes with
SHA-256 `acd80d07a8169ef15d805a365d1ae72615ced51db32ccf7f5ec94719fede0682`,
including `limo_base.launch`, `Tmini.launch`, and three rate-based static TF
publishers. The raw bytes were not archived locally, so this is provenance,
not a current hash verification. See `V1_ROS1_VENDOR_INCLUDE_BLOCKER.json` for
the exact closure inputs. The historically reported node name
`/base_link_to_laser_link` and `/tf` transport are candidates only, not a
runtime allowlist. Static wrapper remaps cannot substitute for those inputs.

The runtime and perception-only loaders do not accept a rule-level provenance
claim. They require three independent absolute files with schemas
`limo_v1_ros1_vendor_source_manifest/v1`,
`limo_v1_ros1_vendor_tf_publisher_pin/v1`, and
`limo_v1_ros1_vendor_tf_rules/v2`, plus the installed blocker whose exact
bytes are hash-anchored by the reviewed topology-policy source. The blocker
must already be `VERIFIED`; the current anchored blocker is deliberately
`BLOCKED_ON_VENDOR_INCLUDE`, so no supplied rules can pass this release.

A future reviewed release must rehash the three manifests, every raw launch
artifact in the recursive include chain, and the publisher executable. Each
`$(find package)/path` include must bind its declared child logical path, the
graph must be complete and acyclic, and parsed static-TF callerid, edge, exact
topic, and periodic-or-latched behavior must equal the publisher pin and rules
manifest. Unsupported namespace, substitution, conditional, or topic-remap
semantics fail closed. Correctly formatted fake hashes and
`provenance_verified=true` never establish provenance. Any missing, blocked,
unanchored, byte-mismatched, or semantically inconsistent artifact returns
`TF_VENDOR_CONTRACT_UNVERIFIED`.

The future blocker/release approval package must additionally archive
`rospack find` package roots and the exact `roslaunch --files`,
`roslaunch --nodes`, and `roslaunch --dump-params` outputs for the reviewed
arguments. These dumps are release-review-only evidence. The loader does not
consume them, and their existence does not automatically close the blocker or
produce a runtime PASS. Human release review must bind them to the same source
bytes before approving a new trusted blocker hash.

The runtime machine gate is independent: it requires the trusted blocker hash,
three separate artifacts and every referenced raw byte stream, and accepts
only its strict supported ROS launch XML subset. Each manifest path must equal
the package root resolved by `rospack find`; the publisher executable must be
the one unique path returned by `roslib.packages.find_node` and equal the pin.
Any unmodelled include argument, remap, namespace/condition/substitution,
`launch-prefix`, ambiguous executable, or package-path mismatch fails closed.
An absolute path, package/type text, historical node name, or runtime callerid
alone is not proof.

## Stage-specific TF authority

| Stage | `map -> odom` | `odom -> base_link` | `base_link -> laser_link` |
|---|---|---|---|
| sensing only | absent | target `/limo_base_node`, dynamic `/tf` | owner/topic `PROVISIONAL_BLOCKED_ON_VENDOR_INCLUDE` |
| mapping only | target `/slam_gmapping`, dynamic `/tf` | target `/limo_base_node`, dynamic `/tf` | owner/topic `PROVISIONAL_BLOCKED_ON_VENDOR_INCLUDE` |
| localization | target `/amcl`, dynamic `/tf` | target `/limo_base_node`, dynamic `/tf` | owner/topic `PROVISIONAL_BLOCKED_ON_VENDOR_INCLUDE` |
| native navigation | target `/amcl`, dynamic `/tf` | target `/limo_base_node`, dynamic `/tf` | owner/topic `PROVISIONAL_BLOCKED_ON_VENDOR_INCLUDE` |

These are target edge rules, not a statement that the current installed
vendor launch or a live graph has been verified. In particular,
`base_link -> laser_link` has static semantics, but its current authority and
its selected transport remain unresolved. A verified installed publisher pin
must select exactly one of legacy periodic `/tf` or latched `/tf_static`;
observing either topic at runtime cannot choose or create that pin.

Gmapping is permitted only in the explicit mapping stage. It is forbidden in
localization and navigation because AMCL owns the same `map -> odom` edge.
Cartographer is not part of this V1 runtime. `robot_pose_ekf` is forbidden in
every stage because the base driver already owns `odom -> base_link`.

## Edge-level TF evidence contract

TF lookup proves only that a transform chain can be resolved. It does not
prove which connection published an individual edge, whether that edge came
from `/tf` or `/tf_static`, or whether another parent, authority, or transport
also published the same child frame.

The field and runtime-preflight capture contract therefore handles every
`tf2_msgs/TFMessage` one transform at a time. Each observation records the
normalized parent frame, child frame, connection-header `callerid`, the exact
callback-bound topic (`/tf` or `/tf_static`), source stamp, monotonic receipt
time, and a geometry fingerprint. The protected children are `odom`,
`base_link`, and `laser_link`.

For a required protected child there must be exactly one parent, one
authority, and one topic during the bounded evidence session. The following
all fail closed, even when TF lookup succeeds:

- two authorities for one child or one edge;
- one edge observed across both `/tf` and `/tf_static`;
- a wrong parent or child, including a conflicting edge from the same node;
- an alias authority publishing the otherwise correct edge;
- a dynamic edge on `/tf_static`, a static publisher on a transport not
  selected by its verified pin, or changing geometry for a static edge;
- a missing/empty `callerid`, an unverified vendor authority, or missing
  required edge evidence.

Dynamic `map -> odom` and `odom -> base_link` edges are `/tf`-only and require
finite advancing source stamps plus fresh receipt/source timing. A verified
legacy static publisher on `/tf` requires repeated fresh receipts, advancing
stamps, and invariant geometry. A verified latched publisher on `/tf_static`
may legitimately use a zero or old source stamp; that stamp is not checked
against the dynamic 0.5-second freshness limit, but at least one session
observation, invariant geometry if repeated, and a still-present graph owner
are required.

This edge policy is enforced only by the bounded runtime-preflight and
perception-only field capture paths. It is not claimed as a continuous guard
or localization-READY monitor. A preflight edge PASS is a timestamped snapshot
and does not make covariance READY proof of ongoing TF ownership.

## Authoritative process, node, and topic owners

| Component | Canonical owner | Authoritative endpoints | Cardinality | Wrong or duplicate result |
|---|---|---|---|---|
| ROS1 master | one session-owned `roscore/rosmaster`, canonical `/rosout` | ROS1 master URI and `/rosout` | exactly one | fail closed |
| base driver | `/limo_base_node` | publishes `/odom`; owns `odom -> base_link`; consumes `/v1/driver_cmd_vel` | exactly one | fail closed |
| lidar | `/ydlidar_lidar_publisher` | sole `/scan` publisher | exactly one | fail closed |
| laser static TF | unresolved; historical candidate `/base_link_to_laser_link` only | static `base_link -> laser_link`; owner and exact `/tf` versus `/tf_static` transport require a verified installed publisher pin | exactly one parent/owner/topic after pin | blocked until pin; then fail closed on mismatch |
| mapping SLAM | `/slam_gmapping` | mapping-only `/map`, `/map_metadata`, `map -> odom` | exactly one in mapping only | fail closed elsewhere |
| map server | `/map_server` | sole `/map` and `/map_metadata` publisher in localization/navigation | exactly one | fail closed |
| localization | `/amcl` | sole `/amcl_pose`, `/particlecloud`, and `map -> odom` owner | exactly one | fail closed |
| planner and costmaps | `/move_base` | private move_base action; global/local costmaps; sole `/v1/nav_cmd_vel` publisher | exactly one; costmaps are internal | fail closed |
| localization manager | `/v1_localization_manager` | sole public `/initialpose` consumer and `/v1/validated_initialpose` publisher; owns localization READY/status | exactly one | fail closed |
| native goal gateway | `/v1_navigation_gateway` | public V1 goal/cancel ingress and sole private move_base action client | exactly one | fail closed |
| native velocity guard | `/v1_cmd_guard` | sole `/v1/nav_cmd_vel` consumer and `/v1/driver_cmd_vel` publisher | exactly one | fail closed |
| public velocity surface | none | `/cmd_vel` | zero publishers and zero subscribers | any endpoint fails closed |

Costmaps are plugins and namespaces owned by `/move_base`; they are not
separate process owners. A second move_base instance also means a second
planner, costmap, action server, and velocity source and must be blocked.

## Native ROS1 chains

The only accepted velocity chain is:

```text
/move_base -> /v1/nav_cmd_vel -> /v1_cmd_guard
           -> /v1/driver_cmd_vel -> /limo_base_node
```

The only accepted native goal/action chain is:

```text
/v1/navigation/goal -> /v1_navigation_gateway
                    -> /v1/private_move_base/* -> /move_base
```

Public `/move_base_simple/goal`, public `/move_base/*`, and public `/cmd_vel`
are absent in native mode. The private action goal and cancel publishers must
be exactly `/v1_navigation_gateway`; status may be consumed only by the
gateway and localization manager as frozen by the topology policy.

## Explicitly forbidden or mutually exclusive runtime owners

The following are blockers, not warnings:

- `/amcl_*`, `/map_server_*`, `/move_base_*`, or `/limo_base_node_*` aliases
  in addition to the canonical instance;
- `/slam_gmapping` or `/cartographer_node` during localization/navigation;
- `/robot_pose_ekf` in any stage;
- any public `/cmd_vel` publisher or subscriber;
- the legacy `limo_navigation_diff.launch` or another combined vendor launch
  that can spawn duplicate map server, AMCL, EKF, RViz, or velocity surfaces;
- a ROS2/Foxy base driver, Nav2 stack, or duplicate ROS2 TF/velocity owner in
  the native field runtime;
- bridge adapter/watchdog owners in native mode, or native gateway/guard
  owners in explicit integrated mode.

Missing canonical owners, extra aliases, wrong action owners, double topic
owners, inactive-mode endpoints, or a mode mixture all revoke readiness and
block command forwarding. Software PASS or a launch boolean cannot override
this ownership decision.

## Enforcement and evidence limits

The navigation topology code strictly checks the action and velocity surfaces
and rejects the documented canonical `_` aliases plus the named SLAM,
Cartographer, and EKF processes. It is not an arbitrary process-identity
scanner: names such as `/legacy_amcl` or a namespaced AMCL require endpoint and
edge evidence, and `navigation=false` does not by itself prove that every
private navigation process is absent. Generic ROS master topic-owner checks do
not substitute for the per-message TF edge capture, and neither path
attributes the `/request_nomotion_update` service provider.

Consequently, the table remains a fail-closed target contract. Closing it
requires a newly reviewed blocker trust anchor, the three byte-bound vendor
artifacts, the raw source/include chain and installed-publisher executable,
followed by a separately authorized runtime owner audit whose structured edge
report passes.
Until both exist, runtime ownership is `UNKNOWN/BLOCKED`, even when all offline
software tests pass or a TF lookup succeeds.
