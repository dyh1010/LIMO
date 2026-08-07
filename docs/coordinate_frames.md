# LIMO Cleanup 坐标系规范

更新时间：2026-08-05
状态：首版草案，占位数值待样机到货后实测更新。

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
        │       └── camera_depth_optical_frame 深度光学坐标系（检测输出）
        ├── arm_base_link                      机械臂基座
        │   └── ... 机械臂关节链 ...
        │       └── gripper_tcp                夹爪末端工具点
        └── bin_frame（可选）                  垃圾桶参考系，可用 AprilTag/ArUco 标定
```

## 3. 坐标系定义

| 坐标系 | 父坐标系 | 类型 | 发布者 | 当前状态 |
| --- | --- | --- | --- | --- |
| map | 无 | 全局固定 | 定位 / SLAM | 样机到货后启用 |
| odom | map | 局部连续 | 底盘里程计 | 官方 limo_base 提供 |
| base_link | odom | 动态 | robot_state_publisher + URDF | 官方 URDF 已提供 |
| camera_link | base_link | 静态 | static_transform / URDF | 待实测 |
| camera_depth_frame | camera_link | 静态 | 相机驱动 | 待相机型号确认 |
| camera_depth_optical_frame | camera_depth_frame | 静态 | 相机驱动 | 首版检测输出坐标系 |
| arm_base_link | base_link | 静态 | static_transform / URDF | myCobot 280 M5 已确认；安装外参待测 |
| gripper_tcp | 机械臂末关节 | 动态 | 机械臂驱动 | `mycobot_gripper_ag` 已确认；TCP 待标定 |
| bin_frame | map | 静态 | 手动标定 / AprilTag | 待垃圾桶方案确认 |

已确认执行机构为大象机器人（Elephant Robotics）myCobot 280 M5，末端执行器为
myCobot Gripper AG（`mycobot_gripper_ag`）。型号确认不代表运动授权；机械臂安装板、
独立供电、通信方式、固件/驱动版本、急停方案、`arm_base_link` 安装外参和
`gripper_tcp` 工具中心点仍须在到货后实测并记录。

官方手册标称深度相机为 ORBBEC DaBai，ROS 2 Foxy 示例使用 `camera_link` 作为
RViz 固定坐标系。但手册没有给出 Humble 驱动的完整 TF 名称，且不同
`astra_camera` / `orbbec_camera` 驱动可能发布不同 frame_id，因此本规范中的
`camera_depth_frame` 和 `camera_depth_optical_frame` 仍须以样机实际 TF 为准。

## 4. 坐标轴约定

- base_link：x 向前，y 向左，z 向上；原点与官方 URDF 保持一致。
- camera_depth_optical_frame：z 向前（视线方向），x 向右，y 向下，即 ROS / OpenCV 相机光学坐标系标准约定。
- 深度相机驱动一般会自行发布 camera_link 与 optical 坐标系之间的固定旋转，不要手工猜测这个旋转。

## 5. ObjectDetection 的坐标系契约

`limo_cleanup_interfaces/msg/ObjectDetection` 的 `frame_id` 字段表示 `position` 与 `size` 所属坐标系。

首版规则：

1. 检测节点（真实或模拟）统一在 `camera_depth_optical_frame` 中输出目标中心位置，单位为米。
2. 执行器在驱动底盘或机械臂之前，必须先把目标位置通过 TF2 转换到 `base_link`（底盘接近）或 `arm_base_link`（抓取规划）。
3. TF 转换失败（变换不存在、时间戳超差、外参未标定）时不得使用该检测结果，按感知失败处理。
4. `detection_gate` 质量门只允许 frame_id 白名单内的检测通过，白名单随坐标系逐步落地开放，当前默认：`camera_depth_optical_frame`、`base_link`、`arm_base_link`。

## 6. 待实测的静态变换（占位表）

样机到货后逐项测量并填入，随后写入 URDF 或 static_transform_publisher 配置：

| 变换 | 平移 x, y, z（米） | 旋转 roll, pitch, yaw（弧度） | 测量方式 |
| --- | --- | --- | --- |
| base_link → camera_link | 待测 | 待测 | 卷尺 / 卡尺 + 安装孔位 |
| camera_link → camera_depth_frame | 待驱动发布 | 待驱动发布 | 相机驱动默认 |
| base_link → arm_base_link | 待测 | 待测 | 安装板图纸 / 实测 |
| 机械臂末关节 → gripper_tcp | 待测 | 待测 | 夹爪图纸 / 实测 |
| map → bin_frame | 待标定 | 待标定 | AprilTag / 手动标定 |

## 7. 到货后的只读验证步骤

验证期间不启动 RViz / Gazebo（WSL 渲染风险见进度记录第 8 节），全部使用命令行工具：

1. `ros2 run tf2_tools view_frames` 生成 frames.pdf，确认整棵坐标树连通。
2. `ros2 run tf2_ros tf2_echo base_link camera_depth_optical_frame` 确认静态变换数值与实测一致。
3. 使用 `ros2 topic list -t` 与 `ros2 topic info --verbose <topic>` 记录 RGB、深度、
   `camera_info` 和点云的实际消息类型、发布者与 QoS。Foxy 手册提示图像采用
   Best Effort，Humble 环境需按实际发布者匹配。
4. 把已知尺寸的标定物放在底盘正前方 0.3～1.5 m 的已知距离处，比较检测三维
   位置经 TF2 转换到 base_link 后的误差。DaBai 手册标称深度有效范围为
   0.3～3 m，0.3 m 内的结果不得纳入有效测量。
5. 位置误差进入可接受范围（首版目标 ±2 cm）之前，只允许只读验证，不允许驱动底盘或机械臂。

验证顺序（与进度记录第 16.2 节一致）：

```text
能读取图像
能读取深度
能获得相机内参
能检测类别
能计算三维位置
能转换坐标
位置误差达到可接受范围
再允许底盘或机械臂动作
```
