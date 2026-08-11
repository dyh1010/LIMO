# 履带底盘 Stage 2 现场签字记录

用途：记录第 0～1 级现场证据，供 `tracked_base_stage2_preflight.sh` 人工复核。本文件不是
授权脚本，不会设置环境变量，也不代表允许启动原厂 `limo_base`。

当前状态：**未签字，禁止 Stage 2**。

## 只读软件基线

- 日期：2026-08-11
- 主机：`master`
- ROS：Foxy，`ROS_DOMAIN_ID=137`，`ROS_LOCALHOST_ONLY=0`
- 原厂包：`/home/agilex/limo_ros2_ws/install/limo_base`
- 底盘端口：`/dev/ttyTHS0`
- sysfs 设备：`/sys/devices/platform/3100000.serial`
- 内核驱动：`/sys/bus/platform/drivers/serial-tegra`
- 串口占用：无
- `dialout`：已确认
- kernel console / serial-getty 冲突：无
- 命令话题端点：第 1 级审计时不存在
- 原厂启动行为：会调用 `enableCommandedMode()` 并发送 `0x421`
- 当前 preflight：`STAGE2_PREFLIGHT_BLOCKED`

以上仅为只读证据。每次 Stage 2 前仍必须重新运行预检，禁止复制旧 PASS。

## A. 机械与模式检查

- [ ] 两侧模式插销均处于四轮差速/履带要求的位置，短线朝车头并实际插入。
- [ ] 两侧履带安装完整、方向正确、张力合适，无跳齿或脱轨迹象。
- [ ] 两侧车门抬起并固定，不与履带接触。
- [ ] 上电后黄色模式灯稳定常亮；已记录照片或现场观察时间。
- [ ] 机械臂已收纳，`allow_arm_motion=false`，线缆不会卷入履带。

观察时间：____________________

现场人员：____________________　签字：____________________

异常/照片编号：____________________________________________________________

## B. 测试区域与人员

- [ ] 地面平整、干燥、无散落线缆和可卷入物。
- [ ] 机器人四周至少保留 1 m 缓冲区，并设置软围挡。
- [ ] 机器人已经架空或置于可靠托轮架，履带不会接触地面或人员。
- [ ] 现场只保留一名命令操作者和一名急停观察员；职责已口头确认。
- [ ] 禁用键盘、手柄、Nav2、teleop 和历史调试节点。

现场人员：____________________　签字：____________________

## C. 物理急停/断电独立测试

本项必须在未启动原厂 `limo_base`、未发布任何速度命令时独立完成。

- [ ] 急停或物理断电装置可直接触达，无物体遮挡。
- [ ] 已实际操作急停/断电，并确认机器人供能被切断。
- [ ] 已恢复供电并确认没有自动运动、没有遗留运动节点或命令话题端点。
- [ ] 急停观察员知道出现任何履带动作时立即执行物理停止，而非等待软件响应。

测试时间：____________________

急停观察员：__________________　签字：____________________

测试结果/异常：____________________________________________________________

## D. `0x421` 硬件写入知情确认

启动原厂 `limo_base` 不是只读操作。它会打开 `/dev/ttyTHS0`，调用
`enableCommandedMode()`，并向底盘发送 `MSG_CTRL_MODE_CONFIG_ID (0x421)`。

- [ ] 我理解 Stage 2 会发生上述硬件写入，即使 `allow_base_motion=false`。
- [ ] 我理解软件“紧急停止”或语音 cancel 不能替代物理急停。
- [ ] 我理解 Stage 2 只允许全零命令，不授权真实移动、导航或机械臂动作。
- [ ] 我明确授权本次、单次 Stage 2 零速验收；授权在退出后自动失效。

授权人：______________________　签字：____________________

授权时间：____________________

## E. 运行前复核

所有 A～D 项均签字后，现场人员才可在同一终端临时设置三个确认变量。UART 身份变量必须
逐字使用本页只读基线，不得根据端口名称猜测：

```bash
unset ROS_DISCOVERY_SERVER CYCLONEDDS_URI FASTRTPS_DEFAULT_PROFILES_FILE
export ROS_DOMAIN_ID=137
export ROS_LOCALHOST_ONLY=0
export TRACKED_BASE_PHYSICAL_CHECKLIST_CONFIRMED=YES
export TRACKED_BASE_ESTOP_TESTED=YES
export TRACKED_BASE_COMMAND_MODE_WRITE_ACK=YES
export TRACKED_BASE_EXPECTED_SYSFS_DEVICE=/sys/devices/platform/3100000.serial
export TRACKED_BASE_EXPECTED_DRIVER=/sys/bus/platform/drivers/serial-tegra
bash scripts/tracked_base_stage2_preflight.sh
```

预检时间：____________________

预检输出：`STAGE2_PREFLIGHT_`____________________

操作者：______________________　签字：____________________

若不是精确的 `STAGE2_PREFLIGHT_PASS`，立即停止，不得启动零速网关或原厂驱动。

## F. Stage 2 结束记录

- [ ] 先停止 `limo_base_stage2`，确认原厂状态话题消失。
- [ ] 再停止零速网关。
- [ ] 四个公开命令话题与私有安全话题均无残留端点。
- [ ] `/dev/ttyTHS0` 无占用。
- [ ] 履带全程没有运动。
- [ ] 三个现场确认环境变量已在终端退出后失效。

结束时间：____________________

操作者：______________________　急停观察员：______________________

异常/结论：________________________________________________________________
