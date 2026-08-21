# LIMO Cleanup 坐标系规范

更新时间：2026-08-11
状态：DaBai 真实 RGB/对齐深度 frame 已验收；机械安装外参与工具 TCP 仍待现场实测；
ROS1 → ROS2 bridge 已在本地实现并通过离线测试，但 Catkin 构建、跨图运行、状态与 TF
实机验收尚未完成。

## 1. 目的

本规范定义清理机器人全部关键坐标系及其关系，是感知、抓取和导航的共同空间基础。

任何发布三维位置的节点必须声明位置所属坐标系；任何使用三维位置的节点必须先通过 TF2 把位置转换到自己的工作坐标系，不得假设两边坐标系一致。

约定遵循 ROS 标准：

- REP-103：标准度量单位与坐标轴约定。
- REP-105：移动机器人坐标系命名约定（map / odom / base_link）。

## 2. 坐标系总览

```text
map
└── odom
    └── base_link                              底盘中心
        ├── camera_link                        深度相机安装点（机械位置）
        │   └── camera_depth_frame             深度传感器原点
        │       ├── camera_depth_optical_frame 原始深度光学坐标系
        │       └── camera_color_frame         RGB 传感器坐标系
        │           └── camera_color_optical_frame RGB/对齐深度/真实检测输出
        ├── arm_base_link                      机械臂基座
        │   └── ... 机械臂关节链 ...
        │       └── gripper_tcp                夹爪末端工具点
        └── bin_frame（可选）                  垃圾桶参考系，可用 AprilTag/ArUco 标定
```

## 3. 坐标系定义

| 坐标系 | 父坐标系 | 类型 | 发布者 | 当前状态 |
| --- | --- | --- | --- | --- |
| map | 无 | 全局固定 | 坐标约定 | 定位 / SLAM 验收后启用 |
| odom | map | 全局到局部校正 | 定位 / SLAM | `map -> odom` 尚未实机验收 |
| base_link | odom | 动态底盘里程计 | ROS1 Noetic `limo_base_node` | ROS1 实动已确认；`odom -> base_link` 唯一桥入 ROS2 尚未验收 |
| camera_link | base_link | 静态 | static_transform / URDF | 待实测 |
| camera_depth_frame | camera_link | 静态 | 相机驱动 | DaBai 实机 TF 已确认 |
| camera_depth_optical_frame | camera_depth_frame | 静态 | 相机驱动 | 原始深度光学坐标系；实机 TF 已确认 |
| camera_color_frame | camera_depth_frame | 静态 | 相机驱动 | DaBai 实机 TF 已确认 |
| camera_color_optical_frame | camera_color_frame | 静态 | 相机驱动 | RGB、对齐深度、CameraInfo 与真实检测输出 frame |
| arm_base_link | base_link | 静态 | static_transform / URDF | myCobot 280 M5 已确认；安装外参待测 |
| gripper_tcp | 机械臂末关节 | 动态 | 机械臂驱动 | `mycobot_gripper_ag` 已确认；TCP 待标定 |
| touch_tcp | 机械臂法兰 | 静态工具外参 | URDF / static_transform | touch-only 专用软触碰头；待测，禁止沿用 gripper TCP |
| bin_frame | map | 静态 | 手动标定 / AprilTag | 待垃圾桶方案确认 |

### 3.1 跨 ROS 版本的 TF 所有权

当前 ROS1 Noetic `limo_base_node` 是 `/dev/ttyTHS0` 的唯一底盘 driver，也是
`odom -> base_link` 的权威来源。ROS2 Foxy `limo_base` 只保留为历史诊断路径，不得与
ROS1 driver 并发，也不得在 ROS2 中再生成第二份 `odom -> base_link`。

`map -> odom` 只归定位或 SLAM 节点所有，不能由底盘 driver 或
`robot_state_publisher` 发布。`robot_state_publisher` 只负责 URDF 关节链，不是动态
底盘里程计 TF 的 owner。

ROS1 的 `/odom`、`/imu`、`/tf`、`/tf_static` 以及底盘状态如何进入 ROS2 尚未验收。
`/limo_status` 等自定义消息必须先确认 ROS1/ROS2 消息定义和 bridge pair；`/tf` 与
`/tf_static` 必须完成逐 child 唯一所有权审计后才可桥接。禁止同时“桥接原 TF”并在
ROS2 根据 `/odom` 重发同一 `odom -> base_link`。

ROS2 checker 与 `view_frames` 看不到 ROS1 原生图。只看到一棵无冲突的 ROS2 TF 树，不能
证明 ROS1 中不存在第二个发布者；所有权结论必须同时来自 ROS1 图、ROS2 图和实际 bridge
端点。当前状态为 `ROS1_ROS2_BASE_BRIDGE_IMPLEMENTED_LOCALLY_UNVERIFIED`：本地实现和
离线测试不等于 Catkin 构建、ROS1/ROS2 跨图运行或机器人 TF/状态验收通过。V1 不等待
这些 bridge 验收，但 V1 也不启用依赖它的真实自动导航或底盘运动。

已确认执行机构为大象机器人（Elephant Robotics）myCobot 280 M5，末端执行器为
myCobot Gripper AG（`mycobot_gripper_ag`）。型号确认不代表运动授权；机械臂安装板、
独立供电、通信方式、固件/驱动版本、急停方案、`arm_base_link` 安装外参和
`gripper_tcp` 工具中心点仍须在到货后实测并记录。

实机已确认深度相机为 ORBBEC DaBai。当前驱动发布上述完整内部 TF；硬件对齐开启时，
`/camera/color/image_raw`、`/camera/depth/image_raw` 和两路 CameraInfo 的 header 均为
`camera_color_optical_frame`。若更换 `astra_camera` / `orbbec_camera` 版本、关闭深度对齐
或修改相机 profile，必须重新只读核对话题 header 与 TF，不能沿用本次结论。

## 4. 坐标轴约定

- base_link：x 向前，y 向左，z 向上；原点与官方 URDF 保持一致。
- camera_color_optical_frame 与 camera_depth_optical_frame：z 向前（视线方向），x 向右，y 向下，即 ROS / OpenCV 相机光学坐标系标准约定。
- 深度相机驱动一般会自行发布 camera_link 与 optical 坐标系之间的固定旋转，不要手工猜测这个旋转。

## 5. ObjectDetection 的坐标系契约

`limo_cleanup_interfaces/msg/ObjectDetection` 的 `frame_id` 字段表示 `position` 与 `size` 所属坐标系。

当前规则：

1. 真实双模型 detector 的 `frame_id_override` 保持为空，继承 RGB Image header；当前已验收
   DaBai 的真实输出为 `camera_color_optical_frame`，单位为米。由于深度已对齐到 RGB 像素网格，
   使用对齐深度计算的三维点也属于该坐标系。
2. 模拟感知仍可使用 `camera_depth_optical_frame`；真实和模拟结果都必须以消息自身
   `frame_id` 为准，不得按节点类型猜测。
3. 执行器在驱动底盘或机械臂之前，必须先把目标位置通过 TF2 转换到 `base_link`（底盘接近）或 `arm_base_link`（触碰规划）。
4. TF 转换失败（变换不存在、时间戳超差、外参未标定）时不得使用该检测结果，按感知失败处理。
5. `detection_gate` 质量门只允许 frame_id 白名单内的检测通过，当前代码默认：
   `camera_color_optical_frame`、`camera_depth_optical_frame`、`base_link`、`arm_base_link`。

## 6. 待实测的静态变换（占位表）

样机到货后逐项测量并填入，随后写入 URDF 或 static_transform_publisher 配置：

| 变换 | 平移 x, y, z（米） | 旋转 roll, pitch, yaw（弧度） | 测量方式 |
| --- | --- | --- | --- |
| base_link → camera_link | 待测 | 待测 | 卷尺 / 卡尺 + 安装孔位 |
| camera_link → camera_depth_frame | 驱动已发布 | 驱动已发布 | 配置变更后只读复核 |
| camera_depth_frame → camera_color_frame | 驱动已发布 | 驱动已发布 | 配置变更后只读复核 |
| base_link → arm_base_link | 待测 | 待测 | 安装板图纸 / 实测 |
| 机械臂末关节 → gripper_tcp | 待测 | 待测 | 夹爪图纸 / 实测 |
| 机械臂法兰 → touch_tcp | 待测 | 待测 | 软触碰头图纸 / 三次独立实测 |
| map → bin_frame | 待标定 | 待标定 | AprilTag / 手动标定 |

touch-only 的现场记录统一填写 `docs/touch_only_arm_geometry_field_sheet.md`。在该表复核结论
达到 `REVIEWED` 前，不得发布 `base_link -> arm_base_link` 或 `arm_flange -> touch_tcp`
占位变换，不得把空白或全零值解释为已标定。

## 7. 实机只读验证步骤

验证期间不启动 RViz / Gazebo（WSL 渲染风险见进度记录第 8 节），全部使用命令行工具：

1. 在隔离的 ROS1、ROS2 shell 中分别记录节点、TF 发布者和话题端点，并核对
   `/dev/ttyTHS0` 只有 ROS1 `limo_base_node` 或完全无 owner；任一侧查询失败都不能按安全处理。
2. bridge 尚未验收时，只验证 ROS2 相机子树，不得宣称 `map -> odom -> base_link` 已连通。
3. bridge 的状态/TF 白名单和唯一 owner 通过后，才运行
   `ros2 run tf2_tools view_frames` 生成 frames.pdf，并确认没有重复 child。
4. `ros2 run tf2_ros tf2_echo base_link camera_color_optical_frame` 确认真实检测 frame 的完整变换与实测一致。
5. 使用 `ros2 topic list -t` 与 `ros2 topic info --verbose <topic>` 记录 RGB、深度、
   `camera_info` 和点云的实际消息类型、发布者与 QoS。Foxy 手册提示图像采用
   Best Effort，Humble 环境需按实际发布者匹配。
6. 把已知尺寸的标定物放在底盘正前方 0.3～1.5 m 的已知距离处，比较检测三维
   位置经 TF2 转换到 base_link 后的误差。DaBai 手册标称深度有效范围为
   0.3～3 m，0.3 m 内的结果不得纳入有效测量。
7. 位置误差进入可接受范围（首版目标 ±2 cm），且 bridge、ROS1 watchdog、状态话题和
   TF 断链/唯一所有权全部通过之前，只允许只读验证，不允许驱动底盘或机械臂。

验证顺序（与进度记录第 16.2 节一致）：

```text
能读取图像
能读取深度
能获得相机内参
能检测类别
能计算三维位置
能转换坐标
位置误差达到可接受范围
bridge / watchdog / 状态 / TF 验收通过
再分别申请底盘或机械臂单次动作授权
```
