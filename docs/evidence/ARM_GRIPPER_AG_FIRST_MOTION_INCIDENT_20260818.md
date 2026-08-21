# AG 夹爪首次位置命令异常记录（2026-08-18）

状态：`FAIL_POSITION_MAPPING_UNBOUNDED`
现场放行：`BLOCKED`
最后遥测运动状态：`MOTION_UNRESOLVED`
物理现状：操作员已报告拔下夹爪线；未独立测量该连接器是否切断全部执行器能量。

## 边界与执行身份

- 所有目标机命令均由现场操作员在 LIMO 终端手动执行；本任务没有建立 SSH、ROS graph 或目标机进程连接。
- 本次没有发送机械臂关节、坐标、回零、解锁或其他机械臂运动命令。
- 异常后没有发送夹爪反向、归零、校准、STOP、release、力矩、电流或第二条位置命令。
- 操作员随后报告已拔下夹爪线。夹爪必须保持断线，直至协议、校准、机械映射与停止能力重新评审。

## 已确认身份

- 机械臂：myCobot 280 M5。
- 夹爪产品资料：Elephant Robotics `myCobot_gripperAg_white`（AG adaptive gripper）。
- 现场 Python 包：操作员报告 `pymycobot 3.3.4`，加载路径为
  `/home/agilex/.local/lib/python3.8/site-packages/pymycobot/__init__.py`。
- 机械部分：操作员称控制器和电机为原厂件，但项目 CAD 是新齿轮/连杆机构。原厂 AG 保留件、
  BOM、齿轮比、相位、硬限位和过中心位置尚未形成受控对应表，因此当前按混合改装工具处理。

## 动作前只读结果

```text
arm_angles = [29.88, 50.88, -119.09, -82.17, -139.3, -143.17]
arm_moving = 0
gripper_value_type1 = 25
gripper_moving = 0
```

现场前提由操作员确认：`Atom:ok`、物理断电可立即操作、夹爪空载净空、有人观察、机械臂保证不动。

## 唯一动作及原始结果

当次授权仅覆盖：`25 -> 26`、`speed=10`、`gripper_type=1`、单次。

脚本的唯一夹爪动作调用：

```python
mc.set_gripper_value(26, 10, 1)
```

原始终端输出：

```text
before_value = 25
before_moving = 0
command_return = None
early_value = 25
early_moving = 1
final_value = 105
final_moving = 1
```

现场观察：夹爪移动到最大开度；无法确认是正常位置到达还是顶住机械限位；当时无异味、无异响。

判据：命令增量为 `+1`，但反馈由 `25` 变为 `105`，且约 1.3 秒后仍报告 moving。该结果不得
登记为最大开度、行程端点、成功 ACK、可信静止或校准前置姿态。

## `pymycobot 3.3.4` 离线源码证据

从 PyPI 获取的 exact wheel：

```text
pymycobot-3.3.4-py3-none-any.whl
SHA256 EE8B7E40589B1ADBC7F6012F6ACAE7D7A628ABB7B72A3DB003F5B06974C25A07
```

相关源码 SHA-256：

```text
generate.py  5DB80B85E411741570A6E52A7BB99886DD5D629B27B1AA722C8333E2A7437304
common.py    5B2524FAD6BFE0AFCABEA5240F549B3EA6E28331D9C83BE4DA7710F449B88AC7
error.py     FB455536B4FF5DF9B42C380E541234FA88B3798F861E2A8070E9B7FB2459D251
mycobot.py   FFD51D7961E3996CC0CF55F69EBC97181C6FBA8E7B6DEDAC2D5BC03CE588A8E6
```

纯软件帧生成结果：

```text
set_gripper_value(26, 10, 1) -> FE FE 05 67 1A 0A 01 FA
set_gripper_value(26, 10)    -> FE FE 04 67 1A 0A FA
get_gripper_value(1)         -> FE FE 03 65 01 FA
is_gripper_moving()          -> FE FE 02 69 FA
```

源码行为：

- `set_gripper_value` 没有请求 reply；`MyCobot._res()` 写帧后直接返回 `None`。因此
  `command_return=None` 是 fire-and-forget 的正常 SDK 行为，不是 ACK。
- `MyCobot.close()` 只关闭串口，不发送夹爪 STOP，也不撤销夹爪控制器中的最后命令。
- `get_gripper_value` 的单字节 payload 会被原样返回；SDK 不检查结果是否落在 `0..100`。
- 3.3.4 接收路径匹配 `FE FE`、命令码和声明长度，但不校验 footer/checksum。反馈 `105` 是入站
  payload 解码结果，不是 Python 把目标 `26` 缩放成 `105`。
- `105` 十进制等于 `0x69`，而 `0x69` 同时是 `IS_GRIPPER_MOVING` 命令码。这不能单独证明串帧，
  但使固件/帧格式错位或状态字段误作位置成为必须排除的假设；本次未启用 raw serial debug，
  因而无法还原实际 RX 帧。

## 厂家资料冲突

- AG 产品页的 M5 示例使用两参数 `set_gripper_value(100, 80)` / `(0, 80)`，未传
  `gripper_type`。
- 厂家底层通信页把 `0x67` 定义为两参数帧：`FE FE 04 67 value speed FA`，并把 `0x65`
  的反馈定义为 `0..100%`。
- 3.3.4 SDK 又公开可选 `gripper_type`，显式传 `1` 时会产生多一个 payload 字节的扩展帧。
- 当前 Atom 固件是否支持该扩展帧没有闭合证据。禁止用再次动作试错来判断。

厂家页面：

- <https://docs.elephantrobotics.com/docs/acc-en/2-serialproduct/2.7-accessories/2.7.3%20grip/2.7.3.1-ag.html>
- <https://docs.elephantrobotics.com/docs/acc-en/18-communication/18-communication.html>

AG 产品页审计快照 SHA-256：
`CC8F169F04D3FD42E5F31EDC4CAE77D55866797604B34F638F16F6DC69D346DB`。

## 2020/2021 官方手册适用边界审计

本节只用于界定两份旧版官方手册能够证明什么，不能把它们提升为当前夹爪固件、协议或机构参数。

审计源身份：

```text
myCobot 开发引导手册 V20210112
SHA256 5D4F2999C2AA7A04C3BA588949FF86691502630F801302D1B10B0180E2148A11

myCobot 用户手册 V20201231
SHA256 A51565C2B55AECA21F4888B17F469C5B818D8B75416943A341C363279F7F87F2
```

开发指南明确覆盖的内容：

- 第 10--11 页要求 Basic 烧录 `transponder`、Atom 烧录“最新版 `atomMain`”，并给出
  USB Type-C、115200 baud、8N1 和 `FE FE LEN CMD DATA... FA` 的旧通信框架；“500 ms
  内返回”只描述该文档中本来具有返回值的指令，不构成当前夹爪命令 ACK、deadline 或 STOP
  保证。
- 第 10、20 页只给出旧式 `setGripper(int data)`/`0x66` 单状态字节表面，其中 `0=打开`、
  `1=关闭`。该表面没有位置、速度、`gripper_type`、力矩、电流、校准、位置反馈、运动反馈或
  独立 STOP 定义。
- 第 19 页的“程序停止运行”及早前的 JOG stop 属于当时机械臂程序/JOG 语义；文档没有把它
  定义成夹爪独立 STOP、物理急停或安全扭矩关闭。
- Atom 上电/断电、机械臂舵机状态和 J1--J6 相关命令均是当时 myCobot 本体控制表面，不能据此
  推定当前夹爪的供电、使能、去能或停止路径。

用户手册明确覆盖的内容：

- 第 5--6 页要求固定机器人、清空运动区域、仅由受训人员操作，并说明更换作业前必须关闭控制器
  与相关装置电源并拔出电源插头；若末端夹持物在失去动力后可能掉落，应先移除物体。
- 第 10 页的 M5 Basic 开机/双击电源键关机是主控操作说明，不是经过证明的执行器能量隔离、
  硬件急停或夹爪安全停机。
- 第 22--23 页校准程序明确针对 J1--J6：A 键使各机械臂关节上电并保存零位，B 键会依次驱动
  J1--J6 测试。它不得作为夹爪归零、行程或电机校准步骤。
- 第 23--24、27 页说明旧式固件烧录器和 `ATOMMAIN` 恢复流程，并强调 Atom 使用原厂固件；
  它没有给出本机当前 Basic/Atom 固件的名称、版本、包哈希或与 `pymycobot 3.3.4` 扩展帧的
  兼容矩阵。本次不执行任何烧录。

明确禁止外推：手册中的整机/开发板/关节参数，包括 `8V/5A`、`5V@500mA`、`4.8--7.4V`、
`1.5 kg·cm`、J1--J6、舵机零点 `2048`，以及旧 `setGripper(0/1)`，都不是当前原厂电控/电机
与新齿轮--连杆机构组合的夹爪供电、零点、行程、方向、力矩或控制命令。

同样不能因为这两份手册没有记录 `0x65/0x67/0x69` 或 `gripper_type` 扩展，就声称这些协议
不存在。正确结论是：旧手册不足以授权或判定这些扩展，也没有把它们绑定到本机当前固件。

因此，夹爪协议、供电、零点、行程、夹持力/力矩、ACK、STOP 和反馈合法性均保持 `BLOCKED`。

## 官方 Git 仓库离线审计限制

只读快照 HEAD 为 `13185838263047c885552e56d715051c2f1612cc`。本地可解析的相关远端
引用包括：

```text
origin/AtomVersion          95976bae3b3112121071f82a938a21dd821f9f68
origin/basic                d25eb179a86592eed327c6bc65638a8460a4b8db
origin/modify-mycobotbasic  1287d621cf6d8638d85e3666dfdc543ecfba5f6d
origin/master               bf24f79e4d9dc6d54bfb8788ce2f5b2e3a5842b4
origin/main                 13185838263047c885552e56d715051c2f1612cc
```

该快照是 promisor/部分克隆；相关 `CommunicateDefine.h` 与 `setGripper.ino` blob 没有落到本地。
一次 `git show` 因 Git 尝试补取缺失 blob 而在连接 GitHub 前失败，未取得源码、未改动任何本地或
现场状态；随后已用 `GIT_NO_LAZY_FETCH=1` 确认 blob 本地缺失并停止联网尝试。故本次不能把
这些分支当作已核验的 AtomMain 实现证据，也不能从缺失源码推导协议不存在。

## 最小现场/厂商资料清单（再次接线前）

以下资料必须绑定到这台控制器、Atom 固件、原厂电机和当前机械总成；只有通用产品页或旧手册
仍不足以放行：

1. MyStudio 精确版本，以及它对这台 myCobot 280 M5 显示的 Basic 固件名称、版本、目标型号和
   推荐固件包 ID；只记录信息，不执行 Burn。
2. 当前 AtomMain 的精确名称/版本/构建 ID，以及厂家对该 Basic/Atom/pymycobot 组合的兼容
   声明；不能以“最新版”代替可复现版本。
3. 原厂控制器与电机的厂家部件号、硬件 revision、固件 revision，或厂家支持工单中对无铭牌
   部件身份的书面绑定。
4. 夹爪线的点到点针脚/线色表，明确是否同时承载电源与通信；额定/绝对电压、启动/持续/峰值/
   堵转电流、极性、保险/限流、热保护和禁止热插拔要求。
5. 与本机固件绑定的 `0x65/0x66/0x67/0x69`（以及任何 type 扩展）精确 TX/RX 帧、合法长度、
   字段、范围、错误码、校验、ACK/NAK、超时、重启和乱序处理。
6. 可独立于普通命令通道执行且有完成证据的 STOP/去能方式；若 transport 不能独立停止，必须
   提供外部物理能量隔离方案，软件不得报告 STOP 成功。
7. 冻结的原厂保留件 BOM 与 CAD revision，包括电机输出方向、齿轮比、相位、硬限位、过中心
   位置、空载安全中位和机械干涉图。
8. 行程和力验收的测量方案：外部开度量具、测力计/称重装置、仪器量程/精度、固定方法、批准
   阈值与原始记录格式。矿泉水瓶不掉落只能是功能演示，不能代替力矩或夹持力标定。

在上述资料闭合前，下一步仅限离线解析资料、CAD/BOM 对照、pure-fake 契约和诊断方案设计；
不提供或执行下一条真实夹爪命令。

## 根因排序（未封存）

1. `pymycobot 3.3.4` 显式 type 扩展帧与当前 Atom 固件协议变体不兼容。
2. 夹爪端点/位置反馈校准漂移或首次上电状态失配。
3. 原厂电控与新齿轮/连杆机构的方向、比例、硬限位或过中心关系不匹配。
4. SDK 弱接收校验下的畸形/错位响应被接受为位置 `105`。

现有证据不能在上述四项中唯一归因。

## 力与验收结论

- AG 产品页的 `150 g` 是原厂成品夹持力规格，不是当前 API 中已验证的可调力矩设定值；约为
  `1.47 N`，且不能自动继承到新齿轮/连杆机构。
- `set_HTS_gripper_torque` 是 HTS 命名接口，未证明适用于本 AG；`protect_current` 也不是经过
  标定的夹持力控制。二者均不得用于现场试错。
- 在位置映射尚未闭合时，不得进入夹瓶、逐步加力、全行程、归零或校准验收。

## 重新进入任何现场动作前的门槛

1. 厂商确认当前 Atom/Basic 固件版本对应的 `0x65/0x67/0x69` 精确帧格式、合法反馈范围和
   可独立执行的停止/去能方法。
2. 冻结原厂控制器/电机保留 BOM、CAD revision、齿轮比、方向、相位、硬限位和过中心位置。
3. 建立只捕获 raw TX/RX、不会自动发动作的受控诊断方案；不得用真实运动试探协议。
4. 先证明可信静止、位置反馈合法和命令—反馈相关性，再单独申请新的、一次性动作授权。
5. 力验收必须使用外部测力计/称重装置和批准阈值；矿泉水瓶“没有掉”不能代替力标定。
