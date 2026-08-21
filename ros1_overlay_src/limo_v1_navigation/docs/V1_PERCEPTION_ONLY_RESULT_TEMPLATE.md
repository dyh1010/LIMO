# V1 perception-only field result

Status: `NOT_RUN / BLOCKED_ON_VENDOR_INCLUDE` (`PASS` or `BLOCK` only after
the on-robot procedure and verified vendor/publisher pin)

This record covers sensing only. It does not authorize teleop, SLAM, AMCL,
`move_base`, map loading, command publication, or robot motion.

## Session identity

- Date/time/timezone:
- On-site operator:
- Main-task authorization ID:
- Robot hostname/IP (record only; do not place credentials here):
- V1 overlay revision/SHA:
- Installed blocker path, SHA-256, schema, and status:
- Vendor recursive source manifest path, SHA-256, schema, and status:
- Installed static-TF publisher pin path, SHA-256, schema, and status:
- TF rules manifest path, SHA-256, schema, and status:
- Raw launch artifact path/logical-path/SHA-256 inventory:
- Publisher executable path/package/node-type/SHA-256:
- Release-review-only `rospack find` evidence paths and SHA-256:
- Release-review-only `roslaunch --files` / `--nodes` / `--dump-params` evidence paths and SHA-256:
- Release-review approval evidence ID and resolved-node disposition:
- Runtime machine-gate `rospack find` and unique `find_node` verdict:
- Byte-and-semantic binding verdict:
- Vendor contract diagnostic (`TF_VENDOR_CONTRACT_UNVERIFIED` on failure):
- Pinned callerid/topic/temporal semantics:
- Raw JSON result path and SHA-256:

The release-review-only fields above are references for the human blocker and
release approval record. They are not runtime loader inputs and do not create a
PASS. The loader records only its independent machine-gate result.

## Read-only precheck

| Check | Evidence | PASS/BLOCK |
| --- | --- | --- |
| ROS/base/lidar/navigation process match is empty | | |
| ROS master is absent before the owned run | | |
| `/dev/ttyTHS0` exists and has no owner | | |
| `/dev/ydlidar` exists and has no owner | | |
| No `cmd_vel`-like publisher exists | | |

Any non-empty process, existing ROS master, device owner, missing device, or
velocity publisher is an immediate `BLOCK`; do not stop or kill unknown work.

## Perception-only runtime

Exact command used:

```text
<paste command; redact no evidence fields except credentials, which must never be present>
```

| Check | Required | Measured evidence | PASS/BLOCK |
| --- | --- | --- | --- |
| Forbidden nodes | teleop/Gmapping/Cartographer/AMCL/move_base/map_server/robot_pose_ekf/bridge/V1 guard absent | | |
| `/scan` owner | exactly `/ydlidar_lidar_publisher` | | |
| `/scan` frame | every sample `laser_link` | | |
| `/scan` frequency | `4.8 <= Hz <= 7.2`, 30 samples | | |
| `/scan` angles | min `-100 deg`, max `+100 deg`, tolerance `0.5 deg` | | |
| `/scan` stamps | finite, strictly increasing; source age `[-0.1, 0.5) s` | | |
| `/odom` owner | exactly `/limo_base_node` | | |
| `/odom` frames/stamps | `odom/base_link`, 10 finite strictly increasing stamps | | |
| TF observation fields | every `TFMessage` transform records parent, child, connection `callerid`, callback-bound topic, source stamp, monotonic receipt, geometry fingerprint | | |
| protected-child cardinality | each required `odom`, `base_link`, `laser_link` child has exactly one parent and one authority | | |
| cross-topic duplicate | no edge appears on both `/tf` and `/tf_static` | | |
| `odom -> base_link` | target `/limo_base_node`; dynamic `/tf`; finite advancing fresh source stamps and fresh receipts; lookup succeeds | | |
| `base_link -> laser_link` pin | exact verified installed callerid and one selected transport; historical `/base_link_to_laser_link` is candidate only | | |
| `base_link -> laser_link` behavior | static geometry; pinned legacy `/tf` is periodic with advancing stamps, or pinned `/tf_static` is latched and not dynamic-source-age gated | | |
| `map -> odom` | absent in sensing-only stage | | |
| public `/cmd_vel` | zero publishers and zero subscribers | | |
| `/v1/driver_cmd_vel` | zero publishers; sole subscriber `/limo_base_node` | | |
| all cmd_vel-like topics | zero publishers | | |

One failed or missing measurement makes the entire runtime result `BLOCK`.
An unknown/alias authority, wrong parent/child, same-child multi-owner,
cross-topic duplicate, missing pin, or static/dynamic behavior mismatch is a
hard block even if tf2 lookup succeeds. It must not be described as an
on-robot PASS if the script was only dry-run or read-only.

## Stop and cleanup

| Check | Evidence | PASS/BLOCK |
| --- | --- | --- |
| Only the process group started by this procedure was stopped | | |
| ROS/base/lidar/navigation process match returned to empty | | |
| Owned ROS master disappeared | | |
| `/dev/ttyTHS0` owner returned to empty | | |
| `/dev/ydlidar` owner returned to empty | | |

If any process, ROS master, or device owner remains, record `BLOCK`, leave
unknown processes untouched, and escalate to the main task/on-site operator.

## Final decision

- Final status: `NOT_RUN` / `PASS` / `BLOCK`
- Installed blocker status: `MISSING` / `BLOCKED` / `VERIFIED`
- Source manifest status: `MISSING` / `BLOCKED` / `VERIFIED`
- Publisher pin status: `MISSING` / `BLOCKED` / `VERIFIED`
- TF rules manifest status: `MISSING` / `BLOCKED` / `VERIFIED`
- Release-review resolution evidence: `MISSING` / `UNAPPROVED` / `APPROVED`
- Runtime package-root/unique-executable gate: `NOT_RUN` / `TF_VENDOR_CONTRACT_UNVERIFIED` / `VERIFIED`
- Artifact binding verdict: `NOT_RUN` / `TF_VENDOR_CONTRACT_UNVERIFIED` / `BYTE_AND_SEMANTIC_MATCH`
- Edge policy enforcement scope: `PERCEPTION_ONLY_FIELD_CAPTURE`
- Continuous guard/READY TF-edge proof claimed: `false`
- Blockers:
- Operator notes:
- Explicit statement: `No teleop, Gmapping, AMCL, move_base, map_server, or velocity publisher was started.`
