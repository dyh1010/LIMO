# ROS1/ROS2 履带底盘桥接契约

## 当前权威结论

2026-08-11 现场验证确认，机器人能够通过原生 ROS1 Noetic 工作区真实驱动履带。以下命令
只用于记录已经发生的现场证据；在确认当前 ROS1/ROS2 进程与 UART owner 前不得直接重跑：

```bash
source ~/agilex_ws/devel/setup.bash
roslaunch limo_bringup limo_start.launch
roslaunch limo_bringup limo_teletop_keyboard.launch
```

现场观察到履带随键盘命令实际运动。ROS1 `limo_base_node` 使用 `ttyTHS0`，
`use_mcnamu=false`。与之相对，ROS2 Foxy 受控链路虽然通过 preflight、零速守卫、vendor
拓扑和软件命令观测，并输出 `linear.x=0.03 m/s`、持续 `0.5 s`，但履带物理上完全没有
动作；该结果不能记为 Stage 3 或真实运动通过，原因也尚未证明，可能涉及驱动路径、模式、
死区、脉冲时长或其他因素，不能直接归因于某一项。

当前机器人上的 ROS1 bringup/teleop 是否仍在运行尚未复核，状态记为
`ROS1_RUNTIME_STATE_UNKNOWN_ASSUME_ACTIVE`。在用户确认其已停止并完成双图、进程与 UART
只读复核前，必须把 `/dev/ttyTHS0` 视为已由 ROS1 占用；禁止启动 ROS2 driver、bridge、
第二个 teleop 或串口诊断。

因此当前实机架构基线为：

- ROS1 Noetic `limo_base_node` 是 `/dev/ttyTHS0` 的唯一底盘硬件 owner；
- ROS2 清理项目不得直接启动 ROS2 Foxy `limo_base`；
- ROS2 运动请求必须经过安全网关、ROS1/ROS2 bridge 和 ROS1 侧 fail-closed
  timeout/watchdog 适配器后，才能接入 ROS1 命令链；
- ROS1 与 ROS2 底盘 driver 永远不得并发运行或争抢 `/dev/ttyTHS0`。

受限 bridge、独立 Catkin wrapper、ROS1 watchdog、严格 navigation intent 消费者和检查器已在
本地实现，离线策略 6 组、制品检查 13 项与 Python 语法/风格 PASS。当前状态为
`ROS1_ROS2_BASE_BRIDGE_IMPLEMENTED_LOCALLY_UNVERIFIED`：尚未完成 Catkin 构建、ROS1/ROS2
跨图、机器人全零、断链停车、状态/TF 或实机运动验收。在该状态关闭前，ROS2 清理任务不得
发布真实底盘运动。

最新独立只读审计还发现以下硬阻塞，修复并复核前禁止把本地实现同步到机器人：

- 缺 ROS2 源端导航/请求精确 owner topology；ROS1 图只看到统一 bridge 进程，不能排除 rogue
  ROS2 goal、rearm 或 `/cleanup/base/cmd_vel_request` 发布者；
- 只有 readiness 心跳，没有 succeeded/aborted/preempted 结果闭环，导航 dispatch 后授权可能
  持续为 true；
- goal/rearm/stop/cancel 分属四个跨图 topic，缺共同 epoch/nonce，不能排除 cancel 后延迟到达的
  旧 rearm/goal 重放；
- 当前零速编排在证明 watchdog/私有 driver 话题连续全零前启动 vendor，启动顺序不满足本契约；
- 退出路径缺少有界 TERM→KILL→wait、最终双图节点/UART 复核和运行期连续 UART owner 监控。

语音 stop 与固定 `trash_bin_staging` 两种生产 JSON 已被严格 parser 接受，记为
`VOICE_BRIDGE_EXACT_PAYLOAD_READONLY_PASS`；这只证明 schema 精确一致，不关闭上述阻塞。

## 唯一所有权

| 资源 | 唯一 owner | 禁止项 |
| --- | --- | --- |
| `/dev/ttyTHS0` | ROS1 `limo_base_node` | ROS2 `limo_base`、第二个 ROS1 driver、调试串口程序 |
| ROS2 安全输出 | `limo_cleanup_base/tracked_base_controller` | Nav2、teleop 或脚本直接绕过网关 |
| ROS1 `/cleanup/base/safe_cmd_vel` | 单个受限 `ros1_bridge` 发布者 | teleop、手柄或脚本直接注入 |
| ROS1 `/cleanup/base/driver_cmd_vel` | 单个 fail-closed timeout/watchdog 发布者 | bridge、teleop、手柄或脚本直接发布 |
| ROS1 `/cmd_vel` | 自动模式下无端点 | bridge、watchdog、teleop 或脚本使用该公开入口 |
| 物理急停 | 现场主开关观察员 | 语音 cancel 或软件停车替代物理断电 |

所有权判断必须同时检查进程、ROS1 图、ROS2 图和 UART 占用。只检查其中一个系统不能证明
安全，因为 ROS1 与 ROS2 节点不会出现在同一张原生 ROS 图中。

## 目标数据流

```text
ROS2 task/Nav2 request
  -> /cleanup/base/cmd_vel_request
  -> ROS2 tracked_base_controller
  -> /cleanup/base/safe_cmd_vel
  -> 受限 ROS1/ROS2 bridge（仅 Twist 2 -> 1）
  -> ROS1 /cleanup/base/safe_cmd_vel
  -> ROS1 fail-closed timeout/watchdog 适配器
  -> ROS1 /cleanup/base/driver_cmd_vel
  -> ROS1 limo_base_node（原 /cmd_vel 订阅 remap 到私有 driver 话题）
  -> /dev/ttyTHS0
  -> 底盘控制器
```

桥接实现必须保留以下语义：

- ROS2 安全网关仍是自动任务的唯一限速、超时和授权门；
- bridge 只传递 `geometry_msgs/Twist`，不得自行生成、保持或重放速度；
- 生产 bridge 必须显式限制话题和方向，命令只允许 ROS2 → ROS1 单向传递，禁止回环和
  `--bridge-all-topics`；明确禁止桥接 ROS1/ROS2 `/cmd_vel` 与
  `/cleanup/base/driver_cmd_vel`；
- ROS1 侧必须增加独立的 fail-closed timeout/watchdog 适配器，并由它作为私有
  `/cleanup/base/driver_cmd_vel` 的唯一发布者；ROS1 `limo_base_node` 的原 `/cmd_vel` 订阅必须
  remap 到该私有话题；
- ROS1 watchdog 默认禁止运动、订阅队列深度为 `1`，拒绝非有限值和非平面轴；启动时输出零，
  输入 lease 超时后持续输出零，且不得在重连或重启后恢复旧的非零命令；初始 lease 上限为
  `0.25 s`；
- ROS1 自动模式下公开 `/cmd_vel` 必须无端点，键盘 teleop、手柄和其他速度发布者必须停止；
- bridge、ROS2 网关或授权心跳任一退出时，ROS1 适配器必须在 lease 内归零；
- ROS1 适配器自身异常退出时，还必须依赖已经现场验证的 `limo_base_node`/底盘命令超时停止。
  该超时行为尚无验收证据，因此在完成断链测试前禁止 bridge 非零运动；
- 进程重启后不得恢复旧的非零命令；
- ROS1 driver 停止并确认 UART 释放后，才允许进行任何独立串口诊断。

首版桥接白名单只考虑 `geometry_msgs/Twist` 从 ROS2 到 ROS1，以及 `/odom`、`/imu` 从 ROS1
到 ROS2。`/limo_status` 必须先核对 ROS1/ROS2 消息定义并检查 bridge `--print-pairs`；`/tf` 与
`/tf_static` 必须先完成唯一所有权审计，禁止盲桥。ROS1 watchdog 节点名、launch、消息方向和
`limo_base_node` 的命令超时行为都必须通过源码与运行时图确认后再写入启动命令。

## 永久禁止的并发组合

- `~/agilex_ws` 的 ROS1 `limo_base_node` 与
  `/home/agilex/limo_ros2_ws` 的 ROS2 `limo_base` 同时运行；
- ROS1 `limo_teletop_keyboard.launch` 与 ROS2 自动清理 bridge 同时向底盘命令链发布；
- ROS1 driver 活跃时启动 `tracked_base_vendor_stage2.launch.py`；
- 桥接 `/cmd_vel` 或 `/cleanup/base/driver_cmd_vel`，绕过 ROS1 timeout/watchdog 适配器；
- 任一 driver 活跃时运行串口探针、第二个底盘 driver 或直接打开 `/dev/ttyTHS0` 的脚本；
- 用“ROS2 图为空”推断 UART 空闲，或用“ROS1 图为空”推断 ROS2 driver 不存在。

发现上述任一组合时必须先归零并停止命令发布者，再停止非权威 driver，最后确认
`/dev/ttyTHS0` 只有 ROS1 `limo_base_node` 或完全无 owner。

## 分级验收

1. **ROS1 基线复验**：只启动 ROS1 `limo_start.launch`，确认唯一 `limo_base_node`、UART
   owner 和状态话题；键盘短动仅用于人工复验，结束后停止 teleop。
2. **离线契约回归**：对 bridge 白名单/方向、ROS1 watchdog 的默认禁动、有限值/轴约束、
   queue=1、启动零、lease 超时、重启不恢复旧值以及私有 driver 话题唯一发布者规则做自动测试，
   不接 UART。
3. **bridge 零速验收**：ROS1 driver 保持唯一 UART owner；ROS2 安全网关只输出零；bridge 与
   ROS1 watchdog 接通后，私有 `/cleanup/base/driver_cmd_vel` 只能收到连续全零，公开
   `/cmd_vel` 无端点，且两侧均无额外命令发布者。
4. **断链验收**：分别停止授权心跳、ROS2 网关和 bridge，确认 ROS1 watchdog 在 lease 内归零；
   再单独验证 watchdog 异常退出时 `limo_base_node`/底盘自身会在有界时间内停车。
5. **bridge 单次短脉冲**：重新取得现场单次授权后，参数必须在独立试验单中审批，并以 ROS1
   已观测的最低有效值为依据；不得由此前物理零动作推断死区、自动加量或自动重试。每次只
   验证一个已审批档位，同时记录 ROS2 网关输出、bridge 两侧消息、ROS1 私有 driver 命令、
   里程计和物理方向。
6. **导航接入**：只有前五级通过后，Nav2 才能向 ROS2 请求话题提交速度；不得直接发布
   ROS1 公开 `/cmd_vel`、私有 driver 话题或绕过 ROS2 安全网关。

当前仅第 1 级已有物理运动成功证据；第 2 级已有本地实现和离线检查，但被上述安全审计重新
阻塞，尚未完成 Catkin/跨图/机器人验收；第 3～6 级均未通过。

## 启停原则

启动顺序：

1. 清除 ROS1/ROS2 历史 teleop、Nav2、bridge 和第二底盘 driver；
2. 先启动 ROS1 timeout/watchdog 并保持锁定全零，确认它是
   `/cleanup/base/driver_cmd_vel` 唯一发布者，公开 `/cmd_vel` 无端点；
3. 再启动唯一 ROS1 `limo_base_node` wrapper，使 driver 一订阅私有话题就收到连续零，并确认
   `/dev/ttyTHS0` 唯一 owner；
4. 启动 ROS2 安全网关，保持 `allow_base_motion=false`；
5. 启动 bridge 并完成全零、lease 超时与唯一发布者检查；
6. 只有断链停车也通过后，才允许上层任务请求运动。

停止顺序：

1. 撤销 ROS2 运动授权，并确认 ROS2 安全输出与 ROS1 私有 driver 命令均连续归零；
2. 停止上层任务/Nav2；
3. 停止 bridge，并保持 ROS1 watchdog 至少一个 lease 周期，确认
   `/cleanup/base/driver_cmd_vel` 持续全零且公开 `/cmd_vel` 仍无端点；
4. 在 watchdog 仍持续发布私有全零时停止 ROS1 `limo_base_node`，确认 `/dev/ttyTHS0` 已释放；
5. 最后停止 ROS1 watchdog。

在 ROS1 driver/底盘自身命令超时尚未验收前，driver 不得在 watchdog 停止后继续存活。

任何物理运动前仍需当次通知现场人员；机械臂和夹爪授权与本契约相互独立。
