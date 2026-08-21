# Voice V2 field acceptance template

This template is for a separately authorized现场 session. Leave every item
unchecked during offline development. Never infer real movement from mock,
parser, or intent success.

Current implementation gate: `BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY`. The only
implemented ROS1 profile is `offline_text_mock`; it rejects ROS publishing and
production outputs. Do not start a field session, connect a production topic,
or mark any section accepted until a separately reviewed Noetic field adapter
exists. Offline Catkin build, private mock graph, prerecorded WAV, or Vosk PASS
does not clear this gate.

## Session identity

- Date/time:
- Operator:
- Safety observer:
- Robot identifier:
- Source revision/archive:
- ROS distro/domain:
- Map identifier and waypoint file:
- Audio source/device:
- Physical emergency-stop check completed: [ ]
- Explicit authorization for this session recorded: [ ]

## Mandatory preflight evidence

- ROS1/Noetic Catkin target build result and source hashes:
- ROS-free adapter/semantic test counts and results:
- Final hashed evidence `status=BLOCKED` reviewed before field work: [ ]
- Field-capable adapter implementation reviewed (not `offline_text_mock`): [ ]
- Default production outputs remain disabled: [ ]
- Read-only preflight JSON attached: [ ]
- `VOICE_BRIDGE_EXACT_PAYLOAD_READONLY_PASS`: [ ]
- Mock/dry-run smoke attached: [ ]
- No residual test processes/nodes: [ ]
- Rollback archive available: [ ]

## Microphone/Vosk acceptance (no motion)

This phase must use a ROS-isolated or no-ROS process. All ordinary intents stay
in memory/mock state, and the before/after executable-output count must be zero.
If the only available profile is `offline_text_mock`, record this phase as
inconclusive rather than changing its locks.

| Phrase/case | Attempts | Correct transcripts | False activations | Notes |
| --- | ---: | ---: | ---: | --- |
| `小莫小莫` + `到垃圾桶旁边去` | | | | pending only |
| `小莫小莫` + `捡矿泉水瓶` | | | | pending only |
| `小莫小莫` + `处理瓶子` | | | | pending only |
| `停下` | | | | |
| `紧急停止` | | | | |
| `到垃圾桶旁边去` | | | | |
| `到这里来` (must be unsupported) | | | | |
| confirmation before timeout | | | | |
| confirmation after timeout | | | | |
| silence/background/ordinary speech | | | | |

- Prerecorded WAV manifest/report attached: [ ]
- Readiness `status=PASS`: [ ]
- Model structure/load/grammar probe passed with hashes: [ ]
- Positive-command exact/CER reported separately from safety: [ ]
- 80-case human negative corpus false-trigger gate attached: [ ]
- Negative-corpus ASR exact/CER attached as a measurement, not a safety gate: [ ]
- Any `INCOMPLETE` / `decoded_not_transcribed` result rejected: [ ]
- Live transcript log attached: [ ]
- Confirmation-timeout statistics attached: [ ]
- False-activation rate:

## Navigation and safe-stop acceptance (separate authorization required)

This section is forbidden while the adapter status remains
`BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY`. A software STOP result does not replace
the physical emergency stop or prove that the robot stopped.

- Voice node publishes only high-level intent, never velocity: [ ]
- Stop payload exactly matches strict schema: [ ]
- STOP request and ACK carry matching `process_instance_id`: [ ]
- ACK source matches the explicit stop-gate allowlist: [ ]
- Future-wall, wrong-source, wrong-process, stale, failed, and expired ACKs rejected: [ ]
- Immediate stop first-publish latency evidence attached: [ ]
- Exactly 3 bounded stop attempts and monotonic sequence/timestamps: [ ]
- 0.75-second debounce boundary evidence attached: [ ]
- Correct ACK/status observable; wrong, failed, or expired ACK rejected: [ ]
- Waypoint payload exactly targets `trash_bin_staging`: [ ]
- Active map and fixed waypoint were independently verified: [ ]
- Navigation cancel result:
- Downstream safe-stop result:
- Physical movement observed and measured:
- Any failure triggered rollback: [ ]

## Final disposition

- [ ] Accepted for the explicitly tested scope only
- [ ] Rejected and rolled back
- [ ] Inconclusive; keep voice deployment disabled

Signatures/notes:
