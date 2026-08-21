# ROS1 Noetic 底盘桥接实现说明

状态：本地实现与离线测试已准备；机器人端 `ros1_bridge` 可用性、ROS1 overlay 构建和现场零速
拓扑尚未执行。当前仍为 **fail-closed / 禁止真实运动**。

## 2026-08-12 D 审计 REJECT 后的权威安全基线

本节覆盖本文后续仍可能残留的旧 v2/vendor wrapper 描述。当前内部协议是
`cleanup_navigation_bridge/v3`，生产导航入口不再存在
`move_base_private_request.launch`，也不再 include vendor
`limo_navigation_diff.launch`/`map1017`。

- 授权策略具有 sticky reauthorization latch。active 心跳失联、health unavailable、epoch 回退、
  active epoch 不匹配、跨 epoch nonce 重用或异常终态都会清 pending 并锁存授权 false。旧 active、
  旧 status 或单纯 health 恢复不能恢复授权；只有新的合法 voice intent 使用新的持久化 epoch、恢复后
  的新 nonce 完整 dispatch 才能清 latch。
- ROS1 adapter 使用 `RLock + GoalGenerationGate + 单槽 dispatch worker`。cancel/fault 先递增
  generation 并 `cancel_all_goals()`；仍在队列中的旧 send 必然因 generation 不匹配被丢弃，旧 result
  callback 也不能完成新 goal。ROS1 watchdog 使用锁和 lease generation，subscriber/timer/shutdown 的
  计算与 publish 串行；clear/fault 后旧非零 snapshot 不再有效。
- 地图生产输入是 canonical manifest `limo_v1_map_binding/v1`，不是裸 `map_id`。manifest 绑定
  `active_map_id`、`map` frame、YAML/PGM realpath/size/SHA-256、唯一且有限的 map metadata、integrated
  mode、`/cleanup/base/cmd_vel_request` 和 14 项冻结 V1 release SHA。canonical bytes 为 UTF-8 JSON、
  `sort_keys=true`、`separators=(',', ':')` 且不含自引用 digest；外部 token 为
  `V1_MAP_BINDING_PASS_V1:<binding_sha256>`。
- manifest、runtime lease、YAML/PGM 和 14 个 release 文件全部经过同一 secure-open helper：从绝对路径
  根开始逐级 `openat(O_DIRECTORY|O_NOFOLLOW)` 固定并复核 ancestor identity，最终文件以
  `openat(O_NOFOLLOW)` 打开，FD 读取前后核对 regular-file identity/size/mtime/ctime，并再次打开整条目录
  链。拒绝 ancestor/final symlink、路径替换、读中替换、目录逃逸、空文件、可写 map root、stem/id
  不同、非同目录 `<id>.pgm`、metadata/阈值异常、sentinel、`map02`、`map1017` 和任何冻结 release SHA
  漂移。
- 唯一生产入口是 `run_v2_bridged_navigation.py`：同步执行首次 binding/release 验证→最长 60 s 的本轮
  V1 scan/odom/TF/owner preflight→最终全量 secure revalidate→在 runner 私有 0700 目录用
  `O_CREAT|O_EXCL|O_NOFOLLOW` 写入 0600 短租约→启动独立 continuous monitor。monitor 只有完成自身全量
  重验后才通过继承的私有 pipe FD 回送 digest-bound READY；runner 收到 map monitor READY 前不会 spawn
  core。随后私有生成并恰一次 spawn map_server/AMCL/move_base，等待 continuous topology monitor 的
  `POST_CORE_READY` 后才 spawn adapter/ROS2 navigation consumer，再等 `FULL_READY` 才进入运行态。旧
  `v2_bridged_navigation_internal.launch` 已删除且不安装，不能直接 roslaunch 绕过 runner。
- core 启动后 monitor 任一漂移会退出；runner 随即 TERM/KILL 整个 core/adapter launch process group。
  adapter shutdown cancel、move_base request 消失及下游 0.25 s lease 共同归零，runner 不自动重启，保持
  sticky BLOCK。
- cleanup 固定为停止非零 producer→两侧新的连续 10 零窗口→TERM/KILL/wait driver→证明 ROS 节点消失
  和 UART 释放→才允许拆 monitor/bridge/gateway/watchdog/master。driver 仍存活时 cleanup 状态机进入
  `retain_safety`，保留零链并返回 BLOCK，绝不报告 cleanup PASS。
- ROS2 endpoint 校验保留 multiset，并要求非空、非零、唯一 GID；相同 FQN 的重复 endpoint 不再被 set
  去重隐藏。ROS1 navigation continuous monitor 还精确要求唯一 YDLidar、`/odom` limo_base、`/tf` 的
  AMCL+limo_base+三条 vendor static-TF owner，并要求 `/tf_static` 零 publisher。adapter 要求 10 条连续
  4.8–7.2 Hz、360°、至少 360 beams、finite ratio>=5%、0.02–16.0 m metadata 的 scan 窗口，stamp 严格
  单调；TF 按 map→odom→base_link→laser_link 逐段检查有限值、归一四元数和 receipt freshness。
- `goal_timeout` 从 launch 显式传入，默认 120 s；边界到达即 sticky cancel。zero-stage 不再接受三个可
  复用 `YES` 环境变量，而是消费 mode 600、绑定 boot ID、最长 300 s、原子 rename 的一次性授权文件。

当前 `navigation_intent_bridge.launch.py` 仍硬编码 `allow_base_motion=false`，因为尚无已验收的生产
`/cleanup/base/safety_clear` 唯一 source。因此这些修复关闭本地 P0/P1 代码缺口，但不构成非零现场
授权，也不把 bridge 变成 V1 阻塞项。

版本定位：V1 使用 ROS1 原生底盘和 ROS1 原生导航完成扫描避障，本文 bridge **不是 V1
阻塞项**。bridge 主要服务 V2/V3，把 ROS2 高层安全速度请求接入已验证可动的 ROS1 底盘。
V2 已删除“到这里来/说话人定位”；本实现不定义、不桥接也不推断任何说话人目标。

## 数据流与固定话题

```text
ROS2 task velocity request or bridged ROS1 move_base request
  -> ROS2 /cleanup/base/cmd_vel_request
  -> ROS2 tracked_base_controller
  -> ROS2 /cleanup/base/safe_cmd_vel
  -> ros1_bridge dynamic_bridge (geometry_msgs/Twist, ROS2 -> ROS1)
  -> ROS1 /cleanup/base/safe_cmd_vel
  -> ROS1 cleanup_ros1_safe_cmd_vel_watchdog
  -> ROS1 /cleanup/base/driver_cmd_vel
  -> remapped ROS1 limo_base_node /cmd_vel subscription
  -> /dev/ttyTHS0
```

V2/V3 高层导航使用单一原子命令和单一状态闭环：

```text
ROS2 exact voice intent
  -> ROS2 navigation consumer + persistent monotonic epoch
  -> /cleanup/navigation/bridge_command (String, epoch + one-time nonce)
  -> bridge ROS2 -> ROS1
  -> ROS1 atomic navigation adapter
  -> ROS1 move_base
  -> /cleanup/navigation/bridge_status
     (ready/active/succeeded/aborted/preempted/rejected/unavailable/stopped)
  -> bridge ROS1 -> ROS2
  -> authorization=true only for fresh matching active epoch
  -> ROS1 /cleanup/base/cmd_vel_request
  -> bridge ROS1 -> ROS2 (request only)
  -> ROS2 tracked_base_controller
  -> ROS2 /cleanup/base/safe_cmd_vel
  -> bridge ROS2 -> ROS1 (safe output only)
  -> ROS1 watchdog -> /cleanup/base/driver_cmd_vel -> limo_base_node
```

请求与安全输出使用不同 topic，因此没有命令回环。installed V1 public wrapper/core 均为 native-only，
只能输出 `/v1/nav_cmd_vel`。V2 integrated runner 不 include 它们，而是在通过 binding、pre-core、sealed
snapshot 与 monitor READY 屏障后私有生成唯一 map_server、AMCL、move_base，并把 move_base `/cmd_vel`
硬 remap 到唯一私有 request `/cleanup/base/cmd_vel_request`；公开 `/cmd_vel` 仍必须零端点。

桥接两侧故意使用同名 `/cleanup/base/safe_cmd_vel`，因此不依赖 `dynamic_bridge` 的 CLI remap。
桥的方向由“ROS2 唯一发布者 + ROS1 唯一订阅者”触发为 ROS2→ROS1。bridge 永远不直接发布
ROS1 `/cmd_vel`；ROS1 watchdog 是 driver 私有话题的唯一发布者，vendor `/cmd_vel` 在包装
launch 内硬重映射到该私有话题。

启动命令只使用默认 `dynamic_bridge`，明确禁止 `--bridge-all-topics`。命令路径的白名单由
双侧精确 endpoint 拓扑形成：ROS2 safe 话题只有 gateway 发布、bridge 订阅；ROS1 safe 话题
只有 bridge 发布、watchdog 订阅。公开 `/cmd_vel` 和私有 `/cleanup/base/driver_cmd_vel`
不得跨桥；ROS2 侧发现 driver 私有话题任何端点也会立即 BLOCK。

V2/V3 内部控制面只桥两个标准 `std_msgs/String` JSON 话题：

| 方向 | 话题 | 语义 |
| --- | --- | --- |
| ROS2→ROS1 | `/cleanup/navigation/bridge_command` | `cancel` 或一个原子的 `dispatch_goal`；goal 与 epoch、adapter one-time nonce 同包 |
| ROS1→ROS2 | `/cleanup/navigation/bridge_status` | 20 Hz readiness/result 心跳，含 state、最高 epoch、新 nonce、server_ready、scan_fresh、tf_ready |

旧 `/cleanup/navigation/goal`、`stop`、`cancel`、`rearm` 四话题协议已禁用，并在 ROS1/ROS2
拓扑 verifier 中要求零端点。这样 cancel 后延迟 goal、旧 rearm、重复消息和跨话题乱序不能重新
授权：每个 dispatch 必须使用 adapter 最新 nonce，adapter 接受前先消费并轮换 nonce；epoch
必须严格递增。完全相同的 active 命令重复到达时只作幂等确认，不再次发送 goal。cancel 不依赖
nonce且可重复，但只能 cancel all、轮换 nonce、撤销授权，使系统更安全。

语音 V2 的已验证高层入口保持在 ROS2 内部，不跨 ROS1 bridge：

```text
/cleanup/navigation_intent  std_msgs/String(JSON)
```

ROS1 精确拓扑 verifier 要求该话题在 ROS1 图上保持零发布者、零订阅者；发现任何 ROS1 endpoint
即 BLOCK。preflight 虽验证标准 String pair 已编译，但这只证明环境能力，不授权桥接该话题。

只接受以下两个精确 JSON 契约，未知字段、格式错误、缺少安全位或其他 action 全部 fail-closed：

```json
{"action":"cancel_navigation","request_safe_stop":true}
```

```json
{
  "action":"navigate_to_waypoint",
  "target_id":"trash_bin_staging",
  "target_source":"fixed_map_waypoint"
}
```

消费者没有 `Twist` 或 Pose publisher。`cancel_navigation` 生成内部原子 cancel，同时立即并持续
发布 authorization=false；ROS2 gateway 因撤销授权持续输出零，ROS1 watchdog 收到零后替换旧
lease，并在 bridge/gateway 失联时最迟按 0.25 s lease 持续归零。“到这里来”、说话人目标和
速度字段均不支持。

`trash_bin_staging` 只有在 waypoint 文件 `map_id` 与当前 V1 地图 ID 精确一致、条目存在、
`frame_id=map`、坐标/朝向有限，且 ROS1 status 新鲜、server_ready=true、scan_fresh=true、
tf_ready=true 时才派发。内部协议已版本化为 `cleanup_navigation_bridge/v3`；语音 exact schema 不变。
仓库只提供
`config/v1_navigation_waypoints.example.yaml` 空 schema，不包含虚构坐标；现场必须在 V1 地图完成后
写入实测 waypoint。

当前地图状态明确锁定为 `map_id=NOT_AVAILABLE_MAP_NOT_FROZEN`，且
`trash_bin_staging=NOT_AVAILABLE_UNMEASURED`；空 schema 会继续拒绝 waypoint。任何坐标只有在
V1 地图冻结和现场测量后才能录入。适配器启动时默认 stopped，launch 默认
`enable_navigation_bridge=false`。路径规划和避障仍由 ROS1 move_base 完成，底层速度继续经过
safe Twist bridge 与 watchdog。录入与验收逐项见 `docs/trash_bin_staging_field_acceptance.md`；
vendor 当前静态入口 `map1017.yaml` 只作只读参考，不是项目冻结地图。

## 新增组件

- `ros1_overlay_src/limo_cleanup_ros1_base`：独立 Catkin 包，可叠加到机器人 Noetic
  `~/agilex_ws` 之上，不改原厂工作区。
- `fail_closed_cmd_vel_watchdog.py`：启动即零、队列深度 1、单调时钟 lease、非法轴和
  `NaN/Inf` 归零、默认 `allow_nonzero=false`、ROS1 侧再次限速。
- `safe_cmd_vel_watchdog_zero.launch`：零速阶段硬编码禁止非零，不暴露运动开关。
- `limo_start_private_cmd.launch`：默认不启动 vendor；显式硬件授权后才 include
  `limo_bringup/limo_start.launch`，并把绝对 `/cmd_vel` remap 到
  `/cleanup/base/driver_cmd_vel`。不包含键盘 teleop。
- `ros1_base_bridge_preflight.sh`：只读核对 Noetic/Foxy/Cyclone、`dynamic_bridge`、编译出的
  `geometry_msgs/Twist`、`geometry_msgs/PoseStamped`、`std_msgs/Bool`、`std_msgs/String` 配对、
  vendor launch
  静态节点、UART 身份/空闲、双 ROS 图和命令话题零端点、现场三项当次确认。
- `fail_closed_navigation_adapter.py`：解析单一原子 String 命令，校验严格 epoch/nonce/goal schema，
  把目标接到 ROS1 `/move_base` action；done callback 回传 succeeded/aborted/preempted/rejected，
  server、`/scan` 新鲜度或 `map→base_link` TF 任一失效即回传 unavailable、cancel all；cancel/退出
  回传 stopped。YDLidar 已知约 6 Hz，因此 adapter 默认要求 `/scan` 的接收时间与 source stamp 都
  小于 0.5 s，并要求 TF source stamp 小于 0.5 s；边界 `>=0.5 s` 即 false。
- `navigation_health.py`：ROS1-only 纯策略，严格处理 scan/TF 时间戳、未来时间、时间回拨与
  move_base/scan/TF 三门 AND 逻辑，供 adapter 与离线行为测试共用。
- `navigation_bridge_adapter.launch`：默认禁用 V2/V3 高层导航桥，不影响 V1 原生导航。
- `navigation_intent_consumer.py` 与 `navigation_intent_bridge.launch.py`：默认禁用的 ROS2
  `std_msgs/String` JSON 消费者；上游只接受 exact stop/cancel 和固定 `trash_bin_staging`；内部
  epoch 原子落盘，只有 fresh matching active status 才授权，不发布速度或 Pose。
- `navigation_topology_verifier.py`：ROS2 源端连续 owner 审计，能识别被 ROS1 图隐藏的 rogue
  goal/rearm/cmd_vel_request publisher，并按 endpoint multiset、唯一 GID、exact type/QoS 约束
  command/status/request/authorization/topology/safety/safe 的唯一 owner。所有控制、授权、安全和 status
  topic 必须 VOLATILE；Foxy 无法返回 endpoint metadata 时 fail-closed BLOCK。
- `v1_navigation_waypoints.example.yaml`：无坐标的 fail-closed schema；只有现场 V1 地图完成后才可
  复制并填写实际 `map_id` 与 `trash_bin_staging`。
- `map_binding.py`、`validate_v1_map_binding.py`、`verify_v1_map_binding_runtime.py`：实现 canonical
  binding、全输入逐级 openat/FD/hash/TOCTOU 校验、14 项冻结 release SHA、私有 FD ready handshake 和持续守卫。
- `run_v2_bridged_navigation.py`：唯一生产编排入口；同步完成 preflight 后最终重验，等待独立 monitor
  的私有 FD READY。它不 include installed V1 launch/core，而是从 release-bound interface JSON 生成
  0600 私有 launch，各且仅各一份 map_server、AMCL、move_base；地图 YAML/PGM 与 6 个 rosparam 配置
  从 sealed memfd snapshot 消费，move_base 输出硬固定为 `/cleanup/base/cmd_vel_request`，且不启动 V1
  guard、driver 或 watchdog。
  `v2_bridged_navigation_internal.launch` 不存在且不安装。
- `verify_ros1_bridge_ros2_zero_output.py`：ROS2 侧只订阅验证，要求安全网关唯一发布、bridge
  和 verifier 两个订阅、公开命令话题零端点、至少 10 条六轴全零。
- `verify_ros1_base_bridge_topology.py`：ROS1 侧只订阅验证，要求 bridge→watchdog→driver
  私有链精确所有权、普通 `/cmd_vel` 零端点以及至少 10 条全零；V2/V3 设置
  `_navigation_expected:=true` 后还要求 move_base request 只从 ROS1→ROS2，command 只从
  bridge→adapter，status 只从 adapter→bridge，旧四话题与 navigation_intent 在 ROS1 图零端点。
- `run_ros1_base_bridge_zero_stage.sh`：无参数只跑 preflight；只有
  `--execute-zero-stage` 加 owner-only、boot/expiry 绑定的一次性授权文件才可能进入打开 UART 的流程。
  进入 READY 前还会精确比对 `/dev/ttyTHS0` owner PID 与 `/limo_base_node` PID，并保持
  ROS1/ROS2 两个连续拓扑 monitor；任何 owner、公开端点、样本或必要进程变化都会触发清理。

## 本地构建 ROS1 overlay（机器人现场待执行）

以下只准备独立 overlay，不启动节点：

```bash
mkdir -p /home/agilex/limo_cleanup_ros1_ws/src
cp -a /home/agilex/limo_cleanup_ws/ros1_overlay_src/limo_cleanup_ros1_base \
  /home/agilex/limo_cleanup_ros1_ws/src/
source /opt/ros/noetic/setup.bash
source /home/agilex/agilex_ws/devel/setup.bash
cd /home/agilex/limo_cleanup_ros1_ws
catkin_make
```

构建后以 ROS1→ROS2 顺序 source：Noetic、原厂 `agilex_ws`、本项目 ROS1 overlay、Foxy、
ROS2 cleanup overlay。`ros1_base_bridge_preflight.sh` 会按这个顺序自行 source，并阻塞缺失项。

## 只读现场审计

不提供一次性授权文件时，preflight 必须以 `ROS1_BASE_BRIDGE_PREFLIGHT_BLOCKED` 结束；这可用于
先核对软件缺口。未来现场零速阶段必须创建 mode 600 的一次性文件，精确包含六行：schema、当前
boot ID、不超过 300 s 的 expiry、physical checklist、E-stop 和 command-mode write acknowledgement。
execute runner 会把它原子 rename 为 `.consumed.<pid>`，因此不能跨运行复用：

```bash
export ROS1_BASE_ZERO_STAGE_AUTHORIZATION_FILE=/tmp/limo_zero_stage_auth.<UNIQUE>
bash /home/agilex/limo_cleanup_ws/scripts/ros1_base_bridge_preflight.sh
```

只有精确输出 `ROS1_BASE_BRIDGE_PREFLIGHT_PASS` 才能讨论下一步。脚本不会启动节点、打开串口或
发布消息。

## 零速阶段（当前禁止自行执行）

下面命令会在全部门禁通过后启动 ROS1 vendor driver，可能打开 `/dev/ttyTHS0` 并改变硬件
状态。它只能在机器人架空/托轮、物理断电观察员就位、用户对当次操作重新授权后运行：

```bash
bash /home/agilex/limo_cleanup_ws/scripts/run_ros1_base_bridge_zero_stage.sh \
  --execute-zero-stage
```

顺序固定为 watchdog → ROS2 零网关 → dynamic bridge → ROS2 连续零 verifier → ROS1
无 driver 拓扑与 10 条连续零证明 → UART 空闲复核 → ROS1 vendor。任何证明失败都不会启动
vendor。运行期间持续复核 UART owner；清理先停止所有非零 producer，并在 ROS1/ROS2 两侧各取得
新的连续 10 零窗口；随后才对 driver 执行 TERM→有界等待→必要时 KILL→wait，并证明节点消失和
UART 释放。只有 driver 已消失才停止 monitor/bridge/gateway/watchdog/自有 master。driver 仍存活时
保留零安全链并 BLOCK。任何残留使流程失败。

当前零速 launch 在 ROS2 和 ROS1 两层都硬编码拒绝非零，即使有人向 ROS2 请求话题注入非零，
也不能进入 ROS1 driver。真实短脉冲需要另行设计 Stage 3 launch、断链停车实测和新的单次
现场授权；本实现没有提供非零启动入口。

## V2/V3 必测验收项

1. **stop/cancel 优先级**：ROS2 gateway 在撤销授权、安全许可或 cancel 时立即清空旧请求并
   输出零；同一私有 Twist 流保持 FIFO。ROS1 watchdog 收到零后立即替换仍新鲜的非零 lease，
   后续 timer 不得恢复旧命令。导航层 cancel 同时调用 ROS1 move_base
   `cancel_all_goals()`、轮换 nonce 并锁存 stopped；旧 goal/rearm 四话题零端点。
   `/cleanup/navigation_intent` 的 cancel 必须精确包含 `request_safe_stop=true`；消费者在任意
   pending/active 阶段收到 cancel 后都清除 epoch 并持续撤销授权。
2. **失联持续归零**：bridge 或 ROS2 gateway 不再送达新样本时，ROS1 watchdog 在不晚于
   `0.25 s`（比较条件为 `>= lease_timeout`）进入零输出，并在后续每个发布周期持续发零。
3. **driver 互斥**：ROS1 `limo_base_node` 是 `/dev/ttyTHS0` 唯一 owner；ROS2 `limo_base`、
   第二 ROS1 driver 和串口探针均不得并发。preflight 同时检查进程、ROS1 图、ROS2 图和 UART。
4. **公开 `/cmd_vel` 不桥接**：ROS1 vendor 订阅已硬 remap 到私有
   `/cleanup/base/driver_cmd_vel`。ROS1 和 ROS2 两侧 `/cmd_vel` 都必须保持零发布/零订阅
   端点；两个运行时 verifier 任一发现公开端点都立即 BLOCK，禁止依赖 bridge 自动发现继续运行。
5. **源端 owner**：ROS2 verifier 必须识别任意 rogue goal/rearm/cmd_vel_request publisher；
   command/status/request/authorization/safe 各话题 owner 必须精确匹配，不能以 ROS1 图只看到
   `/dynamic_bridge` 作为源端安全证明。
6. **结果与传感器闭环**：只有 fresh、同 epoch、state=active、server_ready=true、scan_fresh=true、
   tf_ready=true 才可授权。succeeded、aborted、preempted、rejected、unavailable、stopped、
   `/scan`/TF 过期或 0.25 s status 失联全部立即授权 false。vendor 当前 `pub_odom_tf=false`，因此
   未证明另有唯一且新鲜的 `odom→base_link`/`map→base_link` TF 链时必须保持 BLOCK；不得伪造 TF。
7. **乱序/重放**：旧 epoch、旧 nonce、cancel 后延迟 goal、不同内容同 epoch 和终态后重放全部
   拒绝并 fail-closed；完全相同 active 命令重复只能幂等确认，不可二次 send_goal。

V1 的 ROS1 原生导航接口、地图/扫描和避障验收由 V1 单独完成；不得为了等待本 bridge 延迟
V1，也不得把 V1 的 ROS1 `/cmd_vel` 所有权规则混入 V2/V3 自动桥接会话。两种运行模式必须
在启动前显式互斥。

V1 只读静态事实同时记录为风险输入：YDLidar `/scan` frame 为 `laser_link`、约 6 Hz；ROS1 base
driver 订阅公开 `/cmd_vel` 并发布 `/odom`，但 `pub_odom_tf=false` 时不发布 `odom→base_link`。
vendor local costmap 使用 `global_frame=map` 且未设置 `expected_update_rate`；planner YAML 与速度频率
配置还存在未闭合差异。因此 bridge 不把 move_base 进程存在当作 readiness，必须等待 V1 对 TF、
scan freshness、costmap/planner 配置和频率冲突完成独立验收。

## `ros1_bridge` 审计结论边界

现有 WSL 包含默认 Ubuntu 26.04、Ubuntu-24.04 和 Ubuntu-22.04。最终离线测试固定使用
Ubuntu-24.04（Python 3.12.3、pytest 7.4.4）；它可用于纯 Python、XML 和 `bash -n`，但没有 ROS1
Noetic/catkin，也没有可用于
本项目现场链的 `ros1_bridge`。因此本轮不能证明机器人已安装或正确构建 bridge；Catkin runtime、
roslaunch runtime 和硬件链仍为 `NOT_RUN`。机器人端必须由 preflight 取得以下只读证据：

1. `ros2 pkg prefix ros1_bridge` 成功；
2. `ros2 pkg executables ros1_bridge` 精确包含 `dynamic_bridge`；
3. `dynamic_bridge --print-pairs` 精确包含 `geometry_msgs/Twist`；
4. Noetic `limo_bringup/limo_start.launch` 静态展开包含 `/limo_base_node`，且不含 teleop、
   Move Base 或 Nav2 命令源；
5. ROS1/ROS2 图和 `/dev/ttyTHS0` 在启动前均无冲突 owner。

以上任一项缺失即保持 `ROS1_ROS2_BASE_BRIDGE_IMPLEMENTED_LOCALLY_UNVERIFIED`，并继续禁止
机器人同步、跨图启动和真实运动。该标签表示“代码已在本地实现，但现场能力未获证明”，
不等于 ready。

2026-08-11/12 独立安全审计要求的 ROS2 源端精确 owner topology、导航结果闭环、原子
epoch/nonce 防重放、vendor 前连续零证明、adapter/watchdog generation 竞态保护、sticky
reauthorization 以及 TERM→KILL→wait/双图/UART cleanup 已在本地源码和行为模型中实现；这只关闭
本地代码缺口。Catkin/roslaunch/ros1_bridge runtime、真实 scan/TF owner/data、UART 唯一 owner 与硬件
清理仍未运行，因此仍不得同步机器人或进入现场 bridge 阶段。

## 2026-08-12 最终离线复核快照

- ROS1 bridge package：`94 passed`；ROS2 base 非-linter 全目录：`75 passed`。
- dependency-free bridge runner：`ROS1_BASE_BRIDGE_OFFLINE_TEST_PASS: 9 groups`；V1 交叉回归：
  `ROS1_V1_NAVIGATION_OFFLINE_TEST_PASS: 29 tests`。
- `bash -n` 2 个生产 shell PASS；bridge+V1 launch XML 9/9 PASS；
  `ROS1_CATKIN_OVERLAY_AUDIT_PASS`。
- 当时冻结的 V1 release SHA 全部 MATCH；当前实现使用 14 项全量 release 集合。`move_base_private_request.launch` 不存在，生产源码中 vendor
  `limo_navigation_diff.launch` 和 `--bridge-all-topics` 命中数均为 0。
- 只读 preflight 按设计输出 `ROS1_BASE_BRIDGE_PREFLIGHT_BLOCKED`，因为 Noetic/Foxy/vendor/overlay
  setup 和 ROS CLI 缺失；未启动节点、ROS master、vendor、UART 或速度发布。
- 状态：`RELEASED_FOR_D_READONLY_FULL_STACK_REVIEW`（仅指本地源码快照，不是机器人现场 RELEASE）。项目真实 map binding manifest、实测
  `trash_bin_staging` 与已验收 `/cleanup/base/safety_clear` source 尚不存在，非零 bridged mode 保持
  BLOCK。

## Exact ROS2 endpoint QoS 合同

所有行均要求 `RELIABLE / VOLATILE / KEEP_LAST`；不接受 transient-local 的旧控制、授权、安全或 status
样本。depth 是 endpoint 精确值，不是下界。

| Topic | Publisher（depth） | Subscriber（depth） | Type |
| --- | --- | --- | --- |
| `/cleanup/navigation_intent` | `/voice_dialogue`（10） | consumer（1） | `std_msgs/msg/String` |
| `/cleanup/navigation/bridge_command` | consumer（1） | `/dynamic_bridge`（10） | `std_msgs/msg/String` |
| `/cleanup/navigation/bridge_status` | `/dynamic_bridge`（10） | consumer（1） | `std_msgs/msg/String` |
| `/cleanup/base/cmd_vel_request` | `/dynamic_bridge`（10） | controller（1） | `geometry_msgs/msg/Twist` |
| `/cleanup/base/motion_authorized` | consumer（1） | controller（1） | `std_msgs/msg/Bool` |
| `/cleanup/navigation/topology_ready` | verifier（1） | consumer、controller（各 1） | `std_msgs/msg/Bool` |
| `/cleanup/navigation/topology_bootstrap_ready` | verifier（1） | consumer（1） | `std_msgs/msg/Bool` |
| `/cleanup/base/safety_clear` | 当前必须无 publisher | controller（1） | `std_msgs/msg/Bool` |
| `/cleanup/base/safe_cmd_vel` | controller（1） | `/dynamic_bridge`（10） | `geometry_msgs/msg/Twist` |

ROS1 adapter 的 `/cleanup/navigation/bridge_status` publisher 明确 `latch=False`，使 bridge status 保持
VOLATILE。未来若实现 safety source，必须先加入唯一 owner 与 depth=1 的同一 exact 合同；当前不允许手工
publisher 填门。

## 严格 JSON 与恶意输入处理

- voice intent、ROS1 status、ROS2 command 统一使用 duplicate-rejecting `object_pairs_hook`；该 hook 对
  nested goal 同样生效，不存在 last-key-wins。
- 拒绝 NaN/Infinity、非 object 顶层、state/action/operation/frame_id 非字符串、goal 非 object、重复
  action/state/operation/epoch/nonce/map_id 和重复 nested `goal.x/y/yaw/frame_id`。
- 所有上述解析失败均转换为 `ValueError`。ROS2 consumer 捕获后锁存 fault、持续
  authorization=false 并进入 cancel retry；ROS1 adapter 捕获后 generation invalidate、cancel all 并发布
  fail-closed status。进程不会因 `state=[]/{}` 的 unhashable `TypeError` 崩溃。

## 2026-08-12 当前 RELEASE 候选测试快照（取代本节之前的旧数字）

- Ubuntu-24.04 / Python 3.12.3 / pytest 7.4.4：ROS1 bridge `94 passed`；ROS2 base non-linter
  `75 passed`；QoS/strict JSON 定向 `49 passed`。
- dependency-free bridge 9/9 groups、V1 offline 29/29、Catkin overlay static audit PASS、`bash -n`
  2/2、launch XML 9/9。
- Catkin/ROS/ros1_bridge runtime、SSH、机器人、vendor、UART、硬件与速度均 `NOT_RUN`。
- 状态为 `RELEASED_FOR_D_READONLY_FULL_STACK_REVIEW`，不是现场 RELEASE；真实 map/waypoint/safety source
  缺失时非零 bridged mode 继续 BLOCK。

## 2026-08-12 第三轮 REJECT 后的实现增量

本节为当前权威实现说明；此前 source ACCEPT 作废。

- PRE_CORE 使用 binding 派生的 mandatory `map_file/active_map_id`，并把真实 preflight launch/script/policy 纳入 secure release SHA 集合。
- runner 在任何检查前持有全局 POSIX flock；所有五个不可逆 spawn 前逐次重验 binding、release、短租约和 sealed snapshot。SIGTERM/SIGINT 只触发一次受控退出，重复信号在 cleanup 期间被忽略。
- descendant cleanup 使用 subreaper、process group 与 run-id `/proc` sweep。TERM 与 KILL 后的两次 wait 都有界；任一失败被记录但不阻断后续进程组、snapshot 与私有目录清理。
- zero-stage controller 是导航期唯一 controller owner。ROS2 navigation launch 只启动 consumer/verifier，不启动第二 controller；PRE_CORE 专用只读 handoff verifier 精确检查 controller/dynamic_bridge/持续零 monitor 的 type、QoS、GID 与 owner 数量。
- snapshot manifest 支持 ROS param 的 dict/string 两种合法表示；其他类型与 strict JSON 异常均 BLOCK。
- scan 窗口要求十个连续健康样本。任一坏样本立即清窗；Tmini angle 参数固定为 `[-100°, +100°]`，4.8–7.2 Hz、frame/range/beams/finite ratio/source stamp/receipt freshness 仍全部门控。
- strict JSON 包装 `RecursionError`；adapter 在注册任何 subscriber/timer 前完成状态、publisher、queue、worker 和 stop latch 初始化；PrivatePipe 不再忽略未知 READY label。

离线结果：ROS1 `112/112`、ROS2 non-linter `79/79`、bridge offline 9/9 groups、V1 offline 35/35、Catkin static PASS、bash 2/2、launch XML 9/9、compileall PASS。Catkin/ROS/ros1_bridge runtime、SSH、机器人、vendor、UART、硬件和速度仍全部 NOT_RUN；真实 map/waypoint/safety source 缺失，所以非零 bridged navigation 保持 BLOCK。

### PrivatePipe 完整批次 READY 合同

`wait_for()` 不得在遍历 `_drain()` 返回值时提前 return。每个批次先完整验证，目标 READY 必须恰好一次且为该批最后一条；该调用允许的 intermediate 只可位于 READY 之前。unknown、wrong READY、duplicate READY、READY 后任意附加 label 均立即 BLOCK。这样已从 FD 读取的恶意记录不会被局部 `labels` 丢弃，也不能绕到后续 `require_fresh()` 之外。

对应最终回归为 ROS1 `117/117`，其余仍为 ROS2 79/79、offline 9/9 groups、V1 35/35、Catkin static、bash 2/2、XML 9/9、compileall PASS。

## 2026-08-12 PrivatePipe READY 后同阶段 heartbeat 合同修订

Linux pipe 不保留 `write()` 与 `read()` 的一一对应关系；monitor 先写 READY、紧接着写 heartbeat 时，runner 的一次 `os.read(4096)` 可以同时取得两条完整记录。因此完整批次合同不能要求 READY 一定位于批次末尾，但仍必须先验证完整批次，再允许 READY 改变 runner 状态。

当前精确合同：

- 目标 READY 在一个 `_drain()` 批次内必须恰好一次。
- READY 前只允许该 `wait_for()` 显式声明的 `allowed_intermediate`。
- READY 后只允许该 `wait_for()` 显式声明的 `allowed_following`，且生产调用只声明本阶段精确 heartbeat：MAP 对应 map heartbeat，FULL 对应 topology heartbeat；POST_CORE 不声明尾随标签。
- unknown、wrong READY、duplicate READY、跨阶段 heartbeat 或任何其他标签均 BLOCK。digest 不符、sequence 重复/回拨仍在 `_drain()` 中先行 BLOCK。
- 整批校验完成前不 return；合法尾随 heartbeat 已被同批消费并更新 freshness/sequence，不会丢失，也无需由后续 `require_fresh()` 再读取。

真实 OS pipe 测试分别执行 READY 与 heartbeat 两次 `os.write()`，并断言 runner 只执行一次 `os.read(4096)`：MAP_READY→MAP_HEARTBEAT 与 FULL_READY→TOPOLOGY_HEARTBEAT PASS；两阶段 READY→异类 heartbeat 均 BLOCK。最终回归为 ROS1 `120/120`、ROS2 non-linter `79/79`、offline 9/9 groups、V1 35/35、Catkin static PASS、bash 2/2、XML 9/9、compileall PASS。

新 SHA-256：`run_v2_bridged_navigation.py=5e3d0470c12f5daf95036ed2db8c1a88040112c6bffa47b3c285ebbfa6325854`；`test_runner_barrier.py=7bb861865fe7dea1bccab67733e19e86972f1f79793751f851c93fd61a431052`。ROS/Catkin runtime、SSH、机器人、vendor、UART、硬件和速度仍全部 NOT_RUN；该 source RELEASE 不解除 `NONZERO_NAV_BLOCKED`。
