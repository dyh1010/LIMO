# 双模型真实感知节点

## 目标

`dual_model_detector` 同时运行当前稳定的瓶模型和垃圾桶模型。垃圾桶检测只用于建立
桶口近似区域；中心落入该区域且重叠率足够的瓶子会被判定为“已经投放”，不会发布到
`/cleanup/detection/raw`，避免机器人重复处理桶内瓶。

真实节点只在收到 `pick_and_dispose / plastic_bottle` 任务后处理最新 RGB-D 帧。
只有具备有效深度和相机内参的桶外瓶目标才会生成 `ObjectDetection`。

## 离线图片验证

```bash
source /opt/ros/humble/setup.bash
source ~/robotics/workspaces/limo_cleanup_ws/install/setup.bash

~/robotics/train/venv/bin/python -m \
  limo_cleanup_perception.offline_dual_detector \
  --image /path/to/test.jpg \
  --bottle-model /mnt/c/Users/DYH/Desktop/limo_graphtest/models/nongfu_yolov8n_best.pt \
  --bin-model /mnt/c/Users/DYH/Desktop/limo_graphtest/models/trash_bin_yolov8n_best.pt \
  --output-dir /tmp/limo_perception_test
```

批量任务可后台运行：

```bash
~/robotics/workspaces/limo_cleanup_ws/scripts/run_offline_perception_background.sh \
  /tmp/limo_perception_batch \
  --input-dir /path/to/images \
  --bottle-model /path/to/bottle.pt \
  --bin-model /path/to/bin.pt
```

进度与结果分别写入 `offline_dual_detector.log`、`summary.json` 和逐图 JSON。

## 到货后的启动方式

先确认 RGB、对齐深度和 CameraInfo 的实际话题，再运行：

```bash
ros2 launch limo_cleanup_bringup cleanup_system.launch.py \
  use_mock_perception:=false \
  use_real_perception:=true \
  use_mock_executor:=true \
  rgb_topic:=/actual/rgb/topic \
  depth_topic:=/actual/aligned_depth/topic \
  camera_info_topic:=/actual/camera_info/topic
```

在三维误差验收通过前保持 `use_mock_executor:=true`，不得驱动底盘或机械臂。

只启动相机读取和真实感知、完全不启动任务管理器或执行器时，使用：

```bash
ros2 launch limo_cleanup_bringup real_perception_only.launch.py \
  start_camera:=false \
  rgb_topic:=/actual/rgb/topic \
  depth_topic:=/actual/aligned_depth/topic \
  camera_info_topic:=/actual/camera_info/topic
```

该入口默认 `always_active:=true`，无需先发布 `CleanupTask` 即可持续处理 RGB-D；
它只发布感知结果和状态，不包含任何运动执行节点。

## 当前限制

- 桶口区域当前使用垃圾桶二维框全宽的上部 62%，`in_bin_overlap=0.30`。该值已在现有
  混合图片上离线调试；实机低机位视角变化后仍应复核 `opening_height_ratio`、
  `opening_margin_ratio` 和 `in_bin_overlap`。
- RGB 与深度必须已经对齐；节点不会自行重投影深度图。
- 节点不依赖 `cv_bridge`，常见 RGB/深度 `Image.encoding` 由 NumPy 直接转换，
  避免 ROS Humble 的 NumPy 1.x 扩展与训练环境 NumPy 2.x 产生 ABI 冲突。
- launch 默认使用 `~/robotics/train/venv/bin/python` 启动真实感知节点，以提供
  Torch、Ultralytics 和 GPU 支持；部署环境变化时应覆盖 `perception_python`。
- 当前只发布瓶目标；垃圾桶导航仍使用后续确定的固定 `bin_frame` 或独立导航目标。
