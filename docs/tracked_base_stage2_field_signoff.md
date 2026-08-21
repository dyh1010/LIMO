# ROS2 vendor Stage 2 历史记录（已冻结，禁止执行）

> 本文件只保存 2026-08-11 已结束实验的证据，不再是现场签字表、授权表或操作说明。
> 不得根据本文件设置环境变量、启动 ROS2 `limo_base`、打开 `/dev/ttyTHS0` 或重试运动。

## 架构纠偏

现场最终证据表明：

- 机器人原生 ROS1 Noetic `limo_base_node` 使用 `ttyTHS0`、`use_mcnamu=false`，并已通过
  `limo_start.launch` 与键盘 teleop 真实驱动履带；
- ROS2 Foxy 受控链虽然在软件图中输出过 `linear.x=0.03 m/s`、持续 `0.5 s`，但履带物理
  完全没有动作，原因未知，不能记为 Stage 3 通过；
- 中间的 `limo_cleanup_ws_review2` 候选没有覆盖最终源码的测试证据，并保留 guard 生产话题
  非零注入、可重放 vendor 布尔授权及测试/实现不一致等阻塞；从未合入或部署，永久禁止执行；
- ROS1 `limo_base_node` 现为 `/dev/ttyTHS0` 的唯一硬件 owner；ROS2 vendor driver 只保留为
  历史诊断资产，不再是默认实机入口；
- ROS2 自动运动必须经过安全网关、受限单向 bridge、ROS1 fail-closed watchdog 和私有
  `/cleanup/base/driver_cmd_vel`，完整要求见 `docs/ros1_ros2_base_bridge_contract.md` 与
  `docs/tracked_base_acceptance.md`。

当前 bridge、catkin wrapper 与 watchdog 已在本地实现并通过离线测试，但尚未完成 Catkin
构建、ROS1/ROS2 跨图运行、机器人全零、断链停车或实机运动验证，状态为
`ROS1_ROS2_BASE_BRIDGE_IMPLEMENTED_LOCALLY_UNVERIFIED`。当前 ROS1 bringup/teleop 是否
仍在运行也未复核，按 `ROS1_RUNTIME_STATE_UNKNOWN_ASSUME_ACTIVE` 处理；在用户确认停止前，
把 UART 视为已占用。

后续独立只读安全审计又发现 ROS2 源端 owner、导航结果闭环、防重放、vendor 前连续零证明
和退出/UART 清理阻塞。该历史文件不提供修复后的执行入口；任何新验收必须使用经专项修复、
重新审查并另行授权的新流程。

V1 不等待 bridge 实机验收即可继续只读、感知和 dry-run 交付；这不构成 bridge 验收通过，
也不授权 V1 发布真实自动底盘命令。

## 2026-08-11 18:14 现场口头状态

用户当时口头报告履带已安装、黄色模式灯亮、场地已清空，主开关是唯一可用的物理停止
手段，并要求任何可能运动前必须先通知。该信息只记录当时现场状态，不构成现在或未来的
授权，也不能代替新的场地、主开关和人员复核。

## 2026-08-11 18:37 首次 ROS2 Stage 2 尝试

- 用户只对当次全零验收作出单次授权并守在主开关旁；该授权已消耗并失效。
- Gate 1 精确为 `Gate1_FILE_HASHES=PASS`、`GATE1_AUDIT=PASS`、`GATE1=PASS`。
- 带当次 ACK 的 Gate 2 为 `GATE2_PREFLIGHT=STAGE2_PREFLIGHT_PASS`。
- 全零网关进入 READY 后，Gate 3 因 Foxy endpoint owner 显示
  `_NODE_NAMESPACE_UNKNOWN_/_NODE_NAME_UNKNOWN_` 而 fail-closed，精确输出：

  ```text
  ZERO_OUTPUT_GUARD_BLOCKED: /cleanup/base/safe_cmd_vel publisher is
  _NODE_NAMESPACE_UNKNOWN_/_NODE_NAME_UNKNOWN_, expected
  /cleanup_tracked_base_zero_output
  ```

- 验证在 topology 阶段停止，未进入样本计数；不能声明采集到全零样本或 Stage 2 通过。
- vendor 从未启动，`0x421` 未发送，`/dev/ttyTHS0` 从未打开且最终空闲；非零命令为 `0`，
  用户确认履带全程没有物理动作。
- 后续隔离 Domain 证明 Fast DDS 与 Cyclone DDS 都能返回 endpoint names；确定性兼容问题是
  Foxy `Node` 缺少 `get_fully_qualified_name()`。最小兼容修复后的
  `ZERO_OUTPUT_GUARD_PASS` 只属于纯软件复测，不是硬件 Stage 2 通过。

## 后续 ROS2 vendor 受控短脉冲

后续一次独立授权下，ROS2 流程完成 preflight、全零守卫、vendor 拓扑与 motion zero guard；
软件观测到 `linear.x=0.03 m/s`、持续 `0.5 s`，峰值 `0.030000`，随后连续全零、有序停止
vendor 并释放 UART。用户现场确认履带物理完全没有动作。

该结果只能证明当时 ROS2 图、串口打开和软件命令观测链完成，不能证明底盘执行成功，也不能
把零动作归因于驱动、模式、死区或脉冲时长中的任一项。不得自动增加参数或自动重试。

## 只读历史基线（不可推断当前状态）

当时记录为：

- 主机：`master`，ROS2 Foxy；
- `/dev/ttyTHS0` sysfs：`/sys/devices/platform/3100000.serial`；
- driver：`/sys/bus/platform/drivers/serial-tegra`；
- 当次审计时串口无占用、用户属于 `dialout`、无 console/getty 冲突；
- ROS2 vendor 启动会调用 `enableCommandedMode()` 并发送 `0x421`。

以上都是时间点证据，不能用于证明当前进程、ROS 图或 UART 空闲。尤其 ROS1 与 ROS2 节点不在
同一张原生图中，单侧“无节点”不构成安全结论。

## 永久禁止按本文件执行的事项

- 复用历史 `TRACKED_BASE_*` 确认变量或旧 `STAGE2_PREFLIGHT_PASS`；
- 根据旧复选框或口头状态再次授权；
- 启动 `tracked_base_vendor_stage2.launch.py` 作为生产底盘入口；
- ROS1 `limo_base_node` 活跃时启动 ROS2 `limo_base` 或打开 `/dev/ttyTHS0`；
- 使用 `--bridge-all-topics`，桥接 `/cmd_vel` 或
  `/cleanup/base/driver_cmd_vel`，或制造命令回环；
- 把软件零输出 PASS、UART 打开或 ROS2 命令峰值解释为物理运动成功；
- 在未重新通知用户并取得单次授权前执行任何可能运动的步骤。

## 后续唯一入口

后续工作只按以下两份当前文档推进：

- `docs/ros1_ros2_base_bridge_contract.md`
- `docs/tracked_base_acceptance.md`

新验收必须重新记录机械/场地/主开关、ROS1 图、ROS2 图、进程、UART owner、bridge 白名单、
watchdog lease、私有 driver 命令、断链停车和当次授权；本历史文件不再提供可勾选签字项。
