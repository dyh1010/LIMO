# LIMO Voice V3 handoff — 2026-08-21

## 一句话结论

语义、确认门、STOP 快车道、真人离线 ASR 与 ROS1 fail-closed 契约已有可复现证据，
但项目仍是 `BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY`、`delivery_ready=false`，不能称为
Noetic 现场可交付。普通意图的实际/生产发布始终为 `0`；软件 STOP 也不能替代现场
物理急停或断电。

最新 create-only 最终报告：

```text
C:\Users\DYH\Desktop\ai scout develop\voice_model_lab_20260814\reports\voice_delivery_evidence_20260821_v11.json
SHA-256 325a2853631505227dbad42ea83171da8b4d09364bd82149320246c59142df49
status=BLOCKED
delivery_ready=false
blocking_issues=["ROS1/Noetic adapter remains offline-only and field BLOCKED"]
```

runner 返回码为 `1` 是上述 BLOCKED 硬门的预期行为，不表示 runner 崩溃。

## 已完成的产品能力

- 固定唤醒词为“小莫小莫”。普通运动/任务请求只有在完整唤醒、单一无歧义语义和
  明确“确认”后才形成高层 mock plan；未唤醒、超时、取消、否定确认均 fail-closed。
- 支持“到垃圾桶旁边去”，canonical 为固定高层 waypoint 候选
  `trash_bin_staging`；没有直接导航、pose 或速度输出。
- 支持识别、处理和捡瓶子。用户口令可说“瓶子”，意图层仍归一化到既有
  bottle/water_bottle canonical，不修改视觉类别和下游接口。
- `停下`、`紧急停止` 等直接肯定停止不需要唤醒或确认，不等待 Agent。STOP 清除
  pending，并生成高优先级内部事件；否定、引用、转述、元语言和仅包含停止子串均拒绝。
- 歧义、多普通意图、相似词、英文非完整词边界均拒绝；普通意图不会越过确认门。
- 语音层只产生高层 intent。代码和契约禁止 Twist、`/cmd_vel`、设备路径、机械臂、
  夹爪、真实 action/service client。

## STOP 契约

STOP 首发不等待 Agent；同一事件最多 3 次 transport attempt，750 ms 内重复输入去抖，
事件序号和墙钟/单调时间戳单调。严格 wire schema 包含
`process_instance_id + event_id`。ACK 必须同时满足：

- source 属于唯一 allowlist `cleanup_ros1_stop_gate`；
- process/event 与当前活动事件相同；
- 状态成功，且在接收端本地 monotonic deadline 内到达；
- ACK 墙钟不超过 5 秒 future tolerance。

错误 source、旧/错误 process、错误 event、缺字段、过期、future wall-time 或失败状态
均不生效。ACK 仅用于状态可观测，不延迟首发。producer 的 process ID 与 parser 使用
同一严格 identifier 规则，生成 payload 可由 strict parser 复读。

ROS-free endpoint ingress 位于
`limo_cleanup_voice/ros1_stop_endpoint_ingress.py`，状态是
`IMPLEMENTED_NOT_CATKIN_INSTALLED_NOT_ROS_OWNER`。它只接受
`vosk_complete_endpoint`，拒绝 partial；同一 stream 保留上下文以阻断拆分的否定、
引用和元语言；普通文本、确认、取消都不进入 dialogue/pending。stream 与上下文容量
有固定上限，耗尽时不驱逐旧上下文而是 fail-closed。

## 真人 ASR 与声学证据

当前推荐的离线候选是 `unrestricted_first_complete_endpoint`，不是 restricted grammar：

| 证据 | exact | micro CER | semantic safety | 实际发布 |
| --- | ---: | ---: | ---: | ---: |
| 冻结 all-endpoints unrestricted 基线 | 2/4 | 0.357143 | 4/4 | 0 |
| 用户要求的 bottle-only “瓶子” grammar | 1/4 | 1.142857 | 4/4 | 0 |
| unrestricted first-complete，两次独立复现 | 4/4 | 0 | 4/4 | 0 |
| 37 条真人语音 full-cn 评估 | 28/37 | 0.081081 | 37/37 | 0 |

现有四条瓶子 WAV 实际说的是“捡矿泉水瓶”，并没有真人“捡瓶子”样本。不得用文件名、
预置期望或 alias 单测伪造转写。bottle-only grammar 因真实退化保持
`BLOCKED_ACCURACY_REGRESSION`，禁止作为默认。first-complete 的 4/4 只是预录真人
WAV 离线候选，不构成 Noetic 现场或人群级能力证明。

真人 endpoint STOP 证据：

- 直接停止识别 `4/4`；
- 80 条真人负样本误触发 `0/80`，四类各 20：近音、否定、引用/转述、环境对话；
- 完整 endpoint 从停止词结束后的 p50/p95/max 为 `375/430/430 ms`；
- partial 识别 `0/4`，且负样本误触发 `1/80`，因此 partial fast path 被硬性禁用；
- 以上均为离线音频/软件证据，不是真实机器人停止端到端时延。

## ROS1/Noetic 当前边界

默认运行时必须是 ROS1/Noetic。所有 `rclpy`、ament、ROS2 Python launch、
`ros__parameters`、colcon/ROS2 smoke 都标为 `LEGACY_ROS2_OFFLINE_ONLY`，只能用于历史
离线回归，不能作为现场入口，也不得据此安装 ROS2。

现有 ROS1 资产：

- ROS-free `ros1_noetic_adapter.py`：只允许 `offline_text_mock`，强制
  `require_wake_word is True`；普通意图只产出内存 mock plan，actual publish 为 0。
- 零 publisher `rospy` wrapper 与 Catkin preview：已完成 Noetic/aarch64 目标机离线
  build 和私有 mock graph 证据，但没有提升为 production owner。
- `voice_ros1_noetic_runtime_contract.json`：固定 node/topic ownership、strict schema、
  mock remap、ACK 与并发 stop-epoch 契约。

普通意图隔离名为：

```text
/cleanup/natural_language  -> /voice_mock/cleanup/natural_language
/cleanup/navigation_intent -> /voice_mock/cleanup/navigation_intent
/cleanup/perception_intent -> /voice_mock/cleanup/perception_intent
```

production 名在 offline profile 必须 0 publisher/0 subscriber。voice 不拥有
`/move_base` action、导航 cancel、底盘、机械臂、夹爪或设备接口。

## 仍未完成，禁止越级宣称

1. 未将 endpoint STOP ingress 安装为独立的现场 `rospy` recognizer owner。
2. 未实现持续 exact-owner topology guard 的完整现场版本。
3. 未实现 `/cleanup_ros1_stop_gate`、幂等 cancel relay 和真实导航 ACK。
4. 未实现/验收唯一 `/cleanup_ros1_navigation_adapter` 到 `/move_base` 的现场 ownership。
5. 未完成 production ordinary owner、status/perception adapter 的跨包集成。
6. 未做完整 production live ROS topology acceptance。
7. 未做真实机器人 STOP 端到端时延或物理停止距离验收。
8. 没有真人“捡瓶子”口令样本，不能对该新短口令单独给出真人准确率结论。

在上述 1–7 完成前，顶层必须保持 BLOCKED；mock、预录 WAV、Catkin build 或私有 graph
PASS 都不能提升 field/delivery 状态。

## 精确复跑

本次交接前的当前源码复核结果：

```text
final evidence + endpoint ingress + ROS1 machine contract
+ adapter + ROS1 audio plan: 180 passed / 0 failed
all voice Python sources: py_compile PASS
voice Python lines longer than 99 characters: 0
git diff --check: PASS
```

该 180 分母是无需 ROS import 的定向安全/交付契约集。完整历史 ROS-free 回归最近一次为
`449 passed / 0 failed / 2 skipped`；本次没有安装缺失的 ROS2 ament lint 依赖，也没有
为跑测试启动 ROS。环境缺少 `ament_flake8/ament_pep257/ament_copyright` 不能写成代码
测试失败，但交付前仍应在匹配的 legacy ROS2 环境单独运行这些历史 lint。

在 `C:\Users\DYH\Desktop\ai scout develop\limo_cleanup_ws` 下，最终 evidence runner
使用 bundled Python：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='C:\Users\DYH\Desktop\ai scout develop\limo_cleanup_ws\src\limo_cleanup_voice'
$python='C:\Users\DYH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

& $python -m limo_cleanup_voice.voice_delivery_evidence `
  --manifest ..\voice_model_lab_20260814\final_voice_delivery_manifest_20260821_v1.json `
  --json-output ..\voice_model_lab_20260814\reports\voice_delivery_evidence_YYYYMMDD_vN.json
```

本次 180 项 ROS-free 定向回归使用 WSL 的系统 Python 与任务内已有 pytest runtime；
不启动 ROS：

```bash
cd '/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws'
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH='/mnt/c/Users/DYH/Desktop/ai scout develop/voice_model_lab_20260814/runtime/pytest_20260820:/mnt/c/Users/DYH/Desktop/ai scout develop/limo_cleanup_ws/src/limo_cleanup_voice'
python3 -m pytest -q \
  src/limo_cleanup_voice/test/test_voice_delivery_evidence.py \
  src/limo_cleanup_voice/test/test_ros1_stop_endpoint_ingress.py \
  src/limo_cleanup_voice/test/test_voice_ros1_noetic_contract.py \
  src/limo_cleanup_voice/test/test_ros1_noetic_adapter.py \
  src/limo_cleanup_voice/test/test_ros1_audio_input.py
```

最终报告路径必须不存在；runner 使用 exclusive-create，禁止覆盖旧证据。BLOCKED 状态
预期返回 `1`。复跑后必须同时检查报告 SHA-256、输入哈希、`actual_publish_count=0`、
`field_delivery_ready=false` 和唯一 blocker，不能只看测试进程退出码。

关键源码身份（2026-08-21）：

```text
voice_delivery_evidence.py  4b3e881af35f67eccab520a4fcafe68a9c9a5b32e347797b27e86c6bbd1a1fbd
ros1_stop_endpoint_ingress.py ba7927be6d75255cc4bb060051d90544f7d184be7f5d98acad6dfc37673f4154
voice_ros1_noetic_runtime_contract.json d979469337afec443d440d98fa0b6083a75f674afe21e2aac5dab5fa12194130
final manifest ebee5165981aa7eb387760b97d34c0c08191e29f78c51f93432f1113ade14cc2
```

`voice_model_lab_20260814`、`voice_v3_lab_*` 和 `conv` 位于 Git 仓库外；它们是外部
evidence/corpus，不会随本仓库 commit 自动上传，迁移时必须按 final manifest 保留
精确目录和哈希。

## 下一执行人的安全规则

- 普通意图继续只进入 mock/隔离命名空间，确认前后都不得连接实际执行器。
- 未经当次现场授权，不连接 production ROS graph、导航、底盘、机械臂或夹爪。
- 任何可能产生非零运动的测试前，先验证物理急停/断电、清场、安全观察员和唯一 owner。
- STOP 软件证据不能替代物理急停，也不能从“发出 cancel”推导“机器人已停止”。
- 保留用户和其他任务的未提交改动；禁止 reset/checkout，Git 只按明确 voice 文件清单暂存。
