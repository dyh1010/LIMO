# Voice V2 legacy ROS2 offline deployment notes

`LEGACY_ROS2_OFFLINE_ONLY`: this document preserves the old ament/ROS2 mock
procedure for reproducibility. It is not a ROS1/Noetic field deployment or
rollback procedure. The Noetic runtime remains blocked until a reviewed
`rospy` adapter and topology guard exist.

This procedure is deliberately fail-closed. It does not authorize robot
motion, microphone capture, or changes to the strict bridge policy.

## Before deployment

1. Save the exact source revision or archive used to build the workspace.
2. Build in an isolated workspace and run:

   ```bash
   colcon build --packages-up-to limo_cleanup_voice
   colcon test --packages-select limo_cleanup_voice
   bash src/limo_cleanup_voice/scripts/preflight_voice_deployment.sh "$PWD"
   bash src/limo_cleanup_voice/scripts/smoke_test_voice_text.sh "$PWD"
   ```

3. Require `VOICE_BRIDGE_EXACT_PAYLOAD_READONLY_PASS` in the preflight report.
4. Require the corpus-readiness report to show `status=PASS`,
   `corpus_ready=true`, `delivery_ready=true`, and `model.ready=true`.
   `INCOMPLETE` or `decoded_not_transcribed` is a deployment blocker.
5. Attach offline stop evidence for immediate first publish, exactly three
   bounded attempts, 0.75-second debounce, monotonic sequence/timestamps,
   strict ACK correlation, expired/failed ACK rejection, and status output.
6. Confirm the launch file pins mock perception/executor, dry-run, and all
   base/arm/gripper motion flags to false for offline acceptance.
7. Do not deploy if any unknown navigation JSON field appears.

## Rollback trigger

Rollback immediately if any of the following occurs:

- wake-word-free task or waypoint forwarding;
- a confirmation timeout still forwards a pending command;
- `到这里来` produces a navigation request;
- a navigation payload is rejected by the strict bridge parser;
- any velocity, joint trajectory, power, or gripper publisher appears;
- ASR repeatedly maps background audio to a supported command.

## Rollback procedure

1. Stop only the voice launch/process group. Do not start a replacement base,
   arm, gripper, navigation, or bridge process.
2. Restore the previously archived voice package source and rebuild in a new
   isolated workspace. Do not overwrite unrelated concurrent changes.
3. Keep `voice_input_mode:=text`, `enable_tts:=false`, mock perception/executor,
   dry-run, and every motion flag false.
4. Re-run the preflight, 42+ package tests, deterministic statistics, and mock
   smoke before considering the rollback complete.
5. Record the failed payload/transcript, source revision, report JSON, and
   process cleanup evidence in `THREAD_VOICE_DIALOGUE.md`.

Rollback success means the offline contract is restored. It is not evidence
that real navigation, safe stopping, or microphone capture has passed.
