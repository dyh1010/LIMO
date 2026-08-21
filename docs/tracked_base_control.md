# 履带底盘安全控制基线

LIMO 履带模式使用与四轮差速相同的滑移转向模型。当前控制层仅接受：

- `linear.x`：前进/后退；
- `angular.z`：左转/右转。

任何横移、升降、滚转或俯仰速度请求都会被拒绝，而不是静默转换。

## 当前实机架构（2026-08-11）

现场已经通过机器人原生 ROS1 Noetic 工作区的 `limo_base_node` 成功驱动履带；该节点使用
`ttyTHS0`、`use_mcnamu=false`。同日 ROS2 Foxy 受控链虽然在软件图中输出了
`linear.x=0.03 m/s`、持续 `0.5 s`，但用户确认履带物理上完全没有动作，因此不能记为
Stage 3 或真实运动通过。

当前权威架构是：

- ROS1 `limo_base_node` 是 `/dev/ttyTHS0` 的唯一硬件 owner；
- ROS2 `limo_base` 不再是默认实机入口，禁止与 ROS1 driver 并发；
- ROS2 清理系统保留本页安全网关，但必须经受限 `ros1_bridge` 和 ROS1 侧 fail-closed
  timeout/watchdog 适配器后再进入私有 driver 命令话题；ROS1 `limo_base_node` 的原
  `/cmd_vel` 订阅必须 remap 到该私有话题；
- bridge、独立 Catkin wrapper 与 ROS1 watchdog 已本地实现并通过离线检查，但尚未完成
  Catkin、跨图或机器人验收；最新只读安全审计还发现 ROS2 源端 owner、导航结果闭环、
  epoch/nonce 防重放、vendor 前连续零证明和退出/UART 清理阻塞。状态为
  `ROS1_ROS2_BASE_BRIDGE_IMPLEMENTED_LOCALLY_UNVERIFIED`，在关闭全部阻塞前禁止 ROS2 清理
  任务驱动真实底盘。

完整所有权、断链停车和分级验收要求见 `docs/ros1_ros2_base_bridge_contract.md`。

## 安全网关

节点：`limo_cleanup_base/tracked_base_controller`

输入：

- `/cleanup/base/cmd_vel_request`：上层速度请求；
- `/cleanup/base/motion_authorized`：持续人工/任务授权心跳；
- `/cleanup/base/safety_clear`：持续安全链心跳。

输出：

- `/cleanup/base/safe_cmd_vel`：经过轴约束、限速、加速度限制和超时保护后的私有底盘命令。

默认实机路径不得把该话题直接交给 ROS2 vendor driver，也不得让 bridge 直接发布 ROS1
公开 `/cmd_vel` 或私有 driver 话题。目标链为：ROS2 `/cleanup/base/safe_cmd_vel` → 受限
bridge → ROS1 `/cleanup/base/safe_cmd_vel` → ROS1 timeout/watchdog 适配器 → ROS1
`/cleanup/base/driver_cmd_vel` → ROS1 `limo_base_node`。ROS1 driver 的原 `/cmd_vel` 订阅必须
remap 到该私有话题；自动模式下公开 ROS1 `/cmd_vel` 必须零端点。

默认值：

```text
use_tracked_base_controller=false
allow_base_motion=false
max_linear_speed=0.12 m/s
max_angular_speed=0.35 rad/s
command_timeout=0.25 s
heartbeat_timeout=0.50 s
```

只有启动参数明确允许运动，并且速度请求、运动授权和安全许可三路消息都为最新状态时，
网关才会输出非零速度。任意消息缺失、过期、取消或出现不支持的运动轴，输出立即归零。
超时判断使用单调时钟，避免系统时间或 ROS 时间回拨让旧心跳继续有效；所有速度、限制和
时间输入必须是有限数值，`NaN` / `Inf` 会 fail-closed。三个输入订阅均使用深度 1，避免
恢复连接后重放积压速度。授权或安全许可变为 `false`、以及收到非法轴时会在回调中立即
发布零速并清除旧速度请求，重新放行后必须收到新的速度请求。

本节点不是导航规划器，也不启动任何底盘 driver。首次 bridge 实机验收前仍需验证履带安装、
黄色模式灯、主开关物理断电、双图唯一命令所有权，以及两层断链停车：

1. bridge、ROS2 网关或授权心跳丢失时，ROS1 watchdog 必须在不超过 `0.25 s` 的 lease 内
   向私有 `/cleanup/base/driver_cmd_vel` 持续输出零；
2. ROS1 watchdog 自身退出时，ROS1 `limo_base_node`/底盘必须在已测得的有界时间内停车。

ROS1 watchdog 还必须默认禁动、订阅 queue=1，并拒绝非有限值和非平面轴。生产 bridge 只允许
白名单话题与单向数据流，禁止 `--bridge-all-topics`、命令双向桥接和回环；`/cmd_vel` 与
`/cleanup/base/driver_cmd_vel` 均不得跨桥。

第二项目前没有现场证据。在该行为完成源码确认和现场断链验证前，不得经 bridge 发送非零速度。
所有权检查必须同时覆盖进程、ROS1 图、ROS2 图与 UART 占用；任一系统查询失败或超时都不能
按“没有节点”处理。

## 冻结的 ROS2 vendor 实验路径

目标机上的 ROS2 `limo_base` 启动会打开 `/dev/ttyTHS0`，并立即发送
`MSG_CTRL_MODE_CONFIG_ID (0x421)` 进入 commanded mode。项目曾为它准备
`tracked_base_stage2_preflight.sh`、`tracked_base_zero_output.launch.py`、
`verify_tracked_zero_output.py`、`tracked_base_vendor_stage2.launch.py` 与
`verify_tracked_stage2_topology.py`，并完成严格 fail-closed 软件加固。

该路径现在只保留为历史诊断和离线回归资产，不是默认实机入口。2026-08-11 的 ROS2 诊断
路径曾取得 vendor Stage 2 topology PASS；该结果不构成新生产架构验收。随后 Stage 3 软件
短脉冲完成 UART 打开、命令观测和最终归零，但履带没有物理动作，因此 Stage 3 未通过。
ROS1 `limo_base_node` 活跃时禁止启动上述 vendor launch。
任何未来独立诊断都必须先证明 ROS1 driver 已停止、UART 已释放，并取得与生产路径相互独立的
现场授权；不能把它作为 bridge 的替代方案。

纯软件零输出 launch 与观察器仍可用于不接 UART 的回归：持续注入授权、安全许可和非零请求时，
硬禁用网关必须只输出零，且不得创建真实 ROS1 或 ROS2 `/cmd_vel` 硬件链。该测试只证明 ROS2
安全网关，不证明 bridge、ROS1 watchdog、ROS1 driver 或真实底盘已经通过。

## 离线话题级 smoke

`scripts/smoke_test_tracked_base.py` 会把输出改到
`/test/cleanup/tracked_cmd_vel`，并明确检查没有真实 `/cmd_vel` 发布者。它依次验证：

1. 缺少授权或安全许可时始终输出零；
2. 条件齐全时输出被限制在 `0.12 m/s` 和 `0.35 rad/s` 以内；
3. 撤销运动授权后立即归零并清除旧请求；
4. 撤销安全许可后立即归零并清除旧请求；
5. 请求横移等履带不支持轴时立即 fail-closed；
6. 指令或心跳过期后立即归零。
