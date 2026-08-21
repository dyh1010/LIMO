# Voice V2 ROS1/Noetic runtime audit

## 结论

系统运行时基线是 ROS1/Noetic。当前语音包的 `rclpy`、ament、ROS2 Python
launch、`ros__parameters` 配置、ROS2 smoke/preflight/aggregate 仍是历史实现，统一
标记为 `LEGACY_ROS2_OFFLINE_ONLY`；它们不能作为 Noetic 现场入口，也不能把
ROS2 dry-run 或 Vosk 离线通过提升为现场通过。

当前已增加纯软件 adapter core、默认零 publisher 的 `rospy` wrapper，以及默认禁用的
Catkin source preview。该 preview 已完成 Noetic/aarch64 目标机离线构建和私有 mock
graph 验证，但尚未作为完整现场语音链安装，也未连接 stop gate、导航 ACK 或
production ordinary owner。
因此当前状态必须保持：

```text
BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY
field_delivery_ready=false
```

ROS 无关的 parser、semantic schema、`voice_contract`、模型 intake、预录 WAV、
corpus readiness 与 acceptance fixture 仍可继续离线验证。旧 dialogue/stop/node
wrapper 依赖 `rclpy/std_msgs`，只能通过 import stub 做历史 source regression，不能再
笼统称为 ROS-independent runtime。

机器契约见 `fixtures/voice_ros1_noetic_runtime_contract.json`。其中
`ros1_noetic_adapter.py` 是不导入 ROS 的 fail-closed core；
`ros1_noetic_adapter_node.py` 是零 publisher 的 Noetic 薄包装；
`ros1_overlay_src/limo_cleanup_ros1_voice` 提供 source-preview Catkin metadata、入口和
默认 `enable_offline_adapter=false` 的 XML launch；其目标机离线 build 已有哈希绑定
证据，但未完成现场 install/production topology 验收。

## 已实现的最小离线 adapter

- 仅接受 `offline_text_mock`，并强制 `require_wake_word is True`；False、整数或字符串
  都在构造时拒绝。production profile、ROS publish 与 production output 开关同样拒绝。
- 普通意图只形成内存 pending，明确确认后也只产生 `/voice_mock/...` 内存计划；
  `actual_publish_count=0`。
- STOP 不等待 Agent，先清 pending，再递增 stop epoch；生成首发加两次有限重发的
  内部事件计划，750 ms 内重复输入复用同一 event。
- ACK 同时校验 `process_instance_id`、`event_id`、唯一 source allowlist
  `cleanup_ros1_stop_gate`、成功状态、接收端本地 monotonic deadline，以及 5 秒 future
  wall-time tolerance；ACK 只提供观察性，不会延迟 STOP。
- STOP request/broadcast schema v3 与 ACK schema v2 都把 `process_instance_id`
  放在严格 JSON 内；缺字段、错误进程或旧进程复用同一 `event_id` 均拒绝，不能依赖
  Python 外层 envelope 补相关性。
- producer 构造期用与 wire parser 相同的公开 identifier validator 复读
  `process_instance_id`；空、空白、bool、过短/过长或非法字符在生成事件前拒绝。
- core 使用显式 `RLock` 串行化 transcript/STOP/ACK；没有 service、action、Twist、
  `/dev`、底盘、机械臂或夹爪接口。

这些通过只证明纯软件 adapter contract，不是 live ROS、导航取消或机器人端到端证据。

## 已发现的 ROS2 假设

- `package.xml`、`setup.py`、ament linter 和安装索引属于 ament/ROS2。
- 六个 runtime wrapper 与 smoke probe 使用 `rclpy`；dialogue 还依赖 ROS2
  `CleanupStatus` 和 QoS。
- 两个 launch 文件使用 `launch_ros`，YAML 使用 `ros__parameters`。
- `voice_preflight` 使用 `ament_index_python`；`voice_v2_report` 通过 ROS2 wrapper
  复用 callback；旧 aggregate 会 source Humble 并运行 colcon。
- README、rollback 与 smoke 保留旧 ROS2 命令，仅允许作为隔离 mock 的历史复现。
- 旧 ROS1 base topology 不仅禁止 ROS1 `/cleanup/navigation_intent` endpoint，还固定
  `/dynamic_bridge` 为 `/cleanup/navigation/bridge_command` publisher；全 ROS1 端口必须
  由 base/integration 职责另行修改，voice 包不能单方面放开。

所有已知旧入口都列在 machine contract 的 `legacy_ros2_entrypoints` 中；source test
逐文件检查 `LEGACY_ROS2_OFFLINE_ONLY` 标记。生成的 `.egg-info` 只视为旧构建产物，
不是部署依据。

## 最小 ROS1 node ownership

| ROS1 node | owner | 职责 | action/service |
| --- | --- | --- | --- |
| `/voice_text_fixture` | test-only Catkin package | 明确 mock 文本输入 | 无 |
| `/voice_mock_topology_guard` | `limo_cleanup_ros1_voice` | 持续检查精确 owner，并控制输入 enable | 无 |
| `/voice_asr` | `limo_cleanup_ros1_voice` | 文本或本地 Vosk 到 transcript | 无 |
| `/voice_priority_stop` | `limo_cleanup_ros1_voice` | STOP 首发、有限重发、去抖、ACK 观察 | 无 |
| `/voice_semantic_agent` | `limo_cleanup_ros1_voice` | 只产生非 stop 高层 candidate | 无 |
| `/voice_dialogue` | `limo_cleanup_ros1_voice` | 唤醒、确认、超时、取消、mock 输出 | 无 |
| `/voice_tts` | `limo_cleanup_ros1_voice` | 可选反馈，默认禁用 | 无 |
| `/cleanup_ros1_stop_gate` | future integration package | 独立消费高层 stop，每 event 最多一次副作用 | 只调用 navigation adapter 的幂等 cancel relay；不得成为第二个 `/move_base` client；未实现 |
| `/cleanup_ros1_status_adapter` | future integration package | 只读 cleanup status | 无；未实现 |

Voice 不拥有 service、action client/server、`Twist`、pose、设备路径、底盘、机械臂或
夹爪接口。`/move_base` action server 归 `/move_base` node；未来唯一允许的 client 是
`/cleanup_ros1_navigation_adapter`，不是 voice node。

## ROS1 topic 与 transport 要点

所有 JSON 均使用合法 ROS1 类型 `std_msgs/String`，另以 `encoding` 指定严格 schema，
不使用伪类型 `std_msgs/String(JSON)`。控制、transcript、candidate、STOP 与 ACK 的
publisher/subscriber queue 均为 1，subscriber 要求 `tcp_nodelay=true`；只有诊断、
只读 status 和 mock input-enable 可以 latch。`/voice/intent` 永不 latch。

STOP 生产目标路径必须绕过 dialogue：

```text
/voice/transcript
  -> /voice_priority_stop
  -> /voice/priority_stop_request
  -> /cleanup_ros1_stop_gate (future, not implemented)
  -> idempotent cancel relay (future, not implemented)
  -> /cleanup_ros1_navigation_adapter (the only /move_base client)
  -> high-level navigation cancel observation
  -> /voice/stop_ack
```

`/voice/priority_broadcast` 只让 dialogue 清除 pending；dialogue 故障不得阻断 stop gate。
三次 attempt 只是 transport 重发，同一 event 下游 task/navigation cancel 最多执行一次。
ACK 必须关联 `event_id + process_instance_id`，并用接收端本地 monotonic deadline 判定
新鲜度；跨主机 payload monotonic 只用于源端审计，不能直接比较。旧、未来、错误、
非活跃 event ACK 一律拒绝。

ROS1 `rospy` 回调可能并发，不能沿用 ROS2 单线程 executor 的隐式串行。实现必须使用
单一串行 event loop 或显式锁，并维护 stop epoch：确认提交前 epoch 必须未变化；STOP
一旦发生，旧 pending 不能被竞争中的“确认”恢复。

## 普通意图 mock/确认隔离

默认 profile 是 `offline_text_mock`，声明名到 resolved 名精确 remap：

```text
/cleanup/natural_language  -> /voice_mock/cleanup/natural_language
/cleanup/navigation_intent -> /voice_mock/cleanup/navigation_intent
/cleanup/perception_intent -> /voice_mock/cleanup/perception_intent
```

三个生产名必须 0 publisher/0 subscriber；三个 mock 名必须仅
`/voice_dialogue` 一个 publisher、0 subscriber、非 latch。topology guard 必须持续检查，
不是只在启动前抽查；发现 rogue endpoint 时立即把 `/voice/mock_input_enable` 置 false，
ASR/text fixture 不得继续输入。

普通请求必须经过：完整“小莫小莫”唤醒 -> 单一无歧义 candidate -> pending -> 明确肯定
确认。未唤醒、否定、引用、元语言、多意图、超时或取消均不得产生普通输出。当前不允许
任何 production ordinary consumer。

## Vosk/“瓶子”证据门

用户要求的“瓶子” alias 已在意图层保持 canonical：`捡瓶子` 仍映射
`捡塑料瓶`，`识别瓶子` 仍映射 `识别矿泉水瓶`。但现有真人 WAV 实际说的是
“捡矿泉水瓶”，没有真人“捡瓶子”样本。

真人 A/B：

- unrestricted/no grammar：exact `2/4`，micro CER `0.357143`；
- bottle-only restricted grammar：exact `1/4`，micro CER `1.142857`；
- 两组 semantic safety `4/4`，普通发布均为 `0`。

因此 bottle-only grammar 状态是 `BLOCKED_ACCURACY_REGRESSION`。安全门不能替代识别
能力；当前推荐证据基线只能是 unrestricted/no grammar。兼容 grammar 只有在真实 WAV
的 exact/CER 与关键短语均不回退时才可升级。文件名或预置期望不得补写转写。
遗留 ROS2/offline ASR wrapper 和 YAML 默认均关闭受限 grammar；实验开关只接受显式
布尔 `true`。Vosk 的 `捡 / 矿泉水 / 瓶` 空格分词由解析器归一化，不改变下游
canonical，也不改变 ROS1 现场 `BLOCKED` 结论。
另有两次哈希绑定的 small-cn unrestricted first-complete 离线回放均达到 exact
`4/4`、micro CER `0`、semantic safety `4/4`、实际发布 `0`。该结果在最终报告中
作为实验候选单列；冻结 all-endpoints 基线 `2/4`、CER `0.357143` 不被改写，且
first-complete 结果不构成 Noetic 现场、真人麦克风或真实机器人端到端证据。

## 实现前阻塞项

1. Catkin source preview 与默认关闭的 ROS1 XML launch 已通过 Noetic/aarch64 离线
   target build；尚未作为完整现场链安装，也未做 production live ROS 拓扑验收。
2. 没有持续 exact-owner topology guard。
3. 没有独立 ROS1 stop gate、幂等 cancel 或真实 navigation ACK。
4. 没有 `rospy` 并发 stop epoch/锁实现。
5. 没有 ROS1 cleanup/perception/status owner。
6. ROS1 base/integration topology 与全 ROS1 intent ownership 尚未协调。
7. bottle-only grammar 真人准确率回退。

完成纯软件 source contract 也不能解除这些现场阻塞。只有 adapter 实现、跨包契约完成、
离线测试通过后，才可另行请求一次零运动 live ROS 验收授权。真实 navigation cancel 或
机器人联动仍需当次明确授权；软件停止永不替代物理急停或断电。

本审计未启动 ROS master、麦克风、导航、底盘、机械臂或夹爪。
