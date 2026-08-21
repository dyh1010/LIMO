# Voice V2 offline and field acceptance runbook

## Safety boundary

The deterministic fixture is the only step authorized during ordinary offline
development. It does not initialize ROS, enumerate audio devices, connect to a
robot, or publish to a topic. Ordinary navigation, cleanup, bottle, arm, and
gripper requests remain mock state only.

Software voice stop is a high-level cancel and safe-stop request. It does not
replace the on-site physical emergency stop or power isolation. Any session
that connects a live ROS graph, navigation bridge, base, arm, gripper, or other
device requires explicit authorization for that session before connection or
execution. A previous authorization cannot be reused.

## Deterministic offline fixture

Run from a sourced development or installed workspace:

```bash
bash src/limo_cleanup_voice/scripts/run_voice_offline_acceptance.sh \
  src/limo_cleanup_voice/fixtures/voice_offline_acceptance_fixture.json \
  /tmp/voice_offline_acceptance.json
```

The output path is created exclusively and is never overwritten. A passing
report must state all of the following:

- `mode=deterministic_offline_mock_no_ros_no_hardware`;
- `live_ros_used=false` and `hardware_used=false`;
- zero false activations for noise, near-soundalike, negated, and unwoken cases;
- every ordinary intent creates only pending confirmation and is not forwarded;
- confirmation after the configured timeout is blocked and pending state clears;
- stop produces attempt sequence `1,2,3`, monotonic timestamps, exact bounded
  repeats, a debounced duplicate below `750 ms`, and a new event at the exact
  `750 ms` boundary;
- the correlated successful ACK and final `relay_acknowledged` status are
  observable;
- the report contains no Twist, device path, action/service client, or other
  direct hardware command contract.

The synthetic latency is a contract check, not an acoustic or deployed-system
measurement. Do not cite it as real microphone or robot stop latency.

## No-motion microphone and ASR session

This section may run only after the user supplies the exact local Chinese Vosk
model path and the read-only model gate passes. Do not download a model, infer a
path, use filename labels as transcripts, or connect a ROS graph for the
prerecorded-WAV evaluation.

For a separately authorized microphone session, keep every actuator and bridge
disconnected. Record monotonic timestamps at audio onset, final transcript,
priority-stop event first publish, each bounded repeat, ACK observation, and
terminal status. Record at least these groups separately:

| Group | Required samples | Measured result |
| --- | ---: | --- |
| wake word plus supported ordinary request | 20 | |
| direct `停下` / `紧急停止` | 20 | |
| near wake/stop soundalikes | 20 | |
| negated, quoted, and meta-language stop | 20 | |
| ordinary request without wake word | 20 | |
| silence, background speech, and added noise | 20 | |
| confirmation before timeout | 10 | |
| confirmation after timeout | 10 | |

For each group report attempts, correct transcripts, correct high-level intent,
false activations, confirmation timeouts, median latency, p95 latency, maximum
latency, model hash, source hash, and corpus hash. Missing samples or timestamps
make the result inconclusive. Keep ordinary intents in an isolated mock
namespace and assert zero executable output before and after every run.

## Stop-latency observations

Measure, without live robot coupling:

1. acoustic onset to final ASR transcript;
2. final transcript callback to first internal stop broadcast;
3. first broadcast to the third and final bounded attempt;
4. first broadcast to correlated ACK observation;
5. trigger to terminal `relay_acknowledged` or `ack_timeout` status.

Do not collapse these into one number. The offline fixture validates only items
2 through 5 with a deterministic clock. The field report must distinguish
measured acoustic/ASR time from software dispatch time.

## Separately authorized real linkage

Stop here unless the user explicitly authorizes this exact session. Before any
live navigation cancel or robot linkage:

1. identify the robot, operator, safety observer, ROS domain, and exact source;
2. verify and physically test the emergency stop and power isolation;
3. clear people and obstacles and keep the safety observer at the emergency stop;
4. prove ordinary intents are disabled or isolated from every real executor;
5. start with zero-motion/status observation only;
6. abort on unexpected topic, stale ACK, missing timestamp, extra repeat, or
   any output that is not the documented high-level intent.

Record the one-time authorization with the field report. Passing offline or
microphone fixtures never authorizes movement and never proves that a physical
robot has stopped.
