# Eye-in-hand true-grasp visual reference — 2026-08-20

Status: `REFERENCE_ENVELOPE_CAPTURED_NOT_METRIC_DEPTH_CALIBRATION`

## Capture identity

- Camera: wrist-mounted JoyandAI `JYU2C-2083`, `/dev/video0`
- Resolution: `640 x 480`
- Capture: 30 frames at approximately 0.5 s intervals
- Remote archive: `/tmp/limo_grasp_reference_seq_c4d1.tar.gz`
- Local archive: `tmp/limo_grasp_reference_seq_c4d1.tar.gz`
- Archive SHA256: `b5c550f2e8af8f07bf9a1d9f96fd1359282a92c632a0d7d6778cb3bd6732298f`
- Actuator access during capture: none
- Arm/gripper command during capture: none

## Corrected visual interpretation

The earlier far-floor frame showed the whole bottle at roughly `220 px` apparent width and center near
`(242, 235)`. Although its 2-D projection lay between the two fingers, the operator confirmed that it was far
outside the gripper's physical capture height. That frame is a required negative example:
`2D_BETWEEN_FINGERS_IS_NOT_GRASPABLE_DEPTH`.

During this reference sequence the operator moved the same bottle through the actual gripper capture volume.
At a representative centered near-grasp pose the bottle occupies roughly `500--550 px` of the image width,
its lateral center is near `x=320`, its long axis is approximately vertical in the image, and the lower red-label
region lies between the fingers near the gripper base. This is materially different from the far-floor view.

The operator moved the bottle throughout the sequence, including the last frames. Therefore this capture is a
visual envelope, not a single stationary ground-truth pose, not a camera-to-tool transform, and not a metric depth
calibration. It may be used to design image-based approach gates, but must not directly authorize closing or arm
motion.

## Required image-based approach gates

1. Do not close when the complete bottle is small and fully visible merely because it overlaps the finger gap.
2. Align the bottle long axis with the demonstrated near-grasp orientation before final approach.
3. Drive lateral image error toward the demonstrated center (`x` near 320), using measured motion-to-pixel response
   rather than an assumed camera axis mapping.
4. Use apparent scale/reference-image similarity as a near-depth gate; a single monocular frame is insufficient for
   metric distance.
5. Require a stationary no-hand frame and a separate, explicitly authorized close command before gripping.
6. Main-camera data may confirm bottle identity/coarse scene location, but cannot fill its blind region with assumed
   coordinates; the wrist camera owns the final visual loop.

## Explicit outside-current-grasp-volume negative frame

After returning the bottle to the floor, the operator requested observation only. The initial wording was interpreted
as outside the arm workspace; the operator subsequently corrected it: the bottle is reachable by arm motion, but is
outside the gripper's **current** physical capture volume. A single wrist-camera frame was captured without actuator
access:

```text
path: tmp/limo_wrist_out_of_reach_20260820.png
resolution: 640 x 480
sha256: bbcb77270118fb863e9652cdbae4c1e75cd17fdd6e72325db527fe5abe09269f
approximate bottle center: (278, 225)
approximate projected bottle extent: 250 x 100 px
operator reachability label: ARM_REACHABLE_BUT_OUTSIDE_CURRENT_GRASP_VOLUME
```

The bottle is fully visible and horizontally oriented, but its scale is less than half the representative true-grasp
reference width. This is a required negative example for any later visual gate: visibility, centering, or overlap with
the finger projection must never be treated as proof that the bottle is already inside the gripper capture volume.
It does **not** mean the bottle is outside the arm workspace. No planned `Z+5 mm` observation motion was executed.
Arm motion is required to approach it, but the first motion must be a small measured observation step because the
monocular image and currently uncalibrated camera-to-tool transform cannot safely determine a one-shot metric move.
