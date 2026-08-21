# `trash_bin_staging` 录入与现场验收清单

当前状态（2026-08-11）：

```text
active project map_id = NOT_AVAILABLE_MAP_NOT_FROZEN
trash_bin_staging = NOT_AVAILABLE_UNMEASURED
vendor navigation_diff static map = map1017.yaml (reference only)
```

`map1017.yaml` 是 vendor 当前硬编码入口，不等于项目 V1 已冻结地图，不得直接作为
`active_v1_map_id`，也不得从其中猜测 `trash_bin_staging`。当前空 waypoint schema 必须继续使
bridge fail-closed 拒绝导航。

## 录入前置门

- [ ] V1 的 `/scan`、TF、SLAM、地图保存/重载、AMCL 和 ROS1 `move_base` 已分别验收。
- [ ] 项目团队明确冻结一组匹配的 map YAML 与图像文件，并给出不可混淆的 `map_id`。
- [ ] 冻结地图的 YAML、图像、分辨率、origin 和 checksum 已存档。
- [ ] 垃圾桶物理位置固定；周围保留底盘转向、停车和人员撤离空间。
- [ ] 现场人员用卷尺/标记复核安全停靠点，不使用视觉估计或旧地图坐标代替测量。
- [ ] 录入期间不运行 bridge、vendor driver、teleop 或自动导航，不发布速度。

任一项未满足时，保持：

```yaml
map_id: NOT_AVAILABLE_MAP_NOT_FROZEN
waypoints: {}
```

## 坐标采集流程

1. 复制已冻结 V1 map YAML 与图像到只读归档，记录 SHA-256；给该组合分配项目 `map_id`。
2. 在 RViz 中只加载冻结地图和 TF。不要点击可能向 `/move_base` 发 goal 的 “2D Nav Goal”。
3. 用非运动方式确定安全停靠点的 `map` 坐标：可用 RViz Publish Point 只记录 x/y，yaw 由现场
   朝向基准测量；或在机器人完全断开驱动时读取已人工放置姿态的 `/amcl_pose`。
4. 记录 `x`、`y`、`yaw`（弧度）、测量人、时间、地图 checksum、垃圾桶与机器人最小间距。
5. 在地图和实际场地分别确认停靠点不在 occupied/unknown 区域，并位于膨胀障碍外；保留截图。
6. 两人复核后，复制空 schema 为新的项目文件，只写入实测值：

```yaml
map_id: <FROZEN_V1_MAP_ID>
waypoints:
  trash_bin_staging:
    frame_id: map
    x: <MEASURED_X_METERS>
    y: <MEASURED_Y_METERS>
    yaw: <MEASURED_YAW_RADIANS>
```

7. ROS2 launch 的 `active_v1_map_id` 必须与文件 `map_id` 逐字符一致；`epoch_state_file` 必须位于
   持久、仅运行用户可写的位置。缺失、空值、损坏或 map mismatch 都必须阻塞。

## 无运动验收

- [ ] exact voice stop/waypoint JSON 仍通过严格上游 parser，未增加 epoch/nonce 字段。
- [ ] 空 waypoint、`NOT_AVAILABLE_MAP_NOT_FROZEN`、错误 map_id、缺条目、非 map frame、NaN/Inf
  均被拒绝。
- [ ] 内部 command/status 只使用 `cleanup_navigation_bridge/v2`，旧 goal/rearm/stop/cancel
  四话题在 ROS1/ROS2 图均零端点。
- [ ] rogue ROS2 goal、rearm、cmd_vel_request publisher 被 ROS2 source verifier 阻塞。
- [ ] 乱序、重复、旧 epoch、旧 nonce、cancel 后延迟 goal、终态后重放行为测试均 PASS。
- [ ] succeeded/aborted/preempted/rejected/unavailable/stopped/status timeout 均使 authorization=false。
- [ ] `/scan` 必须为 `laser_link` 且接收时间/source stamp 均 `<0.5 s`；`map→base_link` TF source
  stamp 必须 `<0.5 s`。缺失、未来超限、时间回拨或 `>=0.5 s` 均使 status unavailable、cancel all
  和 authorization=false。
- [ ] `pub_odom_tf=false` 场景下已证明唯一且连续的新鲜 TF 链；未证明时不得用静态假 TF 绕过。
- [ ] 生产脚本无 `--bridge-all-topics`；公开 `/cmd_vel` 和私有 driver topic 不跨桥。

## 零速现场门（仍需当次授权）

- [ ] 目标机有 ROS2 Foxy 与 `ros1_bridge`；当前只读信息显示目标环境无 `ros2` 命令，因此现状 BLOCK。
- [ ] preflight 证明 Noetic/Foxy、标准消息 pair、双图、进程和 `/dev/ttyTHS0` 均满足要求。
- [ ] vendor 启动前，watchdog、zero gateway、bridge、ROS2 连续 verifier 与 ROS1 10 条连续零均 PASS。
- [ ] vendor 启动后 `/dev/ttyTHS0` 始终只有 ROS1 `/limo_base_node` owner；循环复核无变化。
- [ ] 退出执行 TERM→有界等待→KILL→wait；ROS1/ROS2 节点、相关进程清零，UART 恢复空闲。

## 真实 waypoint 验收（以后单独申请运动授权）

每次动作前必须重新获得现场单次明确授权，不得由本清单自动延伸授权。

| 试次 | map_id/checksum | 起点 | 目标误差 | 用时 | stop结果 | 障碍结果 | 碰撞/异常 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | | | | | | | |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |

通过标准：5/5 到达实测停靠点、无碰撞、无 rogue publisher；每次 stop 均取消当前 epoch 并归零；
至少覆盖 succeeded、cancel/preempted、不可达 aborted、状态失联和 bridge 退出。视觉精定位不得用于
掩盖固定 waypoint 失败。
