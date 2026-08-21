# LIMO Pro 官方手册项目摘录

更新时间：2026-08-11
资料来源：本地官方文档 `Limo Pro user manual(EN).md`、中文版本及
`Limo Pro Ros2 Foxy user manual(EN).md`。

## 1. 使用范围与版本边界

官方资料同时包含 ROS 1 示例、ROS 2 Foxy 示例，以及 Jetson Nano 时代遗留文字；
LIMO Pro 规格表则写明 Jetson Orin Nano。当前开发电脑使用 ROS 2 Humble，目标机同时
安装 ROS1 Noetic 与 ROS2 Foxy。现场已经确认真正能够驱动本机履带的是 ROS1 Noetic
`limo_base_node`，而不是此前假定的 ROS2 Foxy vendor 路径。因此：

- 硬件参数可作为到货验收清单，但仍以样机铭牌和实测为准。
- ROS1/ROS2 手册中的包名、launch 和话题只作为历史线索，不能直接视为本项目实机契约。
- ROS1 Noetic `limo_base_node` 是 `/dev/ttyTHS0` 的唯一底盘硬件 owner；ROS2 `limo_base`
  仅保留为历史诊断路径，两套 driver 永远不得并发。
- ROS2 清理系统必须经过受限单向 bridge、ROS1 fail-closed watchdog 和私有
  `/cleanup/base/driver_cmd_vel` 才能接入 ROS1 driver。bridge、catkin wrapper 与 watchdog
  已在本地实现并通过离线测试，但 Catkin 构建、ROS1/ROS2 跨图运行、机器人全零、断链
  停车、状态/TF 和实机运动仍未验证，状态为
  `ROS1_ROS2_BASE_BRIDGE_IMPLEMENTED_LOCALLY_UNVERIFIED`。
- V1 不等待 bridge 实机验收，可继续只读、感知与 dry-run 交付；V1 不得因此绕过 bridge
  或声明已经具备真实自动底盘运动。
- ROS2 checker 看不到 ROS1 图。系统版本、进程、UART owner、ROS1/ROS2 话题、状态、TF
  和 QoS 必须分别从实机两套图中记录，不能用一侧的空结果推断另一侧安全。

## 2. 底盘与计算平台

| 项目 | 手册参数 | 对项目的影响 |
| --- | --- | --- |
| 整机尺寸 | 322 × 220 × 251 mm | 场地、围挡和垃圾桶接近规划参考 |
| 自重 | 4.8 kg | 搬运和急停方案参考 |
| 额定载荷 | 4 kg | 机械臂、安装板、夹爪和附加设备总重必须计入 |
| 最小离地间隙 | 24 mm | 首版应坚持平整地面，避开线缆和门槛 |
| 最高空载速度 | 1 m/s | 首版实机调试必须设置更低的软件限速 |
| Ackermann 最小转弯半径 | 0.4 m | 场地与垃圾桶周边需要预留转弯空间 |
| 最大爬坡能力 | 20° | 不作为首版实验场地目标 |
| 工作温度 | -10～40 ℃ | 与室内实验条件兼容 |
| 标称工作时间 | 2.5 h | 训练/联调前安排电量检查 |
| 计算平台 | Jetson Orin Nano，8 GB LPDDR5 | 需要实测 JetPack/CUDA/ROS 版本 |
| 存储 | 128 GB NVMe | 模型和日志容量有限，数据集仍放开发电脑 |
| IMU | HI226 | 到货后检查驱动话题、frame_id 和时间戳 |

手册列出的扩展接口包括 Gigabit Ethernet、4×USB 3.2 Gen2、UART、SPI、I2C、
CAN、PWM 和 GPIO；车体外部 USB HUB 则是 1×Type-C、2×USB 2.0。

## 3. 供电与安全限制

- 电池典型容量 10 Ah，标称电压 11.1 V，充电截止 12.6 V，放电截止 8.25 V。
- 原装充电器为 12.6 V / 2 A，从低电压到充满约 2.5 h。
- 充电时必须关机、拆下电池，并让电池与车体断开；禁止边充边运行。
- 电池向底盘、计算平台和传感器提供的最大总电流为 10 A，超出后进入过流保护。
- 外部 USB HUB 三个接口的总输出电流最多 0.5 A，不适合给机械臂或高功率扩展件供电。
- 车体不防水；工作湿度 30%～80%，避免雨雪、积水、腐蚀性和易燃环境。

## 4. 深度相机 DaBai

| 项目 | 手册参数 |
| --- | --- |
| 成像方式 | 双目结构光 |
| 深度有效距离 | 0.3～3 m |
| 深度分辨率 | 640×400@30 FPS；320×200@30 FPS |
| RGB 分辨率 | 1920×1080 / 1280×720 / 640×480@30 FPS |
| 标称精度 | 6 mm@1 m（指定 FOV 区域） |
| 深度 FOV | 水平 67.9°，垂直 45.3° |
| 延迟 | 30～45 ms |
| 数据与供电 | USB 2.0 或以上，USB 供电 |
| 工作温度 | 10～40 ℃ |

项目约束：

1. 当前数据集从 0.3 m 起采集，与相机最小深度距离一致。
2. 目标进入 0.3 m 以内后，不得继续把深度值当成可靠测量；抓取末段需要机械臂
   标定、预抓取位姿或其他近距离策略。
3. 6 mm@1 m 是相机标称值，不包含 RGB/深度对齐、外参、TF、检测框和机械安装误差；
   项目 ±2 cm 的总误差目标仍必须实测。
4. ROS 2 Foxy 手册使用 `camera_link`，图像显示建议 Best Effort QoS。Humble 接入时
   必须读取实际 `camera_info`、frame_id、话题名与 QoS，不能硬编码 Foxy 示例。

手册中的 Foxy 启动参考：

```bash
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: ros2 launch astra_camera dabai.launch.py
# 失败时手册建议尝试：
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: ros2 launch orbbec_camera dabai.launch.py
```

以上只保留为手册历史。2026-08-14 本机曾观察到以下 ROS1 Noetic
package-resolution 命令；它现在是 **HISTORICAL / FORBIDDEN**，不得执行：

```bash
# DO NOT RUN -- historical observation only
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: roslaunch astra_camera dabai_u3.launch
```

实测 launch SHA-256 为
`75f9ada995ac961d0b4dddb7d86d591f57dc5392165663f4a905709a24231b2e`。
现场不得再默认使用 Foxy 相机图、DDS QoS 或 rosbag2 作为 V2 验收入口。
未来只允许按 `PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md` 使用 host-owned
`ros1_camera_only_atomic_launcher.py` 的 sealed-memfd camera-only 路径；旧
`scripts/start_dabai_camera.sh` 已永久 fail-closed。

## 5. LiDAR T-mini Pro

| 项目 | 手册参数 |
| --- | --- |
| 原理 | 360° 2D Pulse ToF |
| 测距频率 | 4000 Hz |
| 扫描频率 | 6～12 Hz，推荐 6 Hz |
| 室内标称量程 | 0.02～12 m（80% 反射率目标） |
| 标称精度 | 20 mm |
| 角分辨率 | 0.54° |

ROS 2 Foxy 手册通过 `ros2 launch limo_bringup limo_start.launch.py` 启动底盘与
LiDAR；该命令现在只保留为历史资料，不能作为本机默认实机入口。现场实际底盘基线是
ROS1 `~/agilex_ws` 中的 `limo_start.launch`。ROS1 bringup 是否同时拥有 LiDAR 与相关 TF、
以及 `/scan` 的实际名称、时间戳、frame_id 和扫描频率，仍须通过 ROS1 运行图单独核对；
桥入 ROS2 前还要排除重复 TF owner。

## 6. MyCobot 280 M5（选配）

| 项目 | 手册参数 |
| --- | --- |
| 自由度 | 6 |
| 额定负载 | 250 g |
| 工作半径 | 280 mm |
| 重复定位精度 | ±0.5 mm |
| 自重 | 800 g |
| 供电 | 12 V / 5 A |
| 通信 | Type-C；示例使用 USB UART |
| 示例串口 | `/dev/ttyACM0` |
| 示例波特率 | 115200 |

直接影响：

- 标准版 LIMO Pro 不含机械臂，必须核对采购清单、夹爪、安装板、独立供电和线缆。
- 满装 500/550 ml 水瓶的质量明显超过 250 g，不能作为 MyCobot 280 的抓取验收物。
- 额定负载还需结合夹爪和转接件的质量、姿态与力矩核算；首版实机抓取优先使用
  已称重的空瓶或轻量模型瓶。
- 机械臂需要约 60 W 额定输入，不能从总输出仅 0.5 A 的车体 USB HUB 取电。
- 手册要求先把机械臂配置为 Transponder → USB UART，再进行 API/MoveIt 控制。

## 7. 底盘接口线索与实机纠偏

Foxy 手册提供以下参考，但这些命令只用于保存上游接口线索：

> **禁止直接执行以下原厂示例。** 它们仅用于记录手册接口：`limo_base` 启动会发送
> `0x421` 硬件写入，直接向 `/cmd_vel` 发布会绕过本项目安全网关。ROS2 vendor Stage 2/3
> 流程现已冻结为历史诊断资产，不是默认实机路径，也不得作为 bridge 的替代方案。

```bash
# HISTORICAL VENDOR EXAMPLES — DO NOT RUN
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: ros2 launch limo_base limo_base.launch.py
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "..."
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: ros2 launch limo_bringup limo_start.launch.py
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: ros2 launch limo_bringup limo_nav2.launch.py
# LEGACY_NONAUTHORITATIVE/DO NOT RUN: ros2 launch limo_bringup limo_nav2_ackmann.launch.py
```

2026-08-11 现场已经用以下 ROS1 命令成功让履带运动。它们只记录已经发生的证据，不构成
后续运行授权；在确认 ROS1/ROS2 进程和 UART owner 前不得直接重跑：

```bash
# VERIFIED HISTORICAL FIELD EVIDENCE — DO NOT RE-RUN WITHOUT A NEW CHECK
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: source ~/agilex_ws/devel/setup.bash
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: roslaunch limo_bringup limo_start.launch
# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN: roslaunch limo_bringup limo_teletop_keyboard.launch
```

实际运动节点为 ROS1 `limo_base_node`，使用 `ttyTHS0`、`use_mcnamu=false`。同日 ROS2
受控链虽然观测到 `linear.x=0.03 m/s`、持续 `0.5 s`，履带却没有物理动作，因此不能记为
Stage 3 通过，也不能把无动作直接归因于死区、模式或某个单一原因。

当前自动底盘目标链固定为：

```text
ROS2 /cleanup/base/cmd_vel_request
  -> ROS2 tracked_base_controller
  -> ROS2 /cleanup/base/safe_cmd_vel
  -> 受限单向 bridge（仅 Twist，ROS2 -> ROS1）
  -> ROS1 /cleanup/base/safe_cmd_vel
  -> ROS1 fail-closed timeout/watchdog
  -> ROS1 /cleanup/base/driver_cmd_vel
  -> ROS1 limo_base_node（原 /cmd_vel 订阅 remap 到私有话题）
  -> /dev/ttyTHS0
```

自动模式下公开 ROS1 `/cmd_vel` 必须无端点，bridge 不得直接发布公开 `/cmd_vel` 或私有
driver 话题，也不得使用 `--bridge-all-topics`。bridge、watchdog 或授权链断开时必须按
已验收的有界超时停车；该行为目前尚无完整实现和现场证据。

- 四轮差速、履带和麦轮共用普通导航入口；Ackermann 使用单独入口。
- 手册中的 `/cmd_vel` 是底盘历史公开入口；本项目自动模式必须把 ROS1 driver 订阅 remap
  到私有 `/cleanup/base/driver_cmd_vel`，禁止任何节点绕过 ROS2 网关和 ROS1 watchdog。
- 手册要求遥控器/APP切换到 command mode 后程序控制才生效；模式状态也需要纳入
  实机验收与安全检查。
- ROS 1 主手册显示驱动会发布里程计、LIMO 状态和 IMU，并读取电池电压与错误码；
  当前只把 `/odom`、`/imu` 列为首版 ROS1 → ROS2 候选白名单。`/limo_status` 的消息定义
  和 bridge pair、`/tf`/`/tf_static` 的逐 child 唯一 owner 均未验收，禁止盲桥。

## 8. 实机验收检查项

1. 核对 Jetson 型号、内存、NVMe、Ubuntu、JetPack、CUDA、ROS 和驱动分支。
2. 核对 DaBai、T-mini Pro、HI226 的型号、USB/串口连接和设备权限。
3. 在彼此隔离的 Noetic 与 Foxy shell 中分别记录 ROS1 `rosnode`/`rostopic` 和 ROS2
   `ros2 node`/`ros2 topic`；不得在同一 shell 混合 source 两套环境。
4. 同时检查进程表和 `fuser /dev/ttyTHS0`，确认 ROS1 `limo_base_node` 是唯一 UART owner，
   ROS2 `limo_base`、第二 driver、teleop 和串口探针均未并发。
5. 对相机图像、深度、相机内参和点云分别记录话题、frame_id、频率与 QoS。
6. 对 ROS1/ROS2 命令话题、里程计、IMU、底盘状态、电池电压和错误码记录实际接口；
   ROS2 checker 的 PASS 不能替代 ROS1 图检查。
7. 用 bridge 的实际 pair 列表验证 Twist 单向白名单和状态消息兼容；确认公开 ROS1
   `/cmd_vel` 无端点，私有 `/cleanup/base/driver_cmd_vel` 只有 watchdog 一个发布者。
8. 分别记录 `map -> odom`、`odom -> base_link`、传感器静态 TF 的唯一 owner；状态和 TF
   bridge 未通过前不得接入 Nav2。
9. 核对机械臂、夹爪、安装板、独立 12 V 供电、串口设备名和通信模式。
10. 称量每个抓取物体；超过机械臂安全负载的物体只允许用于视觉测试。
