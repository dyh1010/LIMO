# limo_cleanup_voice

ROS 2 Foxy 兼容的离线中文语音入口。该包只生成可审计的高层意图，绝不发布
`/cmd_vel`、导航目标、机械臂姿态、`power_on` 或夹爪动作。

## 接口

| 方向 | 话题 | 类型 | 用途 |
| --- | --- | --- | --- |
| 输入 | `/voice/text_input` | `std_msgs/String` | 无麦克风开发回退 |
| 中间 | `/voice/transcript` | `std_msgs/String` | ASR 识别文本 |
| 审计 | `/voice/intent` | `std_msgs/String` JSON | 意图、是否转发及原因 |
| 输出 | `/cleanup/natural_language` | `std_msgs/String` | 接入既有语言节点 |
| 反馈 | `/voice/response_text` | `std_msgs/String` | 中文对话反馈/TTS 输入 |
| 状态 | `/voice/asr_status`、`/voice/status`、`/voice/tts_status` | `std_msgs/String` JSON | 运行诊断 |

清理指令默认需要二次确认。`停止任务` 和 `紧急停止` 会立即向任务管理器发送
高层停止请求，但不能替代物理急停。当前任务状态机没有暂停、继续和返回接口，
所以这些语音只返回“不支持”，不会触发移动。

## 无麦克风验收

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
ros2 topic pub --once /voice/text_input std_msgs/msg/String "{data: '小莫，捡塑料瓶'}"
ros2 topic pub --once /voice/text_input std_msgs/msg/String "{data: '确认'}"
```

停止任务：

```bash
ros2 topic pub --once /voice/text_input std_msgs/msg/String "{data: '紧急停止'}"
```

完整自动化冒烟测试（只使用模拟执行器，且强制本机 DDS）：

```bash
bash src/limo_cleanup_voice/scripts/smoke_test_voice_text.sh
```

脚本会优先使用 `/opt/ros/foxy/setup.bash`，在开发机上自动回退到 Humble；
机器人工作区不在默认路径时，将工作区作为第一个参数传入。

## 离线中文 Vosk

在 Jetson ARM64/Python 3.8 环境安装与系统版本匹配的 Vosk、PortAudio 和
`sounddevice`，并把中文模型放到：

```text
/home/agilex/limo_cleanup_ws/models/vosk-model-small-cn-0.22
```

先运行只读环境检查（不会录音，也不会发布运动命令）：

```bash
bash src/limo_cleanup_voice/scripts/check_voice_runtime.sh
```

先列出麦克风设备并记录设备编号：

```bash
python3 -c "import sounddevice; print(sounddevice.query_devices())"
```

再启动固定词表离线识别：

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

固定词表减少中文误识别。需要唤醒词的指令必须作为完整短语写入词表，例如
`机器人 捡 塑料瓶` 和 `机器人 碰 一下 塑料瓶`，不能把唤醒词与命令拆成两个候选项。
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

## 可选离线语音反馈

确认扬声器和 `espeak-ng` 可用后：

```bash
ros2 launch limo_cleanup_voice voice_dialogue.launch.py \
  input_mode:=vosk_microphone \
  enable_tts:=true
```

默认关闭 TTS，不会因为音频设备或语音包缺失阻塞任务指令链路。
