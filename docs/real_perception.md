# V2 双类别只读真实感知

## 当前结论（2026-08-14）

现场默认运行时已经确认是 ROS1 Noetic。2026-08-14 用户曾用历史命令
`roslaunch astra_camera dabai_u3.launch` 启动 `/camera/camera`，并在
`rqt_image_view` 中查看 `/camera/color/image_raw`；该 package-resolution
命令现已禁止复用。权威现场流程只见
PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md。

本文中的 ros2 run、ROS2 typed collector、rosbag2 DB3/CDR 和 Foxy launch
只保留为离线实现与迁移资产，不能作为机器人现场入口或 ROS1 验收 PASS。
2026-08-14 的共享图诊断 bag 已经采集，但 /tf 混有非相机发布者，且窗口内
/tf_static 为零消息；该 bag 明确排除于四场景分母，delivery_ready=false。

V2 视觉源码已经具备瓶子与垃圾桶的二维检测、对齐深度投影和类型化只读输出，但仍处于
不可交付状态。现有 148 图结果只是冻结同域二维回归；四场景真实 RGB-D、独立垃圾桶指标、
TF 和三维误差尚未验收。旧文档中“完整 TF/真实 detector/gate 已通过”的结论已经过期，
不得继续作为发布依据。

视觉结果绝不直接驱动底盘、导航、机械臂或夹爪。V2 首版垃圾桶导航仍使用冻结的
`trash_bin_staging` waypoint；视觉桶目标只用于确认和后续精对准研究。

## 只读输出契约

`dual_model_detector` 发布：

- `/cleanup/perception/frames`，`limo_cleanup_interfaces/msg/PerceptionFrame`：每个处理帧的
  时间戳、相机 frame、任务 ID、sequence、有效性、错误码、四流同步跨度、处理延迟，以及
  瓶子和垃圾桶目标列表。
- 每个 `PerceptionTarget` 含 observation ID、类别、置信度、有效性、是否 actionable、状态、
  错误码、三维位置/尺寸、二维框、深度、ROI 有效深度像素与比率、模型来源和位置语义。
- `/cleanup/detection/raw`，旧 `ObjectDetection`：只保留具有有效深度的桶外 actionable
  `plastic_bottle`，兼容现有 gate/executor；垃圾桶不会进入该链。
- `/cleanup/perception_status`：诊断状态，不是导航或执行命令。

类型化 active bottle 与 legacy bottle 使用同一 observation ID，便于消费者关联。节点启动时
强制模型分别为单类 `plastic_bottle` 和单类 `trash_bin`；装错或多类权重会失败退出。
`frame_id_override` 必须为空，防止只改 frame 字符串而未做坐标变换。

供任务编排做无硬件联调的 fixture 安装在
`share/limo_cleanup_perception/fixtures/orchestration_typed_frames.json`。它覆盖有效瓶、有效桶、
无效 frame、无效深度 target、过期 frame、重复 observation ID 和重复 sequence。配套纯函数
`select_typed_target()` 只做类别、有效性、actionable、时间新鲜度和重复过滤，不创建 ROS
publisher，也不授权导航或执行器动作。

## RGB-D 与三维语义

输入为四路已对齐数据：

- `/camera/color/image_raw`
- `/camera/depth/image_raw`
- `/camera/color/camera_info`
- `/camera/depth/camera_info`

运行期使用缓存中最接近 RGB 时间戳的四元组，并检查时间戳非零、最大时间跨度、frame 和
像素网格一致。它是软件近邻匹配，不是硬件同步证明。完全相同的坏 bundle 只报告一次；
同一 RGB 获得新的深度或 CameraInfo 后可以重试。

瓶子和垃圾桶使用同一个纯函数投影质量契约。位置是
`camera_color_optical_frame` 中“检测框裁剪后中央 ROI 有效深度中值对应的三维观测点”，
不是 `base_link` 点、地图点、抓取姿态或导航目标。无有效深度时发布
`valid=false + error_code`，不会伪造零坐标有效目标。

桶内瓶过滤目前仍以垃圾桶二维框上部 62%、瓶中心和重叠率为主要判据。它尚未利用瓶/桶
深度前后关系，因此必须在桶前瓶、桶边瓶、透明瓶和漏桶场景继续实测。

## 离线回归与机器报告

运行 evaluator：

```text
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: ros2 run limo_cleanup_perception perception_evaluator matrix
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: --matrix /path/to/matrix.json
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: --report /path/to/frozen_matrix_report.json
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: --verify-recorded-files
```

当前冻结矩阵严格对账为：

- 总数 148 = 78 个混淆矩阵样本 + 70 个排除样本；
- 正集 54：TP=49、FN=5，图像级 recall=90.7407%；
- 背景 24：FP=0、TN=24；
- 78 个已评分样本上的图像级 F1=95.1456%，accuracy=93.5897%；
- mix 70：3 张人工代表图、67 张非穷尽标注 unknown、0 skipped，全部排除于
  TP/FP/FN/TN 分母之外；
- `IMG_9048`、`IMG_8976`、`IMG_9030`、`IMG_9017` 四张代表图只作结构回归；
- 报告始终 `delivery_ready=false`。

正式报告位于 `evidence/perception_v2_offline_20260813/frozen_matrix_report.json`，绑定输入矩阵、
148 张图、两份模型、历史推理源码和当前 evaluator/source 哈希。当前源码与历史生成矩阵的
源码并非完全一致，因此该命令评估的是历史冻结预测，没有重新运行当前 YOLO 源码。

这组结果不是独立盲测、实例级 mAP、垃圾桶独立准确率、三维定位精度或真机泛化证据。

## 四场景采集与验收

现场 ROS1 不启动 ROS2 collector 或 ros1_bridge。正式原始证据先由 ROS1 rosbag v2 记录，
停止并哈希后，再由 ROS1 indexer 和离线规范化工具生成 typed artifact。以下 collector
命令只保留为离线迁移回归：

```text
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: ros2 run limo_cleanup_perception perception_frame_collector
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: --scene background
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: --task-id FIELD_ID-background-readonly
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: --output /evidence/background.frames.jsonl
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: --manifest /evidence/background.manifest.json
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: --max-frames 120
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: --duration-sec 60
```

collector 不创建 ROS publisher；按唯一 sequence 数或最长时长退出。帧文件和 manifest 均以
独占新文件方式创建，已有路径会拒绝覆盖。逐帧记录订阅接收时间和完整 `PerceptionFrame`，
manifest 记录帧数、重复 sequence、文件大小与 SHA-256。

四个场景必须独立采集：

1. `background`：无瓶、无垃圾桶；
2. `bin_only`：只有垃圾桶；
3. `bottle_in_bin`：瓶子位于桶内，不得 actionable；
4. `bottle_outside`：桶外瓶必须保持 actionable，不得被错误抑制。

每个场景至少 30 个唯一、时间递增的处理帧。正式 evaluator 门槛包括两类 TP/FP/FN/TN、
预期类 recall、缺席类误检率、有效 3D 比率、桶内泄漏、桶外错误抑制、RGB-D 拒绝率、
同步 p95、节点处理 p95 和消费者接收端到端 p95。CLI 不允许把最小帧数降至 30 以下。

每场景 ROS1 bag 必须严格只录冻结 ROS1 manifest 中的六话题：四路 RGB-D、`/tf`、
`/tf_static`。不得把 `/cleanup/perception/frames`、状态或任何额外话题加入 raw bag。
索引器必须解析 ROS1 connection header、MD5、callerid、latching、Header、CameraInfo
内参和每条 TF edge；不能用 rosbag info、计数、FPS 或 DDS QoS 冒充 payload 验收。

缺场景时生成机器可读缺口报告：

```text
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: ros2 run limo_cleanup_perception perception_evaluator gaps
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: --report /path/to/four_scene_rgbd_gap_report.json
```

当前报告位于 `evidence/perception_v2_offline_20260813/four_scene_rgbd_gap_report.json`，结果为
FAIL，四场景全部缺失，`delivery_ready=false`。

## 真实相机启动边界（ROS1 Noetic）

用户当时验证过的历史相机入口如下；它没有把校验字节原子绑定到执行字节，
因此现在 **FORBIDDEN / DO NOT RUN**：

```bash
# HISTORICAL ONLY -- DO NOT RUN
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: roslaunch astra_camera dabai_u3.launch
```

实际 launch SHA-256 为
`75f9ada995ac961d0b4dddb7d86d591f57dc5392165663f4a905709a24231b2e`，只含一个
`astra_camera_node`。当前参数 `depth_align=false`、
`color_depth_synchronization=false`，所以只可作 raw RGB-D 诊断，不能冒充已对齐 3D。
正式细节和共享图隔离规则见 `PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md`。
未来 camera-only 启动只能使用其中的
`audit_tools/ros1_camera_only_atomic_launcher.py` sealed-memfd 路径；旧
`scripts/start_dabai_camera.sh` 永久非零退出，不能作为替代入口。

默认模型部署路径：

```text
/home/agilex/limo_cleanup_ws/models/nongfu_yolov8n_best.pt
/home/agilex/limo_cleanup_ws/models/trash_bin_yolov8n_best.pt
```

本视觉任务不得停止或操作用户并行运行的非相机终端、底盘、导航、机械臂、夹爪或桥接链。
若共享 `/tf` 出现非相机 owner，只能把采样标成 mixed diagnostic 并保持 readiness=false；
不得通过操作非相机节点来制造 camera-only PASS。软件停止也不能替代现场物理急停或断电。

## 仍需现场补齐

- 四场景独立 RGB-D 数据与 typed frame；
- 垃圾桶独立 precision/recall/F1；
- 透明/反光瓶和目标 ROI 深度有效率；
- `base_link -> camera_color_optical_frame` 实测外参与 TF 复验；
- 0.3～1.5 m 已知真值下，转换到 `base_link` 后 XYZ 误差目标 ±2 cm；
- 处理与消费者端到端延迟分布；
- 桶前瓶/桶边瓶/遮挡/多桶等过滤鲁棒性；
- 正式机器人 install 重建、消息生成和只读 launch 回归。

以上证据齐全前，V2 保持不可交付，视觉输出不得接入任何真实运动链。
