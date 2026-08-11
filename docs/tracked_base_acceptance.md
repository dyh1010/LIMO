# 履带底盘分级验收清单

当前软件已经完成离线实现与模拟验证。本清单从只读检查开始，任何一级失败都不得进入下一
级。机械臂在全部底盘验收期间保持关闭，`allow_arm_motion=false`。

## 第 0 级：机械与现场条件

现场使用 `docs/tracked_base_stage2_field_signoff.md` 逐项记录并签字。该模板不会自动授权，
所有复选框默认保持未勾选。

- 两侧模式插销处于四轮差速位置，短线朝车头并实际插入。
- 履带安装完整、张力合适；两侧车门抬起且不与履带摩擦。
- 车灯黄色常亮，确认处于四轮差速/履带模式。
- 测试区域平整、干燥、四周留有至少 1 m 缓冲区并设置软围挡。
- 现场人员可以直接触达物理断电或急停；先独立验证停止功能。
- 机械臂收纳并断开动作授权，线缆不会卷入履带。

## 第 1 级：只读软件检查

在启动任何底盘控制节点前确认：

```bash
export ROS_DOMAIN_ID=137
ros2 topic info /cmd_vel -v
ros2 node list
```

通过标准：

- `/cmd_vel` 没有未知发布者；
- 没有键盘、手柄、Nav2 或历史调试节点残留；
- 底盘串口、里程计、IMU、状态和电池话题名称已现场记录；
- 本级不得启动原厂 `limo_base`。机器人原厂源码确认其构造函数在打开
  `/dev/ttyTHS0` 后立即调用 `enableCommandedMode()`，向底盘发送控制模式帧 `0x421`；
  因此该节点不是只读状态节点。
- 本级只记录静态设备、进程、ROS 图和 `/cmd_vel` 所有权。底盘状态读取必须等待独立的
  receive-only 监视器，或进入完成第 0 级现场条件后的第 2 级受控验收。

## 第 2 级：架空或托轮零速验证

只有第 0～1 级签字通过并由现场人员明确授权后，才启动原厂 `limo_base` 和履带安全网关；
必须把 `enableCommandedMode()` 视为硬件写操作，而不是只读启动。网关仍保持：

```text
allow_base_motion=false
```

启动前必须先运行只读预检：

```bash
unset ROS_DISCOVERY_SERVER CYCLONEDDS_URI FASTRTPS_DEFAULT_PROFILES_FILE
export ROS_DOMAIN_ID=137
export ROS_LOCALHOST_ONLY=0
export TRACKED_BASE_PHYSICAL_CHECKLIST_CONFIRMED=YES
export TRACKED_BASE_ESTOP_TESTED=YES
export TRACKED_BASE_COMMAND_MODE_WRITE_ACK=YES
export TRACKED_BASE_EXPECTED_SYSFS_DEVICE='/sys/devices/platform/3100000.serial'
export TRACKED_BASE_EXPECTED_DRIVER='/sys/bus/platform/drivers/serial-tegra'
bash scripts/tracked_base_stage2_preflight.sh
```

三个现场确认变量只能由现场人员逐项签字后在当前终端临时设置。两个设备身份变量必须
逐字复制第 1 级审计结果，禁止根据 `ttyTHS0` 名称猜测填写。只有输出
`STAGE2_PREFLIGHT_PASS` 才能讨论第 2 级启动；脚本自身不会启动驱动或发布 ROS 消息。
预检还会拒绝不属于 `dialout` 的运行用户，以及内核 `console=ttyTHS0` 或活动的
`serial-getty@ttyTHS0.service`；检查工具缺失、串口占用查询失败或系统服务状态无法确认也会
直接阻塞。不得通过停止系统服务来绕过本清单，必须先查明原厂配置。
若 Domain、localhost-only 或自定义 DDS 发现环境与上述基线不一致，预检同样阻塞，防止
隔离 ROS 图隐藏真实运动发布者。

先启动专用零速网关：

```bash
ros2 launch limo_cleanup_bringup tracked_base_zero_output.launch.py
```

该 launch 将 `allow_base_motion` 硬编码为 `false`，不提供命令行放行参数，也不启动原厂
`limo_base`。它只向私有话题 `/cleanup/base/safe_cmd_vel` 持续发布零速；先确认该话题只有
`cleanup_tracked_base_zero_output` 一个发布者，并确认真实 `/cmd_vel` 仍无发布者。

在启动原厂驱动前运行第一阶段只订阅观察器：

```bash
python3 scripts/verify_tracked_zero_output.py
```

只有 `ZERO_OUTPUT_GUARD_PASS` 才能继续。观察器要求私有安全话题唯一发布者名称正确且此时
只有观察器自身一个订阅者，连续收到至少 10 条六轴全零有限 Twist，并确认所有公开速度
话题均无任何发布/订阅端点；它不会发送消息。

只有上述状态稳定且现场再次明确授权后，才可在单独终端启动固定配置的原厂驱动：

```bash
ros2 launch limo_cleanup_bringup tracked_base_vendor_stage2.launch.py \
  stage2_hardware_write_authorized:=true
```

该 launch 默认不启动节点；授权后固定使用 `ttyTHS0`，并把原厂 `/cmd_vel` 订阅硬重映射到
`/cleanup/base/safe_cmd_vel`。串口和安全命令话题均不能从命令行改写。若零速发布中断、出现
未知命令发布者或履带有任何动作，立即停止本级。

原厂驱动启动后立即运行只订阅拓扑验证器：

```bash
python3 scripts/verify_tracked_stage2_topology.py
```

只有 `STAGE2_TOPOLOGY_PASS` 才继续本级。它要求私有安全话题恰好有 1 个零速网关发布
端点和 2 个订阅端点（`limo_base_stage2` 与验证器各 1 个），所有公开速度话题没有发布者
或订阅者，`/odom`、`/imu`、`/limo_status` 各恰好有 1 个原厂驱动发布端点，并连续收到
至少 10 条六轴全零有限 Twist。验证器自身只创建一个订阅，不发送任何消息。

离线负向回归已确认：只启动全零网关而不启动原厂驱动时，验证器必须因缺少
`limo_base_stage2` 订阅端点输出 `STAGE2_TOPOLOGY_BLOCKED`，不得把自身订阅误认为驱动
已接入。该负向回归不构成实机 Stage 2 验收通过。

验证网关持续输出零、停止网关后底盘保持不动、DDS 断连不产生残留命令，并确认
`/cleanup/base/safe_cmd_vel` 只有安全网关一个发布者，真实 `/cmd_vel` 始终无发布者。
退出顺序固定为：先停止原厂 `limo_base_stage2`，确认状态话题消失，再停止零速网关；禁止
在原厂驱动仍活动时先撤掉唯一零速发布者。

## 第 3 级：单次短直行

只有第 0～2 级签字通过后，才允许在现场单次设置 `allow_base_motion=true`。使用独立程序
以 10 Hz 以上频率同时发送运动授权、安全许可和速度请求，首次上限为：

```text
linear.x = 0.03 m/s
angular.z = 0.00 rad/s
持续时间 <= 0.5 s
```

通过标准：方向正确、左右履带无干涉、停止距离可控，停止心跳后立即归零。若方向相反、
履带跳齿、车体明显偏航或急停无效，立即停止并回到第 0 级。

## 第 4 级：低速转向与停车

- 直行逐步增加到不超过 `0.08 m/s`；
- 先做大半径转向，不做原地自转；
- 初始 `angular.z` 不超过 `0.15 rad/s`；
- 验证指令超时、取消、安全心跳丢失和 ROS 节点退出都能停车；
- 记录里程计误差、停止距离、履带打滑和地面条件。

履带滑移转向阻力和磨损较大，因此当前软件默认上限 `0.12 m/s`、`0.35 rad/s` 不是首次
实机测试值，而是通过前四级后仍不可超过的系统上限。

## 第 5 级：导航到点

机械臂继续关闭。导航控制器只能向 `/cleanup/base/cmd_vel_request` 请求速度，不能绕过
安全网关发布 `/cleanup/base/safe_cmd_vel`；普通 `/cmd_vel` 也不得成为原厂驱动输入。
验证低速到点、停车误差、取消、障碍物和唯一命令所有权。

导航通过后仍不授权机械臂。下一阶段必须在底盘锁止后独立验收机械臂轻触。
