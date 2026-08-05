# LIMO Pro 官方手册项目摘录

更新时间：2026-08-05  
资料来源：本地官方文档 `Limo Pro user manual(EN).md`、中文版本及
`Limo Pro Ros2 Foxy user manual(EN).md`。

## 1. 使用范围与版本边界

官方资料同时包含 ROS 1 示例、ROS 2 Foxy 示例，以及 Jetson Nano 时代遗留文字；
LIMO Pro 规格表则写明 Jetson Orin Nano。当前自研环境是 ROS 2 Humble，因此：

- 硬件参数可作为到货验收清单，但仍以样机铭牌和实测为准。
- Foxy 的包名、launch 文件和话题只能作为排查线索，不能直接视为 Humble 契约。
- 样机到货后先记录系统版本、驱动分支、实际话题、TF 和 QoS，再决定适配方式。

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
ros2 launch astra_camera dabai.launch.py
# 失败时手册建议尝试：
ros2 launch orbbec_camera dabai.launch.py
```

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
LiDAR。样机到货后需核对 `/scan` 的实际名称、时间戳、frame_id 和扫描频率。

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

## 7. ROS 2 接口线索

Foxy 手册提供以下参考：

```bash
ros2 launch limo_base limo_base.launch.py
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "..."
ros2 launch limo_bringup limo_start.launch.py
ros2 launch limo_bringup limo_nav2.launch.py
ros2 launch limo_bringup limo_nav2_ackmann.launch.py
```

- 四轮差速、履带和麦轮共用普通导航入口；Ackermann 使用单独入口。
- `/cmd_vel` 是底盘速度控制入口，但真实运动前必须加入仲裁、限速、超时停车和急停。
- 手册要求遥控器/APP切换到 command mode 后程序控制才生效；模式状态也需要纳入
  到货验收与安全检查。
- ROS 1 主手册显示驱动会发布里程计、LIMO 状态和 IMU，并读取电池电压与错误码；
  Humble 版本的具体消息和话题必须从实机节点图确认。

## 8. 到货验收新增检查项

1. 核对 Jetson 型号、内存、NVMe、Ubuntu、JetPack、CUDA、ROS 和驱动分支。
2. 核对 DaBai、T-mini Pro、HI226 的型号、USB/串口连接和设备权限。
3. 记录 `ros2 topic list -t`、`ros2 node list`、`ros2 action list -t` 和 TF 树。
4. 对相机图像、深度、相机内参和点云分别记录话题、frame_id、频率与 QoS。
5. 对 `/cmd_vel`、里程计、IMU、底盘状态、电池电压和错误码记录实际接口。
6. 核对机械臂、夹爪、安装板、独立 12 V 供电、串口设备名和通信模式。
7. 称量每个抓取物体；超过机械臂安全负载的物体只允许用于视觉测试。

