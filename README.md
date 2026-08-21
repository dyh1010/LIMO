# LIMO AI Scout

LIMO Pro 移动操作机器人研究工作区，覆盖 ROS1/Noetic 导航、DaBai
RGB-D 感知、中文语音对话、myCobot 280 M5 机械臂及夹爪。

当前状态：**开发中，禁止按现场交付版本使用**。离线测试、pure-fake、私有
ROS graph、只读硬件检查或 prerecorded WAV 通过，都不代表已经允许机器人运动。
软件 STOP 也不能替代现场物理急停或断电。

## 首先阅读

- [项目总交接](docs/PROJECT_HANDOFF_20260821.md)：当前能力、测试证据、阻塞项和安全执行顺序。
- [V1–V3 路线图](docs/product_roadmap_v1_v3.md)：各阶段目标和完成边界。
- [语音 V3 交接](src/limo_cleanup_voice/docs/VOICE_V3_HANDOFF_20260821.md)：真人语音、STOP 和误触发证据。
- [感知运行索引](docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md)：DaBai、模型和现场证据入口。
- [机械臂/夹爪交接](src/limo_cleanup_executor/ARM_GRIPPER_V3_LOCAL_HANDOFF_20260817.md)：fake-first 实现和真实动作阻塞项。
- [ROS1 底盘桥接说明](docs/ros1_noetic_base_bridge_implementation.md)：底盘唯一 owner、watchdog 和零输出阶段。

默认运行面是 **ROS1/Noetic**。仓库中的 ROS2/Foxy 包、`.launch.py` 和相关脚本主要用于
历史兼容、离线回归或受限桥接，除非相应交接材料明确放行，否则不得作为现场启动入口。

## 仓库顶层目录

| 路径 | 作用 | 使用边界 |
| --- | --- | --- |
| `src/` | 原始 ROS 包、纯逻辑核心、接口、配置和单元测试 | 同时包含 ROS2 legacy 资产和可复用纯逻辑，不等于 ROS1 现场入口 |
| `ros1_overlay_src/` | ROS1/Noetic Catkin overlay：底盘、导航、感知、语音、操作预览 | 默认 ROS1 代码面；仍需通过每个子系统的现场 gate |
| `scripts/` | 审计、preflight、smoke test、回归、零输出验证及回滚工具 | 先读脚本说明；名称含 `real`、`hardware` 也不代表已授权执行 |
| `audit_tools/` | 不依赖 live ROS 的证据生成、来源绑定、哈希和 fail-closed 验证工具 | 主要用于离线审计；PASS 不能提升为 field PASS |
| `docs/` | 架构、安全契约、runbook、验收表和紧凑证据 | `docs/evidence/` 是可审查的小型证据，不含大型现场采集 |
| `offline_tests/` | 静态图像、标签和 AprilTag 等可复现实验 fixture | 只能验证离线算法/契约 |
| `evidence/` | 本机大型或现场运行证据 | 被 Git 忽略，可能含 bag、主机信息或临时采集，不随源码提交 |
| `build/`, `install/`, `log/` | Colcon/Catkin 构建及运行生成物 | 被 Git 忽略，不是源码依据 |
| `output/`, `tmp/` | 本地报告和临时输出 | 被 Git 忽略；runner 应尽量 exclusive-create |
| `README.md` | 本文件，仓库导航和文件职责索引 | 不代替各子系统 runbook |
| `.gitignore` | 排除模型、训练输出、缓存、构建目录、大型证据和临时文件 | 不会删除本地文件，只阻止误提交 |
| `BASELINE_SNAPSHOT_2026-08-11.md` | 早期基线快照 | 历史记录；最新事实以总交接和当前源码为准 |

## `src/` 中的功能包

| 包 | 主要功能 | 关键入口 |
| --- | --- | --- |
| `limo_cleanup_base` | 底盘运动策略、导航 intent 消费、桥接协议、拓扑与零输出验证 | `motion_policy.py`、`navigation_intent_policy.py`、`bridge_protocol.py` |
| `limo_cleanup_bringup` | 系统组合 launch、硬件 readiness 和安全默认配置 | `launch/`、`config/`、`hardware_readiness_check.py` |
| `limo_cleanup_core` | 高层清理任务编排和任务状态 | `task_manager.py` |
| `limo_cleanup_dabai_sensor` | 固定序列号 DaBai camera-only 启动契约 | `dabai_cc1wc520183_sensor_only.launch.py`；只允许相机面，不含运动接口 |
| `limo_cleanup_executor` | 机械臂/夹爪 gateway core、backend、journal、release manifest 和 safety latch | `arm_gateway_core.py`、`gripper_gateway_core.py`、`*_safety_latch.py` |
| `limo_cleanup_interfaces` | 高层 Action、Message、Service 定义 | `action/`、`msg/`、`srv/`；接口定义本身不授权真实动作 |
| `limo_cleanup_language` | 早期语言节点、模型枚举和 touch intent | legacy/实验包，不是 V2/V3 中文语音主入口 |
| `limo_cleanup_perception` | RGB-D、目标选择、frame/target schema、证据绑定、readiness 和 ROS1 来源准入 | `perception_core.py`、`target_contract.py`、`perception_readiness.py` |
| `limo_cleanup_voice` | 唤醒、ASR、语义解析、确认状态机、STOP 快车道、TTS 契约和离线评测 | `command_parser.py`、`semantic_agent.py`、`voice_contract.py` |

### 语音关键文件

| 文件 | 作用 |
| --- | --- |
| `command_parser.py` | 把文本解析为高层 intent；否定、引用、转述和歧义等 fail-closed |
| `semantic_agent.py` | 语义候选和 canonical 目标归一化，例如将“瓶子”映射到既有 bottle 目标 |
| `voice_dialogue_node.py` | 普通任务的唤醒、确认、超时、取消和 pending 状态管理 |
| `voice_priority_stop_node.py` | 独立 STOP 快车道；不等待 Agent、不要求唤醒或确认 |
| `voice_contract.py` | STOP request/ACK、序号、时间戳、重发和去抖的软件契约 |
| `ros1_noetic_adapter.py` | ROS1 adapter 的纯逻辑 fail-closed core；普通 intent 默认 mock |
| `ros1_noetic_adapter_node.py` | ROS1 节点包装层；未通过现场 owner 验收前不得连接真实控制链 |
| `ros1_audio_input.py` | ROS1 音频输入适配与音频帧约束 |
| `voice_asr_node.py` | Vosk ASR 节点实现；模型和音频质量决定实际识别能力 |
| `voice_grammar.py` | 离线 ASR grammar 候选，包括“捡 / 矿泉水 / 瓶”试验 |
| `voice_model_intake.py` | 本地 Vosk 模型结构、哈希和加载 readiness 检查 |
| `voice_wav_transcription_run.py` | 对确定 WAV corpus 做真实离线转写和耗时统计 |
| `voice_delivery_evidence.py` | 哈希绑定真人 A/B、模型、语料和安全子报告 |
| `voice_regression_aggregate.py` | 聚合离线语义、STOP、fixture 和 source-contract 回归 |
| `voice_tts_node.py`, `tts_prompt_contract.py` | TTS 输出及提示语契约；不代表设备一定存在扬声器 |
| `config/voice_dialogue.yaml` | 唤醒词、确认超时、STOP 重发等配置 |
| `fixtures/` | 离线验收输入和 ROS1 machine contract |
| `test/` | 语义、STOP、模型 intake、真人 WAV、TTS 和 ROS1 adapter 回归 |
| `scripts/` | 模型 preflight、转写、统计、M4A 解码和一键离线回归 |

上述文件位于 `src/limo_cleanup_voice/limo_cleanup_voice/`，配置、fixture、测试和脚本位于包内同名目录。
语音只允许发布高层 intent，绝不能直接发布 `Twist`、机械臂命令、夹爪命令或设备路径。
普通任务必须经过“小莫小莫”唤醒和明确确认；“停下/紧急停止”走独立 STOP 契约。

### 底盘与导航关键文件

| 文件/目录 | 作用 |
| --- | --- |
| `motion_policy.py` | 速度、模式和安全状态的纯策略判断 |
| `tracked_base_controller.py` | ROS2 历史底盘控制包装；不是 Noetic 默认现场 owner |
| `navigation_intent_policy.py` | 高层导航 intent 校验和 waypoint 约束 |
| `navigation_intent_consumer.py` | 消费已确认的高层导航请求 |
| `navigation_topology_verifier.py` | 检查导航、watchdog、driver 的唯一所有权拓扑 |
| `bridge_protocol.py` | ROS1/ROS2 受限桥接 payload、lease、nonce 和 generation 契约 |
| `zero_stage_handoff_verifier.py` | 验证桥接零输出阶段交接，不发非零运动 |
| `ros1_overlay_src/limo_cleanup_ros1_base/` | ROS1 watchdog、导航 adapter、map binding、runtime snapshot 和 launch |
| `ros1_overlay_src/limo_v1_navigation/` | AMCL/GMapping/move_base、导航 gate、AprilTag docking 和 V1 runbook |
| `v1_navigation_waypoints.example.yaml` | waypoint 格式示例；不能当成已测量现场点位 |

前七个实现/配置文件位于 `src/limo_cleanup_base/`。预期现场所有权是
`move_base -> watchdog/mux -> 私有 driver cmd_vel -> 唯一 limo_base_node`。
公开 `/cmd_vel` 绕过 watchdog 或 ROS1/ROS2 同时占用 UART 都必须阻断。

### 感知关键文件

| 文件/目录 | 作用 |
| --- | --- |
| `perception_core.py` | 检测结果筛选、置信度和基础目标逻辑 |
| `dual_model_detector.py` | 双模型检测组合逻辑 |
| `image_conversion.py` | ROS 图像与数组/深度表示转换 |
| `target_contract.py` | 目标类别、坐标、置信度、frame 和 observation ID 严格 schema |
| `rgbd_contract.py` | RGB/Depth 时间同步、尺寸、frame 和有效性约束 |
| `typed_raw_binding.py` | 原始 RGB-D 与 typed observation 的身份绑定 |
| `evidence_binding.py` | 模型、源码、相机和 evidence 的哈希关联 |
| `diagnostic_evidence_lineage.py` | 诊断证据来源、代际和完整性检查 |
| `perception_frame_collector.py` | 离线/只读感知帧采集和序列管理 |
| `perception_evaluator.py` | 计算场景、目标和质量指标 |
| `perception_readiness.py` | 汇总相机、模型、来源、四场景证据和安装准入 |
| `ros1_noetic_field_readiness.py` | ROS1/Noetic 现场证据 fail-closed 验证 |
| `ros1_source_core_admission.py`, `stdlib_attestation.py` | ROS1 来源/安装身份和标准库可信根检查 |
| `fixtures/` | RGB-D topic、readiness bundle、field intake 和负例 schema |
| `ros1_overlay_src/limo_cleanup_ros1_perception/` | Catkin 包、消息、只读 adapter、rosbag1 indexer 和模型绑定 |
| `src/limo_cleanup_dabai_sensor/` | 固定相机序列号的 camera-only 历史 launch 契约 |

感知实现位于 `src/limo_cleanup_perception/limo_cleanup_perception/`。缺少同步深度、模型哈希、
相机身份或现场场景证据时，不得为机械臂或底盘放行。

### 机械臂与夹爪关键文件

| 文件/目录 | 作用 |
| --- | --- |
| `arm_gateway_core.py`, `gripper_gateway_core.py` | 单 owner、epoch、STOP 和状态机纯核心 |
| `arm_gateway_node.py`, `gripper_gateway_node.py` | ROS 包装；默认配置只允许 dry-run/fake backend |
| `arm_backends.py`, `gripper_backends.py` | fake/候选硬件 backend 边界；真实 backend 未放行 |
| `arm_motion_journal.py` | 动作请求、状态和恢复审计 journal |
| `arm_journal_supervisor_contract.py` | journal 监督和物理隔离状态契约 |
| `arm_motion_release_manifest.py` | 校验机械臂动作 release manifest |
| `final_gripper_release_manifest.py` | 校验最终夹爪硬件、参数和证据绑定 |
| `arm_safety_latch.py`, `gripper_safety_latch.py` | 持久安全锁存，阻止未授权恢复 |
| `arm_gripper_field_acceptance.py` | 汇总 arm/gripper 现场准入矩阵，不执行动作 |
| `config/` | dry-run 配置、候选 release manifest 和现场矩阵 |
| `launch/` | ROS2/Foxy dry-run launch，属于 legacy/offline 面 |
| `ros1_overlay_src/limo_cleanup_ros1_manipulation/` | ROS1 固定瓶子抓取预览，实际发布保持 0 |
| `limo_cleanup_interfaces/action/` | 机械臂/夹爪高层 Action schema |
| `limo_cleanup_interfaces/srv/` | STOP 和 fault acknowledgement Service schema |

核心实现位于 `src/limo_cleanup_executor/limo_cleanup_executor/`。

## ROS1 overlay 目录

| Catkin 包 | 作用 |
| --- | --- |
| `limo_cleanup_ros1_base` | 私有 `cmd_vel` owner、fail-closed watchdog、导航 adapter 和 map binding |
| `limo_v1_navigation` | SLAM/localization/move_base、导航 gateway、AprilTag docking 和 zero-motion preflight |
| `limo_cleanup_ros1_perception` | DaBai/rosbag1 只读感知、typed message、model/source binding 和 readiness |
| `limo_cleanup_ros1_voice` | ROS1 voice adapter 的 offline/mock Catkin 预览；生产 STOP gate 仍未现场验收 |
| `limo_cleanup_ros1_manipulation` | 固定瓶子抓取 mock/preview；不得驱动实体机械臂或夹爪 |

每个 overlay 通常包含：`CMakeLists.txt`/`package.xml`/`setup.py`（安装元数据）、
`config/`（安全配置）、`launch/`（ROS1 launch）、`scripts/`（节点 wrapper/CLI）、
`src/<package>/`（纯逻辑）、`msg/`（typed observation）、`fixtures/`（离线输入）和
`test/`（不连接硬件的回归）。

## `scripts/` 工具说明

| 文件 | 作用 |
| --- | --- |
| `audit_ros1_catkin_overlay.py` | 静态审计 ROS1 overlay 包结构和来源 |
| `audit_foxy_runtime.sh` | 审计历史 Foxy 环境；不是 Noetic 现场启动命令 |
| `robot_tracked_readonly_audit.sh` | 只读检查履带底盘运行信息 |
| `ros1_base_bridge_preflight.sh` | 桥接前 topology/owner/零输出检查 |
| `run_ros1_base_bridge_zero_stage.sh` | 启动零输出桥接阶段，不允许非零运动 |
| `verify_ros1_bridge_ros2_zero_output.py` | 验证桥接端持续为零输出 |
| `verify_ros2_zero_stage_handoff.py` | 检查零阶段 handoff payload 和来源 |
| `verify_tracked_zero_output.py` | 检查底盘命令保持零值 |
| `tracked_base_stage2_preflight.sh` | Stage 2 底盘前置检查；不自动授权运动 |
| `verify_tracked_stage2_topology.py` | 检查 driver、watchdog、publisher 唯一性 |
| `run_v1_frozen_offline_regression.py` | 运行 V1 冻结离线回归并生成机器报告 |
| `run_v1_apriltag_docking_offline.py` | AprilTag docking 纯离线 fixture 回放 |
| `test_ros1_v1_navigation_offline.py` | ROS1 V1 导航 source-contract 汇总测试 |
| `generate_perception_source_manifest.py` | 生成感知源码身份 manifest |
| `perception_release_policy.py` | 感知 release gate 纯策略 |
| `perception_release_preflight.py` | 感知发布前 fail-closed 检查 |
| `run_perception_v2_frozen_regression.py` | 感知冻结/后续代际 ROS-free 回归和证据聚合 |
| `rollback_perception_release.sh` | 感知 release 回滚辅助；先核对精确目标 |
| `start_dabai_camera.sh` | 历史相机启动脚本；必须按 ROS1 runbook 使用 |
| `smoke_test_perception.sh` | 感知 smoke test |
| `smoke_test_real_perception_startup.sh` | 真实相机检查；需要现场只读授权和设备确认 |
| `run_uploaded_arm_foxy_dry_run.sh` | 运行上传的 Foxy arm dry-run 包 |
| `verify_arm_gateway_foxy_dry_run.sh` | 验证 arm gateway 的 fake-only 行为 |
| `smoke_test_gripper_dry_run.sh` | 夹爪 dry-run smoke test |
| `run_hardware_readonly_acceptance.sh` | 只读硬件验收编排，不授权动作 |
| `smoke_test_mock_system.sh` | 全系统 mock smoke test |
| `smoke_test_touch_only.sh`, `touch_only_smoke_probe.py` | touch-only 契约测试，不执行导航 |
| `smoke_test_tracked_zero_guard.sh` | 履带底盘 zero guard 测试 |
| `start_wsl_offline_perception.ps1` | 在 WSL 中启动离线感知工作流 |
| `run_offline_perception_worker.sh`, `run_offline_perception_background.sh` | 离线图像推理 worker 和后台封装 |
| `calibration/collect_jyu2c_intrinsics_gui.py` | JYU2C 标定采集 GUI；访问相机时需单独确认 |
| `training/` | 训练脚本、数据配置和本地权重；权重与 runs 默认不提交 Git |

## `audit_tools/` 说明

该目录保存纯软件证据工具，而不是机器人运行节点：

- `formal_admission_evidence_authority*.py`：逐代强化来源、哈希、runner 和 evidence authority；
- `ros1_camera_*`：camera-only 安装、preflight、operator docs 和 atomic launcher 审计；
- `run_pytest_style_tests*.py`：无 pytest 环境下运行有限 pytest-style fixture；
- `run_unittest_file_tests*.py`：隔离执行单个 stdlib `unittest` 并输出机器报告；
- `workspace_pyc_identity_*.py`：防止陈旧 `.pyc` 或安装产物伪装通过；
- `arm_gripper_local_*`：聚合 arm/gripper 本地安全证据；
- `v3_readonly_*`：只读 SFTP/vendor 静态检查，凭据仅来自环境变量；
- `test_*.py`：上述工具的正负向回归。

## `docs/` 文档索引

| 文档 | 主要内容 |
| --- | --- |
| `PROJECT_HANDOFF_20260821.md` | 全项目真实状态、验证结果、blocker 和后续顺序 |
| `product_roadmap_v1_v3.md` | V1 导航、V2 语音/感知、V3 操作路线图 |
| `tracked_base_control.md` | 底盘控制面和安全约束 |
| `tracked_base_acceptance.md` | 底盘验收标准 |
| `tracked_base_stage2_field_signoff.md` | Stage 2 现场签核项 |
| `touch_only_navigation_contract.md` | 触摸入口只能形成高层导航请求的契约 |
| `ros1_noetic_base_bridge_implementation.md` | ROS1 base bridge 实现和 owner 关系 |
| `ros1_ros2_base_bridge_contract.md` | 跨 ROS bridge schema 与 fail-closed 条件 |
| `coordinate_frames.md` | 地图、底盘、相机、机械臂和 TCP 坐标系 |
| `PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md` | 感知操作文档入口 |
| `PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md` | ROS1 感知现场 runbook |
| `PERCEPTION_V2_READONLY_CAMERA_AUTHORIZATION.md` | 相机只读授权边界 |
| `REAL_CAMERA_READONLY_ACCEPTANCE_TEMPLATE.md` | 真实相机只读验收模板 |
| `real_perception.md` | 真实感知架构、输入输出和限制 |
| `arm_gripper_ros1_noetic_dry_run_checklist.md` | ROS1 arm/gripper dry-run 检查单 |
| `arm_gripper_field_acceptance_matrix.md` | arm/gripper 现场准入矩阵 |
| `arm_motion_release_manifest.md` | 机械臂动作 release manifest 规范 |
| `final_gripper_release_manifest.md` | 最终夹爪硬件和配置绑定规范 |
| `arm_persistent_safety_latch.md` | 机械臂持久安全锁存规则 |
| `gripper_persistent_safety_latch.md` | 夹爪持久安全锁存规则 |
| `v3_pick_place_acceptance.md` | V3 抓取放置完整验收门槛 |
| `EYE_IN_HAND_ROS1_GRASP_INTEGRATION_GATES_20260820.md` | 眼在手上抓取集成 gate |
| `AG_EYE_IN_HAND_SINGLE_BOTTLE_RUN_CARD_20260820.md` | 单瓶实验 run card |
| `trash_bin_staging_field_acceptance.md` | 垃圾桶 staging 点位现场冻结要求 |
| `hardware_readiness.md` | 硬件 readiness 通用检查 |
| `limo_pro_manual_reference.md` | LIMO Pro 手册信息与实机差异 |
| `docs/evidence/` | 小型、可审查的事故、标定和 dry-run 证据摘要 |

## 测试、fixture 和 evidence 命名规则

- `test_*.py`：单元、source-contract 或负向测试；默认不得连接 live ROS 或硬件。
- `fixtures/*.json`：确定性输入、schema 模板或失败样本，不是现场实测结果。
- `*.schema.json`：机器可读输入约束，validator 必须 fail-closed。
- `*_contract.json`：接口、topic、owner 或准入契约。
- `*_manifest.json`：文件身份、模型、来源或 release 绑定。
- `*_evidence*.json`：某次离线/只读观察，必须检查时间、哈希和 provenance。
- `docs/evidence/`：适合 Git 的紧凑证据；根目录 `evidence/` 是大型本地材料。
- `*dry_run*`、`*mock*`、`*preview*`：只允许 fake/预览路径，实际发布应为 0。

## 安全执行顺序

1. 阅读总交接和目标子系统 runbook。
2. 先运行 AST、unit、source-contract、fixture 等 ROS-free 测试。
3. 再做 isolated/private graph 或 pure-fake 测试，确认普通语音 intent 实际发布为 0。
4. 若需设备，只先做断电/物理隔离和只读检查。
5. 相机、麦克风、扬声器、SSH 或 ROS1 adapter 连接必须明确设备和 owner。
6. 任何底盘、机械臂或夹爪非零真实动作，都需要当次单独授权、现场观察员、急停/断电方案和 abort 条件。

目前仓库保存的是可继续开发和验收的源码 checkpoint，不是可直接执行自主清理任务的发行包。
