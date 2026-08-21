# myCobot J6 手眼姿态 1 拒动与故障锁存记录（2026-08-20）

## 结论

本次只获授权发送一次 J6 `14.50° -> 19.50°`、`speed=5` 的关节命令。命令后机械臂角度未变化，控制器错误码由 `0` 变为 `1`。按项目接口表，`get_error_information()==1` 表示 J1 超出极限位置。因此本次姿态变换不得记为成功，手眼姿态 1 不存在。

当前状态固定为 `FAULT_LATCHED`、`MOTION_BLOCKED`。禁止自动清错、使能、回零、反向脱困、重试原命令或发送新动作。

## 命令前后证据

- 授权范围：仅 J6 `14.50° -> 19.50°`，`speed=5`，夹爪不动，禁止重试。
- 命令前：
  - `connected=1`
  - `angles=[175.69,-42.45,-77.08,22.85,17.57,14.5]`
  - `moving=0`
  - `error=0`
  - `servos=1`
- 命令后约 279 ms：
  - 六关节回读无变化
  - `moving=0`
  - `connected=1`
  - `error=1`
  - `servos=1`
- 命令发送次数：1。
- 未执行：重试、清错、反向动作、回零、pose 1 采集。

动作记录位于采集主机：

- `/tmp/limo_jyu2c_handeye_20260820_v1/motion_00_to_01.json`
- SHA256：`1f198d2cec533c56ddc521d323dca55fb5fd925f8dd7b16e26eff0cf71e5fe85`
- reservation：`/tmp/limo_handeye_j6_14p50_to_19p50_20260820.reserved`

## 现场观察

- Atom 背后蓝灯常亮。
- 机械臂静止，无异响、发热或抖动；无人受伤。
- 用户报告机械臂与其他设备共用供电，当前无法独立物理断电。

这些观察只能证明未见外观异常，不能证明控制器故障已解除。蓝灯含义尚未绑定本机固件的厂商证据，也不能替代 `error==0`、可用的独立物理隔离或急停。

## 判据来源与解释边界

`MYCOBOT_280_M5_ARM_API_INTERFACE_TABLE_2026-08-13.md` 第 7.1 节将错误码 `1..6` 定义为相应关节超出极限位置。故 `error=1` 指向 J1；命令前 J1 回读为 `175.69°`。

目前没有经审核的本机控制器限位值或独立量测证明，不能进一步断言是硬限位、固件软限位、零点偏移还是配置不一致。也不能因为本次目标只改变 J6，就忽略已存在或在校验阶段暴露的 J1 越限。

本地仓库审计还确认：`[-170°, 170°]` 只存在于 fake backend 和单元测试构造数据中，不能作为这台实机的厂商限位证据。正式示例
`src/limo_cleanup_executor/config/arm_motion_release.example.json` 的 `controller_deg` 和 `project_deg` 均为空，因而继续 fail-closed。

纯离线 manifest 门测试（WSL bundled Python 3.14.4，隔离模式、禁止字节码）结果为 `43 passed / 0 failed / 0 skipped`；其中包含“项目限位必须是控制器限位严格子集”“named pose 必须保留限位裕量”和“checked-in example 必须保持 blocked”。这只证明软件门禁行为，不证明实机限位或现场可恢复。

## 恢复门槛

在以下条件全部满足前，不得继续手眼姿态动作或抓取：

1. 建立可从扫掠区外操作的独立物理隔离或经验证的急停方案；共享供电且无法独立断能不满足该门。
2. 用本机固件对应的厂商资料确认 `error=1`、Atom 蓝灯及关节限位语义。
3. 人工检查 J1 实际姿态、零点和线缆/机械干涉；不得用自动动作脱困。
4. 根因处理后，由人工重新授权一次只读状态核验，证明错误码稳定为 `0`、状态新鲜且各关节处于批准软限位内。
5. 重新选择远离任何关节限位的手眼初始姿态，并对每个真实动作逐次授权。

本记录不构成现场恢复许可，也不构成机械臂、夹爪或自主抓取验收通过。

## 人工移动后的只读复核

用户随后人工移动机械臂，并在现场运行只读查询，结果为：

- `connected=1`
- `angles=[-23.11,23.81,41.66,-20.56,-137.19,57.39]`
- `moving=0`
- `error=1`
- `servos=1`

因此故障没有被证明解除，禁止重试 J6 命令。新角度与 pose 0 的
`[175.69,-42.45,-77.08,22.85,17.57,14.5]` 明显不同，原 pose 0 只能作为此前时刻的历史配对样本，不能作为当前机械臂姿态，也不能与后续图像拼成手眼标定数据集。

`error=1` 在人工移离原位置后仍存在，可能是控制器锁存，也可能是零点、限位配置或其他尚未闭合的本机状态问题；只读结果不足以区分。不得为区分这些可能性而自动清错或试探运动。

## 控制器限位确认与单次清错

后续只读回读确认控制器实际配置为：

- J1 `[-168.0°, 168.0°]`
- J2 `[-140.0°, 140.0°]`
- J3 `[-150.0°, 150.0°]`
- J4 `[-150.0°, 150.0°]`
- J5 `[-155.0°, 160.0°]`
- J6 `[-180.0°, 180.0°]`

一次中间回读为 J5 `-163.21°`、`error=5`，与“J5 超出下限”一致。人工将机械臂移到
`[-38.32,-4.92,95.88,-92.37,-121.46,83.84]` 后，所有关节均位于控制器限位内，但 `error=5` 仍锁存。

用户随后明确授权：只调用一次 `clear_error_information()`，仅清除已锁存 `error=5` 并只读复核，禁止机械臂和夹爪动作。执行设置了以下前置门：连接正常、`moving=0`、`error=5`、六关节回读完整有限且全部在控制器限位内；任一不满足则不清错。

执行结果：

- `CLEAR_CALLS=1`
- `CLEAR_RETURN=[1]`
- 0.5 s 后：`connected=1`、`moving=0`、`error=0`、`servos=1`
- 再过 1.0 s：`connected=1`、`moving=0`、`error=0`、`servos=1`
- 清错前后角度变化：`[0.0,0.0,0.0,0.0,0.0,0.0]°`
- 脚本结论：`PASS_CLEAR_ONLY`
- 未调用任何 `send_*`、`set_*`、使能、回零或夹爪接口。
- 执行后 SSH 会话已正常退出。

该结果仅解除本次控制器错误锁存；不恢复旧手眼 pose，不构成运动、手眼标定或抓取放行。后续真实动作仍须重新规划并逐次授权。

## 双相机节点纠偏

清错后的新 pose 0 首次采集错误使用了 `/dev/video0`。现场只读 USB/V4L 映射随后证明该节点
当前属于 DaBai DC1 主相机；JYU2C 腕部相机 index0 当前为 `/dev/video2`，稳定路径为
`/dev/v4l/by-id/usb-JoyandAI_JYU2C-2083_JYU2C-2083-2603103-video-index0`。错误采集只产生
`diagnostic_no_board.png`，没有生成 pose 0 JSON，且明确标记为主相机诊断帧、非手眼证据。

## 第二次 J6 手眼姿态动作失败

相机节点纠偏后，已使用 JYU2C 稳定 by-id 成功取得新的静止 pose 0 候选：

- 腕部相机稳定路径解析为 `/dev/video2`；
- 机械臂角度 `[-41.74,6.76,61.69,-29.09,-140.62,89.12]`；
- TCP `[-193.6,49.0,319.9,141.46,51.17,-40.66]`；
- `error=0`、`moving=0`，采集前后六关节变化均为 `0.0°`；
- 棋盘角点 `88/88`，配对跨度 `53.229 ms`；
- 图像 SHA256 `34f863afa1741fb5d07fc8c8487708f1946582c547864488132f7a29bf6b85df`；
- JSON SHA256 `2c8ea9ca79881e4713f6b2edf79169f2085b91d9779b8cb9a60d0eba21bd3249`。

用户逐动作授权 J6 `89.12° -> 94.12°`、`speed=5`，其他关节与夹爪不动，禁止重试。执行器前置门确认连接、静止、`error=0`、舵机使能、六关节均在控制器限位内，且与 pose 0 回读差异不超过 `0.5°`。随后：

- `SEND_COUNT=1`
- `COMMAND_RETURN=None`
- 第一轮后续状态检查进入 `STATE_OR_ERROR_AFTER_SEND`
- `STOP_COUNT=1`
- `RESULT=FAIL_MOTION_BLOCKED`
- 未重试，未生成 pose 1 图像或 JSON；远程会话已退出。

用户随后现场确认：已物理断电；机械臂静止；无人受伤；无异响、发热或异味；棋盘未移动。

由于失败脚本没有在退出前持久化异常样本的具体错误码与角度，不能从现有证据断言是哪个关节、限位裕量、固件校验或通信状态触发。不得通过重新上电和再次动作补证据。新的 pose 0 可作为静止候选保留，但真实 backend 和全部后续手眼姿态动作重新进入 `MOTION_BLOCKED`。

## 离线故障记录修复

新增纯 Python、无 ROS/厂商运行时/设备访问的 `arm_motion_journal.py`。核心不变量是：每个后续状态样本先以独占 JSONL 追加并 `fsync`，随后才能分类为连接故障、非零错误码、moving 无效、角度无效、其他关节漂移、未到位或目标静止。软件 STOP 的结果单独记录且固定 `physical_stop_proven=false`。

对应定向 pure-fake 测试 `test_arm_motion_journal.py`：`8 passed / 0 failed / 0 skipped`。覆盖非零错误码、`None` 角度、非有限值、其他关节漂移、目标 moving/静止分支、独占创建、单调 sequence、进程 `os._exit`、外部超时强杀，以及 STOP 不冒充物理停止。该修复防止未来再次丢失具体异常样本，但不解释本次已经丢失的错误码，也不解除真实运动阻塞。

相关隔离回归总计 `194 passed / 0 failed / 0 skipped`：arm core 114、backend/factory 24、motion manifest 43、journal 8、JYU2C 身份/候选内参配置 5。core 继续禁止集成持久化 I/O；journal 只能置于独立、有 deadline 的 supervisor 侧。由于当前 `fsync` 尚无可证明 deadline，真实 backend 和现场运动仍保持 `DISABLED/MOTION_BLOCKED`。

## pymycobot 3.3.4 安装源码只读审计

在机械臂物理断电后，对目标机已安装的 pymycobot 3.3.4 Python 源文件做了只读审计。审计没有 import 厂商运行时、没有打开设备节点，也没有调用 ROS graph 或执行器接口；只读 SSH 会话随后已用 `exit` 正常关闭。

源码调用链确认：

```text
send_angle(id, degree, speed)
  -> calibration_parameters(class_name="MyCobot", id=id,
                             angle=degree, speed=speed)
  -> _mesg(SEND_ANGLE, id, [angle_int], speed)
```

因此本次 `send_angle(6, 94.12, 5)` 的客户端编码语义确实是 J6 单关节帧，不是六关节目标帧。该结论只能排除“客户端误把调用编码成六关节命令”，不能解释控制器为何在发送后的首次状态检查失败。

`get_error_information()` 的安装源码文档将 `0` 定义为无错误、`1..6` 定义为相应关节越限、`16..19` 定义为碰撞保护、`32` 定义为逆解无解、`33..34` 定义为直线运动相邻解问题。响应处理路径使用普通单值解析；没有发现针对 `GET_ERROR_INFO` 的客户端侧特殊重映射。由于第二次 J6 失败脚本未先持久化原始后续样本，本次失败的具体返回值仍不可恢复，禁止根据第一次历史 `error=1` 或后来的历史 `error=5` 推定本次错误码。

安装文件 SHA256：

```text
generate.py     5db80b85e411741570a6e52a7bb99886dd5d629b27b1aa722c8333e2a7437304
mycobot.py      ffd51d7961e3996cc0cf55f69ebc97181c6fba8e7b6dedac2d5bc03ce588a8e6
error.py        fb455536b4ff5df9b42c380e541234fa88b3798f861e2a8070e9b7fb2459d251
robot_limit.json f8a69a449c3a7ea0fa1ad4d5c7951aae5dac0d2c9487bc21b6ee4744aef8de5d
```

SDK 静态限位与本机控制器回读值并不一致：

| 关节 | pymycobot 3.3.4 `robot_limit.json` | 本机控制器回读 |
|---|---:|---:|
| J1 | `[-170, 170]` | `[-168, 168]` |
| J2 | `[-135, 140]` | `[-140, 140]` |
| J3 | `[-150, 150]` | `[-150, 150]` |
| J4 | `[-145, 135]` | `[-150, 150]` |
| J5 | `[-170, 170]` | `[-155, 160]` |
| J6 | `[-180, 180]` | `[-180, 180]` |

安装源码还包含 MyCobot 280/320 共用客户端限位、无法据此完成精确机型限位校验的注释。故 SDK 静态参数检查不能替代本机控制器限位，也不能作为动作放行证据。J6 目标 `94.12°` 同时位于两套 J6 范围内，所以这一差异本身仍不能解释第二次拒动。

## 当前证据边界

- 第二次 J6 失败仍是 `FAIL-before-pose1 / root-cause UNKNOWN`，不是限位根因已确认。
- 新 pose 0 仍仅为 `STATIC_PAIR_CANDIDATE_INTRINSICS_REBIND_PENDING`。
- journal 定向测试通过只证明未来能先落原始样本再分类；普通 `fsync` 没有可证明 deadline，不能接入 STOP/epoch 核心路径。
- 新增的 `arm_journal_supervisor_contract.py` 只定义独立 worker 的 one-shot epoch/样本哈希/worker release/record 哈希/持久化 ACK 门。它不执行 I/O、不启动线程或进程；ACK 缺失、超时、迟到、置换、伪造、重复或 close-before-ACK 均永久进入 `PHYSICAL_ISOLATION_REQUIRED`。这仍不是 field runner，也不证明底层 `fsync` 有界。
- 真实 backend、ROS1 现场适配、手眼姿态动作和自主抓取继续为 `DISABLED / MOTION_BLOCKED`。
- 后续若恢复现场，必须使用离线冻结、远离本机控制器限位的姿态，并为每个动作重新取得动作级明确授权；本记录中的“全部安全授权”不自动复用为新动作授权。

本轮 bundled Python 纯软件回归：既有定向门 `196 passed / 0 failed / 1 skipped`，新增 supervisor 契约 `7 passed / 0 failed / 0 skipped`，合计 `204 tests = 203 passed / 0 failed / 1 skipped`。唯一 skip 是当前 Windows 测试环境不提供符号链接能力的 manifest 负测，必须记为 skip，不能计为 PASS；AST 解析与 `git diff --check` 均通过。这些数字仅表示本地 offline/pure-fake 状态，不表示 ROS1、现场或交付通过。

## 复位后多关节非预期移动日志审计

用户报告在仅计划进行手眼基线采集时机械臂再次移动。用户随后物理断电并确认机械臂静止、无人受伤、无异响、发热或异味。断电后进行的只读日志审计没有打开执行器端口、没有 import pymycobot、没有启动 ROS，也没有发送动作。

审计证据：

- 异常前一次稳定只读姿态为 `[-121.81,-84.72,62.84,-69.25,-62.13,150.90]°`。
- 后一次只读基线脚本读到 `[-126.82,-83.67,89.12,-119.35,-67.41,174.11]°`，其中 J3 约变化 `+26.28°`、J4 约变化 `-50.10°`、J6 约变化 `+23.21°`。脚本仅读取状态并尝试打开相机，未包含任何 `send_*`、`jog_*`、`power_on`、使能、清错或夹爪调用；它因腕部相机无帧以 `camera_no_frame` 退出。
- `ps` 未发现 pymycobot、ROS、MoveIt、机械臂或夹爪控制进程。唯一相关 GUI 是自 `18:13:35` 运行的 `guvcview --device=/dev/video2`；它解释腕部相机无法独占打开，但不具备机械臂运动接口。
- 用户 crontab 为空；启用的用户服务只有 Ubuntu report、PulseAudio、tracker、GPG 等桌面服务；systemd/autostart 搜索未发现 pymycobot、`/dev/elephant`、`ttyACM0` 或运动命令引用。
- 当前运行服务筛选没有 robot/arm/cobot/ROS/MoveIt/servo/gripper 控制服务。近期 kernel journal 没有 ttyACM/USB reset/disconnect 记录。
- SSH journal 中相关登录均来自 `192.168.1.186`；未发现第二个网络来源。图形会话 `:0` 自 `16:28` 登录。
- `~/.bash_history` 保存了大量历史实机命令。最后一条可见运动帧是早前搜索阶段的 J1 单关节 `send_angle`，其异常分支随后调用一次 `mc.stop()`。之后直到两次只读复核，没有新的 `send_angle`、`send_angles`、`send_coords`、`jog_angle`、`power_on` 或使能命令。bash history 未启用逐命令时间戳，因此不能仅靠行号给每条历史命令建立秒级时间。
- 手眼基线尝试前 `fuser -v /dev/elephant` 输出为空；这只能证明该查询时没有仍持有设备文件的进程，不能证明控制器内部没有缓存目标。

结论固定为 `UNCOMMANDED_OR_RESUMED_MOTION_SOURCE_UNKNOWN`。现有日志排除了当时仍运行的后台 ROS/pymycobot/cron/systemd 控制进程，也证明最后一段基线采集代码本身没有动作调用；但不能区分以下来源：控制器/舵机在复位或重新使能后恢复缓存目标、失去保持后的重力移动、断电期间人工重摆，或日志系统未记录的控制器内部行为。不得将其中任一项宣称为已确认根因。

在完成“上电但保持执行器禁止输出”的厂商恢复流程、缓存目标清除语义、每关节保持/编码器一致性和唯一串口所有权连续监控前，手眼多姿态采集和抓取继续 `MOTION_BLOCKED`。棋盘实际方格尺寸已由用户纠正为 `15.00 mm`；所有按 `14.00 mm` 计算的历史手眼 PnP 平移和 pose 对均作废，不得混入新数据集。
