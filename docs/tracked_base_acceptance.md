# 履带底盘分级验收清单

## 当前状态与适用范围

2026-08-11 现场已确认机器人原生 ROS1 Noetic `limo_base_node` 能真实驱动履带；ROS2 Foxy
受控链虽输出过 `linear.x=0.03 m/s`、持续 `0.5 s`，但履带物理零动作，不能记为 Stage 3
通过，原因也尚未证明。

本清单现以以下架构为唯一默认实机路径：

```text
ROS2 tracked_base_controller
  -> ROS2 /cleanup/base/safe_cmd_vel
  -> 受限 ros1_bridge（Twist 仅 2 -> 1）
  -> ROS1 /cleanup/base/safe_cmd_vel
  -> ROS1 fail-closed timeout/watchdog
  -> ROS1 /cleanup/base/driver_cmd_vel
  -> ROS1 limo_base_node（原 /cmd_vel 订阅 remap 到私有话题）
  -> /dev/ttyTHS0
```

ROS1 `limo_base_node` 是 `/dev/ttyTHS0` 的唯一硬件 owner。ROS2 vendor driver 不再是默认
实机入口，永远不得与 ROS1 driver 并发。完整契约见
`docs/ros1_ros2_base_bridge_contract.md`。

受限 bridge、独立 Catkin wrapper、ROS1 watchdog、导航 intent 消费者和检查器已本地实现并
通过离线检查，但尚未完成 Catkin、ROS1/ROS2 跨图或机器人验收，状态为
`ROS1_ROS2_BASE_BRIDGE_IMPLEMENTED_LOCALLY_UNVERIFIED`。最新安全审计仍阻塞 ROS2 源端精确
owner topology、导航结果闭环、epoch/nonce 防重放、vendor 前连续零证明、退出/UART 清理和
连续 owner 监控。当前机器人上的 ROS1 bringup/teleop 是否仍在运行也未复核，状态为
`ROS1_RUNTIME_STATE_UNKNOWN_ASSUME_ACTIVE`；在用户确认停止前，把 UART 视为已占用，禁止
访问串口、启动 bridge、启动 ROS2 driver 或重跑运动。

机械臂在全部底盘验收期间保持关闭，`allow_arm_motion=false`。任何可能导致履带运动的步骤
必须在执行前当次通知用户并取得单次明确授权；历史授权不得复用，禁止自动重试或自动加量。

## 第 0 级：机械、场地与物理停止

- 两侧模式插销处于四轮差速/履带要求的位置，短线朝车头并实际插入。
- 履带安装完整、方向正确、张力合适；两侧车门抬起且不与履带摩擦。
- 黄色模式灯稳定常亮。
- 测试区域平整、干燥，四周至少留有 1 m 缓冲区并设置软围挡。
- 首轮零速和断链测试使用可靠托轮/架空条件；线缆不会卷入履带。
- 现场主开关观察员可直接触达主开关，并已独立验证断电、恢复后无自动运动。
- 自动集成时 ROS1 键盘 teleop、手柄、Move Base、ROS2 Nav2 和历史调试节点全部停止。

任一项无法确认即停止。本级不启动 ROS 节点，不打开 UART。

## 第 1 级：ROS1、ROS2 与 UART 只读所有权审计

只有用户先确认 ROS1 手动驾驶已经停止后，才执行本级。检查必须同时覆盖：

- 操作系统进程：ROS1/ROS2 driver、teleop、Move Base/Nav2、bridge、串口调试程序；
- ROS1 图：`/cmd_vel`、`/cleanup/base/safe_cmd_vel`、
  `/cleanup/base/driver_cmd_vel` 的发布者和订阅者；
- ROS2 图：`/cleanup/base/cmd_vel_request`、`/cleanup/base/safe_cmd_vel` 及公开速度话题；
- UART：`/dev/ttyTHS0` owner、权限、console/getty 与 sysfs/driver 身份；
- DDS/ROS master：不得用隔离图、查询超时或单侧“无节点”推断另一侧安全。

已知 UART 身份基线为：

```text
/dev/ttyTHS0
/sys/devices/platform/3100000.serial
/sys/bus/platform/drivers/serial-tegra
```

通过标准是所有查询均成功且结果可判定，没有第二个 driver、teleop 或未知速度发布者。只检查
ROS1 图或只检查 ROS2 图都不构成通过。本级不得启动任何 driver、bridge 或速度发布者。

## 第 2 级：ROS1 唯一 driver 基线

本机已经有 ROS1 原生栈物理运动成功证据，但未来自动集成不得直接复用键盘 teleop 流程。
需先在 catkin 工作区提供项目 wrapper，使 ROS1 `limo_base_node` 的原 `/cmd_vel` 订阅固定
remap 到 `/cleanup/base/driver_cmd_vel`，且不允许命令行改回公开入口。

在第 0～1 级通过并取得当次硬件状态授权后，只启动该 ROS1 wrapper：

- `/dev/ttyTHS0` 恰好由一个 ROS1 `limo_base_node` 占用；
- `use_mcnamu=false` 与现场成功基线一致；
- ROS2 `limo_base`、ROS1 teleop、手柄、Move Base/Nav2 均不存在；
- ROS1 公开 `/cmd_vel` 无端点；driver 只订阅私有
  `/cleanup/base/driver_cmd_vel`；
- 记录 ROS1 `/odom`、`/imu`、状态和 TF 的实际类型、frame 与唯一 owner。

本级只建立唯一硬件 owner，不授权非零速度。项目 wrapper 尚未实现时，本级为 BLOCKED。

## 第 3 级：离线 bridge 与 watchdog 契约回归

本级不连接 UART，也不启动任何机器人 driver。必须实现并自动验证：

- 生产 bridge 使用显式白名单，禁止 `--bridge-all-topics`；
- 命令只允许 `geometry_msgs/Twist` 从 ROS2 → ROS1 单向桥接；
- `/cmd_vel` 与 `/cleanup/base/driver_cmd_vel` 明确禁止跨桥，禁止消息回环；
- ROS1 watchdog 默认禁动、订阅 queue 深度为 `1`，只接受有限的平面 Twist；
- watchdog 启动即输出零，输入 lease 不超过 `0.25 s`，超时后持续归零；
- 授权撤销、非法轴、NaN/Inf、时间回拨、bridge 断开和进程重启均不能恢复旧非零命令；
- watchdog 是 ROS1 私有 `/cleanup/base/driver_cmd_vel` 的唯一发布者；
- ROS2 安全网关保持既有限速、心跳和 fail-closed 规则。

首版状态回传仅考虑 `/odom`、`/imu` 从 ROS1 → ROS2。`/limo_status` 必须先核对两侧消息定义
和 bridge `--print-pairs`；`/tf`、`/tf_static` 必须先完成唯一所有权审计，禁止盲桥。

## 第 4 级：bridge 全零实机验收

只有第 0～3 级全部通过、现场人员守在主开关旁并取得新的单次授权后才进入本级。

启动顺序固定为：

1. 先启动 ROS1 watchdog，保持默认禁动并确认私有 driver 命令持续全零、公开 `/cmd_vel`
   无端点；
2. 再启动唯一 ROS1 driver wrapper，使 driver 一订阅私有话题就收到连续零；
3. 启动 ROS2 安全网关，保持 `allow_base_motion=false`；
4. 启动受限 bridge；
5. 同时复核 ROS1 图、ROS2 图和 UART owner。

通过标准：

- ROS2 `/cleanup/base/safe_cmd_vel` 只有安全网关一个发布者；
- ROS1 `/cleanup/base/safe_cmd_vel` 只有 bridge 一个发布者、watchdog 一个订阅者；
- ROS1 `/cleanup/base/driver_cmd_vel` 只有 watchdog 一个发布者、driver 一个订阅者；
- ROS1 公开 `/cmd_vel` 零端点；ROS2 公开速度话题无绕行端点；
- 连续样本均为六轴有限全零，履带没有任何物理动作；
- ROS1 `limo_base_node` 是 `/dev/ttyTHS0` 唯一 owner。

任一未知 owner、额外端点、非零/非有限样本、查询失败或物理动作都立即 BLOCK 并按有序流程
停止；不得进入下一等级。

## 第 5 级：断链与退出停车

保持架空/托轮和当次授权，依次单独验证：

1. 撤销 ROS2 运动授权与安全心跳；
2. 停止 ROS2 安全网关；
3. 停止 bridge；
4. 模拟 bridge 输入超时；
5. 单独验证 ROS1 watchdog 异常退出。

前四项必须使 watchdog 在不超过 `0.25 s` 的 lease 内向私有 driver 话题持续输出零，且不得
恢复旧命令。第 5 项必须证明 ROS1 `limo_base_node`/底盘自身在已记录的有界时间内停车；若
vendor driver 没有可验证的命令超时，本级直接 BLOCK，禁止非零 bridge 运动。

停止顺序为：撤销授权并确认 ROS2 安全输出与 ROS1 私有 driver 命令连续归零 → 停止上层
任务 → 停止 bridge → 保持 watchdog 至少一个 lease 周期并确认私有 driver 命令持续全零、
公开 `/cmd_vel` 仍无端点 → 在 watchdog 仍发布全零时停止 ROS1 driver 并确认 UART 释放 →
最后停止 watchdog。在 driver/底盘自身命令超时尚未验收前，driver 不得在 watchdog 停止后
继续存活。

## 第 6 级：bridge 单次短运动

只有第 0～5 级签字通过后，才可重新通知用户并申请一次、单一档位的运动授权。试验参数必须
在独立试验单中审批，并以 ROS1 已观测的最低有效值为依据；不得由此前 ROS2 物理零动作推断
死区、自动加量或自动重试。

单次试验必须同步记录：

- ROS2 请求与安全网关输出；
- bridge 两侧 Twist；
- ROS1 watchdog 输入和私有 driver 输出；
- ROS1 `/odom`、`/imu` 与底盘状态；
- 履带实际方向、停止距离、异常声音和主开关观察结果。

任何方向错误、履带干涉、额外发布者、归零超时或现场不确定都立即停止，且不自动尝试下一
档位。

## 第 7 级：低速转向与导航接入

只有单次直行和全部断链停车通过后，才逐档验收低速转向、取消、障碍物和停车误差。Nav2
只能向 ROS2 `/cleanup/base/cmd_vel_request` 提交请求；不得发布 ROS1 公开 `/cmd_vel`、私有
driver 话题或 ROS2 安全输出。机械臂继续关闭，导航通过也不自动授权机械臂。

## 冻结的 ROS2 vendor 历史路径

`tracked_base_stage2_preflight.sh`、`tracked_base_zero_output.launch.py`、
`tracked_base_vendor_stage2.launch.py` 和两个 verifier 是此前 ROS2 vendor 实验的安全资产，
不再构成默认实机步骤。旧 `docs/tracked_base_stage2_field_signoff.md` 只保存 2026-08-11 历史
证据，不得作为新的授权表执行。

历史事实必须保持精确：

- 首次 Stage 2 在 Gate 3 fail-closed，vendor 未启动、`0x421` 未发送、UART 未打开；
- Foxy FQN 兼容修复随后只在隔离 Domain 完成纯软件 PASS，不等于硬件 Stage 2 通过；
- 随后的 `limo_cleanup_ws_review2` 扩展候选未完成最终同快照回归：旧 107/249 证据早于最终
  源码，guard 还会向生产名私有输入发布非零测试请求，vendor launch 的布尔授权可重放，
  以及测试/实现、preflight 环境和候选文档存在未关闭阻塞。该候选从未合入或部署，禁止使用；
- 后续 ROS2 受控链完成 preflight、零速、vendor 拓扑和 `0.03 m/s、0.5 s` 软件输出，最终归零
  并释放 UART，但履带物理没有动作；根因未知，不能记为 Stage 3 通过；
- ROS1 原生栈随后产生了现场物理运动成功证据，因此当前采用 ROS1 唯一 UART owner + bridge
  架构。

## 当前阻塞

- `ROS1_RUNTIME_STATE_UNKNOWN_ASSUME_ACTIVE`
- `ROS1_ROS2_BASE_BRIDGE_IMPLEMENTED_LOCALLY_UNVERIFIED`
- `ROS1_BRIDGE_ROS2_SOURCE_TOPOLOGY_UNVERIFIED`
- `ROS1_BRIDGE_NAVIGATION_RESULT_LOOP_MISSING`
- `ROS1_BRIDGE_CROSS_TOPIC_REPLAY_GUARD_MISSING`
- `ROS1_BRIDGE_ZERO_BEFORE_VENDOR_NOT_PROVEN`
- `ROS1_BRIDGE_SHUTDOWN_UART_CLEANUP_UNVERIFIED`
- `ROS1_DRIVER_PRIVATE_REMAP_UNVERIFIED`
- `ROS1_WATCHDOG_IMPLEMENTED_LOCALLY_UNVERIFIED`
- `ROS1_DRIVER_COMMAND_TIMEOUT_UNVERIFIED`
- `ROS1_ROS2_STATUS_TF_BRIDGE_UNAUDITED`

以上任一状态未关闭前，不进入 bridge 非零运动或导航验收。
