# 履带底盘安全控制基线

LIMO 履带模式使用与四轮差速相同的滑移转向模型。当前控制层仅接受：

- `linear.x`：前进/后退；
- `angular.z`：左转/右转。

任何横移、升降、滚转或俯仰速度请求都会被拒绝，而不是静默转换。

## 安全网关

节点：`limo_cleanup_base/tracked_base_controller`

输入：

- `/cleanup/base/cmd_vel_request`：上层速度请求；
- `/cleanup/base/motion_authorized`：持续人工/任务授权心跳；
- `/cleanup/base/safety_clear`：持续安全链心跳。

输出：

- `/cleanup/base/safe_cmd_vel`：经过轴约束、限速、加速度限制和超时保护后的私有底盘命令。

原厂 `limo_base` 的绝对订阅 `/cmd_vel` 必须由专用 Stage 2 包装 Launch 重映射到该私有
话题。Nav2、teleop 或调试节点即使发布普通 `/cmd_vel`，也不得直接连接原厂驱动。

默认值：

```text
use_tracked_base_controller=false
allow_base_motion=false
max_linear_speed=0.12 m/s
max_angular_speed=0.35 rad/s
command_timeout=0.25 s
heartbeat_timeout=0.50 s
```

只有启动参数明确允许运动，并且速度请求、运动授权和安全许可三路消息都为最新状态时，
网关才会输出非零速度。任意消息缺失、过期、取消或出现不支持的运动轴，输出立即归零。
超时判断使用单调时钟，避免系统时间或 ROS 时间回拨让旧心跳继续有效；所有速度、限制和
时间输入必须是有限数值，`NaN` / `Inf` 会 fail-closed。三个输入订阅均使用深度 1，避免
恢复连接后重放积压速度。授权或安全许可变为 `false`、以及收到非法轴时会在回调中立即
发布零速并清除旧速度请求，重新放行后必须收到新的速度请求。

本节点不是导航规划器，也不启动原厂底盘节点。首次实机测试前仍需验证履带安装、黄色模式
指示灯、遥控急停/物理断电、私有安全话题唯一发布者以及原厂底盘的命令超时行为。

原厂 `limo_base` 不是只读驱动：目标机源码确认其启动时会打开默认 `/dev/ttyTHS0`，随后
立即发送 `MSG_CTRL_MODE_CONFIG_ID (0x421)` 进入 commanded mode。任何启动原厂驱动的步骤
都属于第 2 级硬件写入验收，禁止用于第 1 级只读检查。

第 2 级之前使用 `scripts/tracked_base_stage2_preflight.sh` 做 fail-closed 预检。它要求三个
现场确认、固定 `/dev/ttyTHS0`、串口无占用、用户属于 `dialout`、没有 kernel console/
serial-getty 冲突、无运动进程/节点且所有公开/私有命令话题无发布者；任意一项无法证明安全时输出
`STAGE2_PREFLIGHT_BLOCKED`。所需检查工具缺失，以及 `fuser`、`grep` 或 `systemctl` 无法
给出可判定结果时同样阻塞。预检本身不启动节点、不打开串口、不发布消息。

由于板载 UART 没有 `/dev/limo*` 稳定别名，预检还要求把第 1 级审计得到的 sysfs 设备
路径和内核驱动路径作为期望值传入并精确匹配。预检固定使用集成 Domain 137，并要求
`ROS_LOCALHOST_ONLY=0`；`ROS_DISCOVERY_SERVER`、`CYCLONEDDS_URI` 或
`FASTRTPS_DEFAULT_PROFILES_FILE` 等自定义发现覆盖必须清除。ROS 图/话题查询超时或失败
同样直接阻塞，不能按“没有发现节点”处理。

第 2 级使用 `tracked_base_zero_output.launch.py`。该专用 launch 只启动自研安全网关，将
`allow_base_motion` 直接硬编码为 `false`，不暴露运行时放行参数，也不启动原厂底盘节点。
它用于在架空或托轮条件下先建立唯一、持续的零速
`/cleanup/base/safe_cmd_vel` 发布者，同时保持真实 `/cmd_vel` 无发布者。

原厂驱动启动前先运行 `scripts/verify_tracked_zero_output.py`。该观察器只订阅私有安全话题，
要求恰好一个名为 `cleanup_tracked_base_zero_output` 的发布者、只有观察器自身一个订阅者、
至少 10 条六轴全零有限 Twist，并确认四个公开速度话题均无任何端点；输出
`ZERO_OUTPUT_GUARD_PASS` 才能继续。

`tracked_base_vendor_stage2.launch.py` 默认不启动原厂驱动；只有显式设置
`stage2_hardware_write_authorized:=true` 才会执行硬件写入。授权后串口固定为 `ttyTHS0`，原厂
`/cmd_vel` 订阅固定重映射到 `/cleanup/base/safe_cmd_vel`，两项均不提供命令行覆盖入口。

原厂驱动启动后使用 `scripts/verify_tracked_stage2_topology.py` 做只订阅复核，验证私有话题
恰好 1 个零速网关发布端点和恰好 2 个订阅端点（原厂驱动与验证器各 1 个）、公开速度话题
隔离、状态话题精确所有权和连续全轴零速样本。
退出时先停原厂驱动、后停零速网关。

机器人第 1 级审计已记录 `/dev/ttyTHS0` 的精确 sysfs 身份为
`/sys/devices/platform/3100000.serial`，驱动为
`/sys/bus/platform/drivers/serial-tegra`。Foxy/aarch64 8 包构建与全量测试为
`193 tests / 0 errors / 0 failures / 6 skipped`；未签署三项现场确认时 preflight 保持
`STAGE2_PREFLIGHT_BLOCKED`。该结果不是 Stage 2 硬件验收通过。

离线运行时回归将该 launch 的输出重映射到
`/test/cleanup/tracked_zero_output`，再持续注入授权、安全许可和非零速度请求；通过标准是
所有输出仍为零，并且测试期间真实 `/cmd_vel` 没有发布者。

## 离线话题级 smoke

`scripts/smoke_test_tracked_base.py` 会把输出改到
`/test/cleanup/tracked_cmd_vel`，并明确检查没有真实 `/cmd_vel` 发布者。它依次验证：

1. 缺少授权或安全许可时始终输出零；
2. 条件齐全时输出被限制在 `0.12 m/s` 和 `0.35 rad/s` 以内；
3. 撤销运动授权后立即归零并清除旧请求；
4. 撤销安全许可后立即归零并清除旧请求；
5. 请求横移等履带不支持轴时立即 fail-closed；
6. 指令或心跳过期后立即归零。
