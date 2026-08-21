# limo_cleanup_voice

`LEGACY_ROS2_OFFLINE_ONLY` applies to every `rclpy`, ament, ROS2 launch and
`ros2` command retained in this package. They exist only for reproducible
offline/mock evidence and are not ROS1/Noetic field entry points.

项目运行时基线现为 ROS1/Noetic。当前包中的 `rclpy`/ament/ROS2 launch 节点仅是
遗留实现，因此不得作为默认部署入口，也不得据此安装 ROS2。现已新增 ROS-independent
`ros1_noetic_adapter.py`、零 publisher 的 `rospy` 薄包装，以及默认不启动节点的
`ros1_overlay_src/limo_cleanup_ros1_voice` Catkin source preview。该 preview 已完成
Noetic/aarch64 目标机离线构建和私有 mock graph 验证，但尚未作为完整现场语音链安装或
连接 production owner；这些证据只证明 offline fail-closed contract，不是现场入口。
模型 intake、预录 WAV、解析器、确认状态机和停止策略测试均为 ROS 无关的离线工具，
仍可继续使用。ROS1 实际审计、节点/topic ownership、mock 隔离与阻塞项见
`docs/VOICE_ROS1_NOETIC_RUNTIME_AUDIT.md` 和
`fixtures/voice_ros1_noetic_runtime_contract.json`。

当前完整状态、证据哈希、复跑命令和下一执行人边界见
`docs/VOICE_V3_HANDOFF_20260821.md`。最终机器报告必须保持
`status=BLOCKED`、`delivery_ready=false`，直到独立 ROS1 stop gate、导航 cancel relay、
ACK owner 和零运动现场拓扑验收全部完成。

ROS1 adapter 当前状态是 `BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY`：强制完整“小莫小莫”
唤醒，普通意图只形成内存 pending/mock plan，STOP 只形成内部高优先级事件计划；所有
离线决策 `actual_publish_count=0`。ACK 要求精确 stop-gate source、process/event 关联、
接收端 monotonic deadline 和 future wall-time tolerance。它没有 publisher、service、
action、Twist 或设备接口，不能作为 live ROS 或现场停止证据。

该语音链只生成可审计的高层意图，绝不发布
`/cmd_vel`、导航目标、机械臂姿态、`power_on` 或夹爪动作。

## 接口

| 方向 | 话题 | 类型 | 用途 |
| --- | --- | --- | --- |
| 输入 | `/voice/text_input` | `std_msgs/String` | 无麦克风开发回退 |
| 中间 | `/voice/transcript` | `std_msgs/String` | ASR 识别文本 |
| 审计 | `/voice/intent` | `std_msgs/String` JSON | 意图、是否转发及原因 |
| 输出 | `/cleanup/natural_language` | `std_msgs/String` | 接入既有语言节点 |
| 导航意图 | `/cleanup/navigation_intent` | `std_msgs/String` JSON | 仅高层导航/取消/安全停止请求，不含速度 |
| 反馈 | `/voice/response_text` | `std_msgs/String` | 中文对话反馈/TTS 输入 |
| 状态 | `/voice/asr_status`、`/voice/status`、`/voice/tts_status` | `std_msgs/String` JSON | 运行诊断 |

V2 唤醒短语固定为“小莫小莫”。清理和导航指令默认需要二次确认。`停下`、
`停止任务` 和 `紧急停止` 具有最高优先级，会立即发送高层任务取消，以及
`cancel_navigation + request_safe_stop=true` 导航意图，但语音节点绝不直接发布速度，
也不能替代物理急停。当前任务状态机没有暂停、继续和返回接口，所以这些语音只
返回“不支持”，不会触发移动。

唤醒词既可与命令同句，也可单独说。单独识别到完整“小莫小莫”后，只开启一次
默认 5 秒的下一句命令窗口；第一条后续转写无论成功、歧义或不支持都会消费该窗口。
超时、取消和 STOP 都会清空窗口。用户标注语料中 Vosk 实际输出的
`丢 垃圾 丢 垃圾` 只按精确监督别名归一化为 `开始清理`，仍需唤醒和确认；
相似子串和模糊匹配不会建立待确认任务。

停止采用独立最高优先级快车道：`voice_priority_stop` 直接监听 `/voice/transcript`，识别
明确停止词后同步广播 `/voice/priority_broadcast`，并发布严格的高层任务取消与
navigation cancel/safe-stop。它不等待、也不依赖 Agent 语义节点。其余文本由
`voice_semantic_agent` 规范化到 `/voice/semantic_candidate`，再进入确定性 schema 校验、
唤醒门、确认门与超时门。语义 Agent 被禁止生成 stop，也不能输出速度、坐标或硬件动作。
对话节点只订阅优先广播来同步清除待确认状态，不重复发布 stop；因此停止发生后，旧任务不能
被后续一句“确认”恢复。

每个停止事件立即首发，并按默认配置最多发布 3 次；0.75 秒内重复 ASR 文本只做去抖，
不创建新事件。事件携带事件 ID、序号、墙钟/单调双时间戳和首发时延；下游 ACK 必须与
当前事件严格关联，默认观察窗为 1.5 秒。ACK 只用于可观测状态，绝不延迟或阻止停止发布。

当前内置的是可离线复现的受限规则 Agent，例如：

- `小莫小莫，你去桶边等着` → 候选 `到垃圾桶旁边去`，仍需确认；
- `小莫小莫，处理一下那个瓶子` → 候选 `捡塑料瓶`，仍需确认；
- `小莫小莫，过来我这边` → 候选 `到这里来`，最终仍为 unsupported；
- `停下/先别干了/别动` → 不进入 Agent，由优先广播通道处理。

后续可替换为本地模型或外部 Agent，但输出仍必须使用同一候选 schema，且不能绕过上述安全门。

待确认指令默认 10 秒超时。每条新输入都会先清除已经过期的待确认状态；超时后
新任务必须重新满足唤醒词门。`取消` 只清除待确认指令或一次性唤醒窗口；当前没有
待确认指令时 fail-closed，不发送停止或导航请求。需要停止正在运行的任务时必须说
明确停止词，例如 `停下` 或 `紧急停止`。

## 遗留 ROS2 无麦克风 mock（非 Noetic 入口）

以下命令仅保留为旧 ROS2 隔离 mock 的历史复现实例。它们不能证明 ROS1/Noetic
兼容，也不得在现场作为启动命令。当前任务不运行这些命令。

```bash
source /home/agilex/limo_cleanup_ws/install/setup.bash
ros2 launch limo_cleanup_voice full_system_with_voice.launch.py
```

另开终端观察审计与反馈：

```bash
ros2 topic echo /voice/intent
ros2 topic echo /voice/response_text
ros2 topic echo /cleanup/status
```

发送一条指令，再确认：

```bash
ros2 topic pub --once /voice/text_input std_msgs/msg/String "{data: '小莫小莫，捡塑料瓶'}"
ros2 topic pub --once /voice/text_input std_msgs/msg/String "{data: '确认'}"
```

停止任务：

```bash
ros2 topic pub --once /voice/text_input std_msgs/msg/String "{data: '紧急停止'}"
```

V2 导航意图：

- `小莫小莫，到垃圾桶旁边去`：确认后发布固定地图点位
  `trash_bin_staging` 的高层请求。当前语音包不连接 Nav2；后续可把目标源升级为视觉
  垃圾桶定位。
- `小莫小莫，到这里来`：V2 正式不支持，不进入确认门，不发布导航 intent，也不映射为
  任何运动。V2 不开展麦克风阵列、DOA 或说话人定位方案。

遗留自动化冒烟测试（只允许隔离 ROS2 mock，且强制本机 DDS）：

```bash
LIMO_ALLOW_LEGACY_ROS2_OFFLINE=1 \
  bash src/limo_cleanup_voice/scripts/smoke_test_voice_text.sh
```

脚本会优先使用 `/opt/ros/foxy/setup.bash`，在开发机上自动回退到 Humble；
机器人工作区不在默认路径时，将工作区作为第一个参数传入。
`full_system_with_voice.launch.py` 显式固定 mock perception、mock executor、
`executor_dry_run=true`，并关闭真实感知、履带控制器、机械臂运动和夹爪控制器，
不依赖 bringup 的默认值。

## 部署前只读检查与可重复报告

构建完成后运行只读 preflight。该命令不启动 ROS 节点、不查询或打开麦克风，也不连接
机器人；它检查文件完整性、mock/dry-run 固定参数、V2 词法、精确 navigation JSON，并把
两个生产 payload 交给严格 bridge parser：

```bash
bash src/limo_cleanup_voice/scripts/preflight_voice_deployment.sh "$PWD" \
  /tmp/voice_preflight.json
```

预期包含 `VOICE_BRIDGE_EXACT_PAYLOAD_READONLY_PASS`。可重复的 V2 行为、确认超时和负向
误触发统计同样不启动 ROS 或硬件：

```bash
bash src/limo_cleanup_voice/scripts/report_voice_v2_statistics.sh \
  100 /tmp/voice_v2_statistics.json
```

离线音频文件评测使用 mono 16-bit PCM WAV 清单，不打开麦克风：

```bash
bash src/limo_cleanup_voice/scripts/evaluate_voice_wav.sh \
  /path/to/manifest.json \
  /path/to/vosk-model-small-cn-0.22 \
  /tmp/voice_wav_report.json
```

清单格式：

```json
{
  "cases": [
    {
      "id": "wake-waypoint-01",
      "audio_path": "audio/wake_waypoint_01.wav",
      "expected_transcript": "小莫小莫到垃圾桶旁边去",
      "expected_intent": "navigate_to_bin"
    },
    {
      "id": "background-01",
      "audio_path": "audio/background_01.wav",
      "expected_transcript": "",
      "expected_intent": "ignored",
      "negative": true
    }
  ]
}
```

评测清单与转换生成的 `decode_manifest.json` 是两个独立 schema，不得混用。每条评测
case 必须显式给出 `expected_intent`，并给出 `expected_transcript`；只有夹具/CI 模式可用
`transcript_fixture` 代替预期转写。缺少 ground truth 时评测器在读取音频前 fail-closed。

`transcript_fixture` 只用于无模型的夹具/CI 回归；正式音频报告应省略该字段并传入真实离线
Vosk 模型。部署回滚步骤见 `docs/VOICE_DEPLOYMENT_ROLLBACK.md`；真人麦克风或真实导航需用
`docs/VOICE_FIELD_ACCEPTANCE_TEMPLATE.md` 独立现场验收。

Media Foundation 转换后可先运行不需要 ASR 模型的 corpus readiness 检查：

转换器要求输出目录是输入目录的直接子目录。例如输入为 `conv`，输出为
`conv/decoded_16k_mono`；清单固定写入 `source_root: ..`。复用输出目录时，若
存在不属于本次精确输入集的生成 WAV，转换会在写入前 fail-closed，且不会删除
陈旧或无关文件。

Windows 上的可复现转换命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  src/limo_cleanup_voice/scripts/decode_voice_m4a_media_foundation.ps1 `
  -InputDirectory C:\path\to\conv `
  -OutputDirectory C:\path\to\conv\decoded_16k_mono
```

```bash
bash src/limo_cleanup_voice/scripts/check_voice_corpus_readiness.sh \
  /path/to/decoded_16k_mono/decode_manifest.json \
  /home/agilex/limo_cleanup_ws/models/vosk-model-small-cn-0.22 \
  /tmp/voice_corpus_readiness.json
```

检查只读取预录 WAV/manifest 和模型目录，不打开麦克风、ROS 或硬件。
它校验源/WAV SHA-256、16 kHz mono PCM16、音频质量、唤醒/停止/普通意图
覆盖和 Vosk 动态语法关键结构（`am/final.mdl`、`graph/HCLr.fst`、
`graph/Gr.fst`、`graph/disambig_tid.int`、词表与配置）。若本机安装了
Vosk，readiness 还会用完整部署语法实际构造 `Model + KaldiRecognizer`；
运行时或动态语法不可用时保持 `delivery_ready=false`。文件名标签只是录制提示，
不是转写；模型缺失时报告必须保持
`decoded_not_transcribed` 和 `delivery_ready=false`。
readiness 报告同时满足 `status=PASS`、`corpus_ready=true`、
`delivery_ready=true` 和 `model.ready=true`，也只解除模型结构/加载门；它不能解除
ROS1 adapter 的 `BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY`。`INCOMPLETE` 或
`decoded_not_transcribed` 只能证明语料已解码，不能证明 ASR、意图或现场链可交付。

## 离线中文 Vosk 模型与 WAV（ROS 无关）

模型 intake、预录 WAV 转写和语义评估不需要 ROS。当前已下载的官方模型只在
任务目录只读加载；不得据此安装 ROS2。下面涉及麦克风或 `ros2 launch` 的旧内容
均为 `LEGACY_ROS2_OFFLINE_ONLY`；offline adapter core 通过也不属于现场验收。

旧 Jetson 路径约定为：

```text
/home/agilex/limo_cleanup_ws/models/vosk-model-small-cn-0.22
```

先运行只读环境检查（不会录音，也不会发布运动命令）：

```bash
bash src/limo_cleanup_voice/scripts/check_voice_runtime.sh
```

以下麦克风/ROS2 命令只作历史记录，当前禁止执行：

```bash
python3 -c "import sounddevice; print(sounddevice.query_devices())"
```

遗留固定词表启动示例：

```bash
ros2 launch limo_cleanup_voice voice_dialogue.launch.py \
  input_mode:=vosk_microphone \
  microphone_device:=0 \
  require_wake_word:=true
```

通过 NoMachine 转发电脑麦克风时，使用 PulseAudio 输入并缩短采集块可降低交互延迟：

```bash
ros2 launch limo_cleanup_voice voice_dialogue.launch.py \
  input_mode:=vosk_microphone \
  microphone_device:=pulse \
  input_sample_rate:=44100 \
  block_size:=4000 \
  require_wake_word:=true
```

当前不得推荐 bottle-only 固定词表。真人 A/B 中 unrestricted/no grammar 为
exact `2/4`、micro CER `0.357143`；“瓶子” restricted grammar 为 exact `1/4`、
micro CER `1.142857`，因此被标记 `BLOCKED_ACCURACY_REGRESSION`。现有瓶子录音实际
说的是“捡矿泉水瓶”，并没有真人“捡瓶子”样本。默认 ASR 证据基线是 unrestricted；
兼容 grammar 必须用同一真人 WAV 证明 exact/CER 和关键短语不回退后才可升级。
遗留离线 wrapper 与 YAML 均固定 `use_restricted_grammar: false`；只有显式布尔
`true` 才可复现实验 grammar，非布尔值直接拒绝。解析器可接受 Vosk 的
`捡 / 矿泉水 / 瓶` 分词，但这不会把受限 grammar 提升为默认配置。
small-cn 的 unrestricted first-complete 候选已在同一四条真人 WAV 上两次独立得到
exact `4/4`、micro CER `0`、semantic safety `4/4`、实际发布 `0`。final runner
将两次报告和 runner 哈希作为独立实验门，同时继续保留 all-endpoints 的冻结基线
exact `2/4`、CER `0.357143`；该候选未经过 Noetic 现场或人群级验证，不能提升现场状态。
意图层仍保留 `瓶子` alias 到既有 canonical 目标，但不能用 alias 单测或 mock PASS
替代真人识别能力。
Vosk 的显式 `[unk]` 结果只写入 ASR 状态审计，不再发送给对话节点。
麦克风词表不包含当前状态机不支持的暂停、继续和返回。先在安静环境逐条验收，再决定
是否扩充词表。
USB 麦克风原生采样率由节点自动读取；若不是 16 kHz，音频会在内存中重采样，
无需修改 ALSA 全局配置。
配置文件中的中文固定语法按 Vosk 词典分词书写，例如 `紧急 停止`；发布到
`/voice/transcript` 后的空格会由确定性解析器忽略，不影响命令匹配。
`voice_dialogue.launch.py` 使用节点默认参数和显式 launch 参数，避免 Foxy
同时合并基础 YAML 与临时覆盖文件时出现参数优先级差异；YAML 保留为独立节点
启动和部署配置模板。

## 遗留 ROS2 可选语音反馈（非 Noetic 入口）

确认扬声器和 `espeak-ng` 可用后：

```bash
ros2 launch limo_cleanup_voice voice_dialogue.launch.py \
  input_mode:=vosk_microphone \
  enable_tts:=true
```

默认关闭 TTS，不会因为音频设备或语音包缺失阻塞任务指令链路。
