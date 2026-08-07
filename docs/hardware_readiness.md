# LIMO Pro / DaBai 实机配置与只读验收

更新时间：2026-08-07
状态：机器到货前模板；相机实际话题、TF 名称和外参数值待到货后填写。

## 1. 安全边界

`hardware_readonly_acceptance.launch.py` 只启动可选的相机驱动和订阅型检查节点。它不会启动：

- `limo_base`、导航、`cmd_vel` 发布者；
- 机械臂、MoveIt、轨迹控制器或夹爪控制器；
- 清理任务管理器或真实/模拟执行器；
- RViz 或 Gazebo。

检查节点只订阅 RGB、对齐深度、CameraInfo 和 TF，并查询 ROS graph。它还会检查配置中的底盘、机械臂和夹爪命令话题是否存在发布者；发现发布者时验收失败。

## 已确认的机械臂与末端执行器

截至 2026-08-07，用户侧已确认以下执行机构型号：

| 项目 | 已确认型号 | 当前状态 |
| --- | --- | --- |
| 机械臂 | 大象机器人（Elephant Robotics）myCobot 280 M5 | 型号已确认；安装、供电、通信和驱动待实机核验 |
| 末端执行器 | myCobot Gripper AG（`mycobot_gripper_ag`） | 型号已确认；TCP、夹持力和空矿泉水瓶适配待实测 |

这里的“M5”按用户提供的型号记录，后续采购单、铭牌和驱动文档应进一步确认其完整商品名称、控制器版本及固件版本。

到货后，在允许任何运动指令前必须完成：

1. 确认 myCobot 280 M5 的额定电压、电流、独立电源和接地方案，禁止直接假定由 LIMO 车体供电。
2. 确认机械臂与 LIMO 的安装板、螺孔、重心、工作半径及满伸展状态稳定性。
3. 记录实际通信方式、设备路径或网络地址、固件版本以及 ROS 2 驱动版本。
4. 确认急停或等效断能方案能够同时阻止底盘和机械臂运动。
5. 在空载、低速、限制工作空间条件下检查关节方向、零位、软限位和碰撞风险。
6. 标定 `base_link -> arm_base_link` 和机械臂末端关节到 `gripper_tcp` 的变换。
7. 用实际空矿泉水瓶验证 `mycobot_gripper_ag` 的开口范围、夹持力、瓶身滑落和释放可靠性。

上述项目完成前，机械臂和夹爪仍保持“型号已确认、运动未授权”状态；只读相机与 TF 验收流程不因此放开执行机构。

夹爪软件控制边界、dry-run 方法、真实运动互锁和到货后的逐步验收流程见
`docs/gripper_control.md`。当前控制器默认 `backend=dry_run` 且
`allow_hardware_motion=false`；仅指定真实后端不会打开串口或发送运动命令。

## 2. DaBai 驱动模板

官方 LIMO Pro ROS 2 Foxy 手册给出的入口为：

```bash
ros2 launch orbbec_camera dabai.launch.py
```

当前 Humble WSL 环境尚未安装 `orbbec_camera`。到货后应优先使用机器原厂已验证的驱动版本，不要在确认原厂镜像和 USB 规则前随意替换。先查看驱动实际参数：

```bash
ros2 launch orbbec_camera dabai.launch.py --show-args
```

仅启动相机的项目包装器：

```bash
source /opt/ros/humble/setup.bash
source ~/robotics/workspaces/limo_cleanup_ws/install/setup.bash

ros2 launch limo_cleanup_bringup dabai_camera.launch.py
```

如果原厂包名或启动文件不同：

```bash
ros2 launch limo_cleanup_bringup dabai_camera.launch.py \
  driver_package:=实际包名 \
  driver_launch_file:=实际启动文件.launch.py
```

也可以使用：

```bash
~/robotics/workspaces/limo_cleanup_ws/scripts/start_dabai_camera.sh
```

脚本后的参数会原样传给供应商启动文件。只有 `--show-args` 明确列出的参数才能传入。例如驱动若确实提供 `depth_registration`，才使用：

```bash
scripts/start_dabai_camera.sh depth_registration:=true
```

## 3. 话题参数模板

模板文件：

```text
src/limo_cleanup_bringup/config/dabai_real.yaml
```

需要确认并填写三项：

```yaml
rgb_topic: /camera/color/image_raw
depth_topic: /camera/depth_registered/image_raw
camera_info_topic: /camera/color/camera_info
```

这里的 `depth_topic` 必须是已经注册到 RGB 像素网格的深度图。名称中出现 `registered` 或 `aligned` 不能代替验证；最终必须通过“RGB/深度分辨率一致、时间戳接近、已知距离测量正确”三项检查。

用以下命令记录实际接口：

```bash
ros2 topic list -t | grep -E 'camera|color|depth|image|info|points'
ros2 topic info --verbose /实际RGB话题
ros2 topic info --verbose /实际对齐深度话题
ros2 topic info --verbose /实际CameraInfo话题
ros2 topic echo --once /实际RGB话题/header
ros2 topic echo --once /实际对齐深度话题/header
ros2 topic echo --once /实际CameraInfo话题
```

相机图像通常使用 SensorDataQoS / Best Effort。项目节点已经按 `qos_profile_sensor_data` 订阅。

## 4. TF 和相机外参模板

先检查相机驱动发布的 frame：

```bash
ros2 topic echo --once /实际RGB话题/header
ros2 topic echo --once /actual/aligned_depth/topic/header
ros2 run tf2_ros tf2_echo base_link 实际RGB光学frame
```

`camera_extrinsics.launch.py` 提供 `base_link -> camera_link` 静态变换模板，但默认 `publish_extrinsics:=false`。禁止用全零占位值启动。只有独立测量安装位置后才能发布：

```bash
ros2 launch limo_cleanup_bringup camera_extrinsics.launch.py \
  publish_extrinsics:=true \
  parent_frame:=base_link child_frame:=camera_link \
  x:=实测米 y:=实测米 z:=实测米 \
  roll:=实测弧度 pitch:=实测弧度 yaw:=实测弧度
```

然后把同一组独立测量值写入 `dabai_real.yaml` 的 `expected_*` 字段，并将 `check_expected_extrinsics` 改为 `true`。验收脚本会比较 TF 与实测值，默认允许 2 cm 平移误差和 0.05 rad 角度误差。

不要手工发布 `camera_link -> optical_frame` 的标准光学旋转；该部分应由相机驱动提供。

## 5. 深度单位检查

检查器支持项目节点使用的两类深度格式：

- `16UC1` / `mono16`：按 `depth_scale` 换算，DaBai 模板默认 `0.001`（毫米转米）；
- `32FC1`：数据应已经是米，不再乘 `depth_scale`。

把平整物体放在相机前方已知距离处。DaBai 手册给出的有效深度范围为 0.3～3 m，近于 0.3 m 的结果不作为有效验收数据。报告中的 `median_m` 应与卷尺测量一致；正式允许执行前建议再验证三维点经 TF 转到 `base_link` 后误差不超过项目设定的 ±2 cm。

## 6. 严格只读验收

建议先单独启动相机，再在另一个终端运行验收：

```bash
source /opt/ros/humble/setup.bash
source ~/robotics/workspaces/limo_cleanup_ws/install/setup.bash

scripts/run_hardware_readonly_acceptance.sh \
  rgb_topic:=/实际RGB话题 \
  depth_topic:=/实际对齐深度话题 \
  camera_info_topic:=/实际CameraInfo话题 \
  base_frame:=base_link
```

也可以让验收入口只启动相机驱动：

```bash
scripts/run_hardware_readonly_acceptance.sh start_camera:=true
```

输出报告默认写到：

```text
/tmp/limo_hardware_readiness.json
```

全部检查必须为 `PASS`：

- 三个传感器话题都收到消息；
- RGB、对齐深度、CameraInfo 分辨率匹配；
- RGB 与深度时间戳差在阈值内；
- CameraInfo 的 `fx`、`fy` 有效；
- 深度编码、单位换算和有效距离样本正常；
- `base_link` 到 RGB 光学 frame 的 TF 连通；
- 启用外参比对后，TF 与独立实测值一致；
- 所有配置的执行机构命令话题均无发布者。

只需临时检查相机、尚未提供底盘 TF 时，可以使用 `require_tf:=false`，但这种结果不能作为完整实机验收通过。

## 7. 只读真实感知启动

在上述验收通过后，可以启动只读取传感器的双模型节点：

```bash
ros2 launch limo_cleanup_bringup real_perception_only.launch.py \
  rgb_topic:=/实际RGB话题 \
  depth_topic:=/实际对齐深度话题 \
  camera_info_topic:=/实际CameraInfo话题
```

该入口默认通过训练虚拟环境启动 Ultralytics，并设置 `always_active:=true`，因此不依赖
任务管理器或 `CleanupTask` 就会处理收到的 RGB-D 帧。若虚拟环境位置变化，使用
`perception_python:=/实际/python` 覆盖。

该启动文件不包含任务管理器、底盘、机械臂、夹爪或执行器。真实三维误差和安全验收通过前，不要把它与任何真实运动执行节点组合启动。
