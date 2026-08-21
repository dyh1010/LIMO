# V3 空矿泉水瓶抓取投送架构与分级验收

初版日期：2026-08-11；本次夹爪/现场门禁更新：2026-08-13
机械臂：myCobot 280 M5
末端工具：原 `mycobot_gripper_ag` 或完整替代夹爪候选，尚待正式选型/冻结
当前状态：只读本体通信已有证据；夹爪、几何、动作和闭环均未放行。

## 最终动作定义

V3 只处理经批准的空矿泉水瓶，首版限定固定拾取区、固定垃圾桶停靠点和固定释放体积：

```text
识别桶外空瓶
  -> 冻结目标并重检测
  -> 导航到预抓取站位
  -> 底盘锁止
  -> 规划并到达预抓取位姿
  -> 低速夹取
  -> 抓取验证
  -> 收回批准运输姿态
  -> 低速运输到垃圾桶 waypoint
  -> 底盘锁止并确认 bin_frame
  -> 到桶口上方预释放/释放位姿
  -> 打开夹爪自由释放
  -> 释放结果确认
  -> 撤回并结束任务
```

投放只允许在桶口上方打开夹爪自由释放，禁止投掷、甩臂或利用底盘惯性。首版禁止底盘与
机械臂同时运动；失败默认停止并转人工，不自动重抓、不自动重复释放。

## 已证实的机械臂与旧 AG 历史基线

- 机械臂：myCobot 280 M5；
- 稳定设备：`/dev/elephant`；VID:PID `1a86:55d4`；SN `5B09024480`；`115200`；
- Python 库：`pymycobot 3.3.4`；
- M5 必须保持 `Transponder / USB UART`，屏幕出现 `connect test atom ok`；
- 本体核心只读查询连续三轮 `9/9`，`controller=1`、`power=1`、`error=0`；
- 原厂 `mycobot_follow/follow_display` 会扫描串口并调用 `release_all_servos()`，永久禁止；
- 旧夹爪型号为 `mycobot_gripper_ag`、查询类型 `1`，当前物理断开；
- 旧 AG/Atom 链路中的历史 `get_gripper_value(1)=255` 表示 INVALID/DISCONNECTED，绝非
  “全开”。该 `255` 语义、`gripper_type=1`、`set/get_gripper_value` API 和 `0..100` 范围只
  属于旧硬件历史基线，不能自动继承给完整替代夹爪候选。

以上证据只证明本体只读通信。当前未连接机器人、未访问串口、未启动 ROS 节点，也未动作
机械臂或夹爪。

## 夹爪机械版本与 CAD 候选

`C:\Users\DYH\Desktop\v1gripper` 的最终只读审计将其判定为**新的完整替代夹爪候选**，
不是纯外壳，也不能认定为 AG 安装适配件或“保留原 `mycobot_gripper_ag` 执行器”的改装件。
零件集合包含自身舵机、舵机盒、齿轮/舵盘齿轮、连杆、双指爪、机架板、轴承和紧固件，但
没有 AG 原执行器保留件对应表。

精确资产快照：

- 初始：87 个文件＝1 SLDASM + 33 SLDPRT + 19 STEP + 34 个 4-byte 锁文件；
- 2026-08-11 审计结束：34 个 CAD 文件＝1 SLDASM + 33 SLDPRT，0 STEP、0 锁文件；
- 2026-08-13 当前目录：35 个文件＝1 SLDASM + 33 SLDPRT + 1 `Macro1.swp`，0 STEP、
  0 PDF/BOM/协议/电气资料文件；
- 当前 `齿轮箱.SLDASM` 为 2,035,041 bytes，SHA-256
  `D5F513C69B3590378791CFEC8E0853567F8377676429772ED7E38D1653E94D98`；该值不同于
  2026-08-11 归档记录，必须作为新修订重新导出、审阅和冻结；
- 初始 STEP 在用户外部 CAD 会话变化后缺失，原因只记录为未知；审计任务没有删除、移动、
  复制、恢复或保存源文件；
- SolidWorks 只读 COM 因 `TYPE_E_ELEMENTNOTFOUND` 未取得装配树，没有强制解锁或干预会话。

权威报告：

- `GRIPPER_MODEL_AUDIT_FINAL_2026-08-11.md`
- `GRIPPER_MODEL_SOURCE_INVENTORY_2026-08-11.md`
- `GRIPPER_MODEL_AUDIT_PROGRESS_2026-08-11.md`

后续另有同级派生导出目录 `gripperstl`。用户曾明确授权“把重复的都去掉”，专项将 3712 个
重复 STL 移入同级可恢复 quarantine；主窗口一度因缺少该上下文将其恢复，随后依据原 CSV
纠正。最终 `gripperstl` 顶层/递归均为 116 个 STL、0 子目录、`19622044 bytes`；quarantine
为 3712 个 STL、32 个目录、`639534508 bytes`；全量 SHA mismatch `0`，原生 `v1gripper`
CAD 未改。该事件不证明保留 STL 具备正确 link 划分、装配变换、关节轴、极限或碰撞语义，
也不关闭 V3-2.5。今后任何新的源/导出文件移动、删除、重命名或恢复都需重新取得用户明确授权。

保留集已做隔离 ROS 资产暂存：Desktop `gripperstl` 顶层/递归 116 个 STL、0 子目录、
`19622044 bytes`，与 keep manifest 的 filename/bytes/SHA 全匹配；116 个复制件和 3 份清单
位于 `new_gripper_ros_assets/v1gripper_description_staging/source_exports/
frozen_stl_2026-08-11`，总计 `392246` triangles，解析/hash/size/triangle 全 PASS。当前单位
`UNVERIFIED`，source_exports 未安装，URDF/Xacro 引用 0、visual/collision 0。staging gate
PASS；release gate 因缺已 REVIEWED 的 `export_manifest.json` 按预期 BLOCKED。这个暂存只证明
复制件完整性，不证明尺度、link 语义、关节、TCP、碰撞或装机可用。

配套只读准备文档与配置位于：

- `C:\Users\DYH\Desktop\limo_graphtest\MYCOBOT_V3_READONLY_PREPARATION_2026-08-11.md`；
- `C:\Users\DYH\Desktop\limo_graphtest\limo_cleanup_hardware\config\manipulation_v3_readonly.yaml`。

配置固定 `UNIT=UNVERIFIED`、`scale_to_m=null`、CMake/URDF refs 0、visual/collision=false、
release BLOCKED，14 个未决接口字段均为 null；R0～R9 与 62 个现场 checkbox 均未放行。
本地 35/35 单测与静态检查通过，WSL Python 3.10.12 + PyYAML 5.4.1 动态 safe_load 为
`MANIPULATION_V3_YAML_SAFE_LOAD_PASS`；schema、整数、有限 AABB/min<max、refs 0、
visual/collision=false、legacy 隔离、geometry 全 false、profile/candidate
`permit_motion=false` 均断言通过。这些门只用于确保未知字段 fail-closed，不关闭 V3-1/
V3-2/V3-2.5/V3-3 或 release。

当前没有可用的完整中性装配、经验证的 ROS link mesh/URDF/Xacro、组件变换、配合、齿轮比、
关节轴、极限配置或法兰接口受控图，因此状态为
`COMPLETE_REPLACEMENT_GRIPPER_CANDIDATE_NOT_REVIEWED`。
不得沿用原 AG 的 100 g、20～45 mm、TCP、控制映射或载荷结论。

若最终产品仍要求 `mycobot_gripper_ag`，该候选不能直接冒充 AG；若真实设计意图是保留 AG
内部执行器，必须提交冻结修订、BOM、装配剖视和原厂件保留对应表。若改用完整替代夹爪，
必须建立新的工具型号/修订号、驱动、反馈和验收配置。在任一路径冻结前不得进入 V3-2.5
几何、TCP 与碰撞阶段。

当前也没有 myCobot 280 末端法兰或夹爪安装件受控图，孔距、孔径、定位台阶、安装面法向、
防转、啮合长度和线缆出向均未知；文件名中的“法兰型轴承”不是安装法兰证据，`M5` 是机械臂
型号而不是螺纹兼容证据，禁止安装放行。

现有 `gripper_core.py` 使用旧 AG 假设下的 `0..100` 线性插值，当前不得用于替代夹爪。只有
最终协议本身确认为 `0..100` 标量时，才实测 `0,10,...,100` 到净开口的标定表；若协议不同，
必须建立对应的原生标定表。任何路径都不得假定线性，必要时使用分段插值，并记录方向、机械
硬限位、部分闭合夹持值和重复性。

## 单一命令所有权与底层 transport 所有权

V3 上层必须只有一个 manipulation coordinator/命令 owner，统一排序底盘锁止、机械臂动作、
夹爪动作、验证和故障恢复。底层硬件所有权取决于最终工具选型：

1. **保留原 AG/Atom 链路**：只有 BOM、装配和电气证据证明继续使用原 AG 时，才允许一个
   MyCobot hardware gateway 独占 `/dev/elephant` 并统一机械臂与夹爪；
2. **完整替代夹爪**：arm gateway 独占 `/dev/elephant`；新夹爪使用独立且唯一的受控
   transport owner。新执行器型号、额定电压/峰值电流、控制器、PWM/串口/CAN/其他通信、
   位置/电流/力反馈和断能状态当前全部未知，不能猜测为 MyCobot API。

无论选择哪种底层结构，gateway 必须提供：

- 新鲜的控制器、供电、错误、关节、位姿和夹爪状态；
- 有界的 arm pose/named-pose 动作；
- 夹爪单次开合命令与合法反馈；
- 显式串口打开/关闭、设备身份、占用和 Transponder fail-closed 检查。

当前 `PymycobotGripperBackend` 已退役为永久 fail-closed 占位符：构造即拒绝，注入的 factory
也不会被调用；它不再包含旧 AG 设备路由、执行器选择、`0..100` 映射或可执行的
command/read/STOP/close 协议方法。ROS controller 也不能构造它，因此不会形成已发布的真实
设备路径。generic arm STOP 不能冒充夹爪 STOP。它不得用于现场探测、完整替代夹爪或任何
真实动作。最终实现仍必须补齐设备身份、唯一 owner、协议反馈和经过验证的
STOP/fault/ACK 契约。

目标数据流：

```text
task_manager
  -> V3 cleanup executor
     -> target freeze / redetection / grasp pose planner
     -> ROS2 高层导航适配 -> ROS1 Noetic 底盘唯一 owner
     -> 单一 manipulation coordinator
        -> arm gateway（sole /dev/elephant owner）
           -> fresh arm state
           -> bounded arm named-pose/action
        -> gripper gateway
           -> 原 AG：仅在证据充分时复用 MyCobot gateway
           -> 替代夹爪：独立且唯一的受控 transport owner
     -> grasp verifier
     -> drop verifier
```

## 几何、标定与碰撞门

进入动作前必须完成：

1. 在最终安装下复核 `base_link -> camera_link`；
2. 三次独立测量 `base_link -> arm_base_link`，达到 `REVIEWED` 前禁止发布该 TF；
3. 最终夹爪装好后标定 `arm_flange -> gripper_tcp` 六自由度，TCP 位于真实夹持中心；
4. 至少 5 个工作区标定点验证
   `camera_color_optical_frame -> arm_base_link` 的端到端误差和时间戳对应，不能只证明静态 TF
   可相乘；
5. 标定 `map -> bin_frame`、`bin_drop_base_pose`、`pre_release`、`release`、`retreat` 和允许
   释放体积；垃圾桶移动、定位失效或 TF 过期立即 BLOCK；
6. 碰撞模型覆盖 LIMO 车体/履带/上层板、安装板、机械臂连杆、最终夹爪开闭和扫掠包络、
   最大批准瓶型、线缆、相机、地面、桶壁与桶沿；
7. 建立关节、速度、加速度和工作空间软限位；
8. 冻结唯一批准运输 named pose：机械臂和瓶子收进车体包络、线缆无拉扯、关节不近限位。

只有确认到达运输姿态且持瓶证据仍有效后，底盘才允许运动。

## 抓取与释放证据

- 工具和 transport 冻结后先断电连接，再只读确认连续合法反馈；若选择旧 AG 链路，`255` 必须
  始终按 INVALID/DISCONNECTED 阻塞；若选择替代夹爪，合法/非法值必须按新协议重新定义；
- 单独动作授权下，以最低速验证开合方向、机械安全范围、非线性开口映射和部分闭合夹持值；
  每次闭合只发一次；
- 抓取成功至少使用两类独立证据：合法夹爪开度/电流/力反馈，以及小幅验证抬升后的视觉随动
  与无滑落；单纯“position verify”或命令返回成功不能证明抓住瓶子；
- 运输期间持瓶证据丢失时立即停止底盘并转人工恢复；
- 释放后使用专用 `drop_verification`，确认瓶已离爪且位于桶内；当前 actionable detection 会
  过滤桶内瓶，不能用“`/cleanup/detection` 没目标”作为释放成功；
- `error != 0`、TF/目标过期、IK/碰撞失败、夹爪协议非法反馈、`bin_frame` 无效或 owner 不唯一
  均 fail-closed；旧 AG 的 `255` 属于协议非法反馈。禁止自动 `power_on`、`clear_error`、夹爪
  init/校准、重抓或反复开合。

## V3 分级验收

前一级未通过，后一级禁止开始。

### V3-0 纯软件 / dry-run

- 完整状态机、取消、超时和故障注入；
- 夹爪协议非法反馈（旧 AG 包括 `255`）、TF 缺失/过期、目标过期、错误 owner、IK/碰撞失败
  全部 BLOCK；
- 不打开串口，不发布机械臂、夹爪或底盘硬件命令。

### V3-1 最终工具、执行器与通信架构冻结

- 冻结使用原 AG 还是完整替代夹爪；任一路径未冻结前，不得开始工具 TCP、质量惯量或碰撞
  包络验收；
- 若保留 AG，提交 BOM/剖视/原厂件保留表并证明 Atom/MyCobot API 链仍适用；
- 若使用替代夹爪，确认执行器型号、固件、电压/峰值/堵转电流、保险/限流、控制器、连接器、
  引脚、电平、通信帧/CRC、反馈、watchdog、断能和唯一 transport owner；
- 明确电源、保护地、急停/断能、线缆、故障状态和上下电顺序；未通过时所有真实 gripper
  backend 保持禁用。

### V3-2 安装、供电方案与机械臂只读

- 最终安装、紧固、拟用供电、接地、线缆和断能方案记录；
- M5 保持 Transponder；机械臂本体新鲜状态、arm gateway 唯一 `/dev/elephant` owner；
- 夹爪 transport 保持断开/禁用，只允许另行授权且证明非使能的被动只读阶段；
- 主开关是否能切断各独立危险能量必须实测；软件 STOP 不得替代物理急停或断能。

### V3-2.5 几何、TCP 与碰撞

- 外参、gripper TCP、`bin_frame`、停靠/释放姿态、多点端到端误差和完整包络全部
  `REVIEWED`；
- CAD 工具修订号、质量、质心、惯量、开闭/扫掠包络冻结。

### V3-3 夹爪独立

- 先完成所选协议的连续合法只读反馈，再做无瓶最低速开合、非线性标定和空瓶部分闭合；
- 第一次无瓶动作需要夹爪专用、当次、一次性授权；机械臂授权、历史授权或只读授权均不能
  复用；
- 冻结夹持电流/力上限，以及瓶径或壁面允许变形的毫米值和百分比；这些阈值当前为
  `TBD_MEASURED`，屈曲、开裂、刺穿或泄漏必须为 `0`；
- 建议 10 次持续持瓶与 20 次抓放；协议非法反馈（旧 AG 包括 `255`）、卡滞、重复命令和
  超限均为 `0`。

### V3-4 机械臂空载

- 第一次机械臂动作需要与夹爪分开的、当次、一次性授权，只覆盖一个明确的最低风险有界
  命令；
- 底盘固定；预抓取、抓取、验证抬升、运输、预释放、释放、撤回 named pose 各至少 10 次；
- 碰撞、限位、拉线和错误均为 `0`。

### V3-5 固定底盘：瓶到固定桶

- 建议 20 次中至少 19 次完整成功；
- 碰撞、桶外释放、停止失败、自动重抓和重复释放均为 `0`。

### V3-6 运输

- 先空载后持空瓶，至少 10 次低速运输无滑落；
- 未到批准运输姿态、持瓶证据不新鲜或机械臂未锁定时，底盘必须硬阻塞。

### V3-7 完整闭环

- 批准范围内连续 20 次至少 19 次功能成功；
- 安全绕过、碰撞、非预期运动、掉瓶后继续行驶和错误桶位释放必须为 `0`。

## 现场上下电、负向验证与证据记录

每个现场阶段必须逐项填写
`arm_gripper_field_acceptance_matrix.md` 的 staged power checklist、negative
acceptance matrix 和 field evidence record。最低要求包括：

- 断能状态下核对授权范围/有效期、人员职责、硬件 serial/revision、BOM/CAD/source/config
  hash、保护地、保险/限流、极性、接头固定、应力释放和唯一 transport owner；
- 从 actuator torque/enable 禁用和供电输出关闭开始；若设计支持，先仅上 controller logic，
  记录浪涌/空闲电流并确认零意外动作，再进行被动状态读取；
- 下电时先撤销命令授权，按受控顺序移除 actuator 与 controller 能量，确认静止和残余电压/
  电流，再释放 transport owner；API/STOP 返回不能替代物理确认；
- 离线覆盖 watchdog 丢失、CRC/帧错误、陈旧/重复/乱序样本、controller restart、掉电/断链、
  STOP 失败/超时、ACK 竞态、非法反馈和 owner 变化；硬件重复仅限协议证明不会引起运动且有
  单独现场授权的条件；
- 每次记录日志路径及归档 hash、ROS domain、session/boot/authorization/command/action ID、
  开始结束时间、STOP/静止/ACK 证据、异常处置、前后进程/端点/owner 差异、最终能量状态和
  safety lead/operator/observer 签名。

## 建议实现切面

- 接口：`GraspTarget`、`BinReleaseTarget`、`GripperState`、`ControlArm` action，并扩充
  `ExecuteCleanup` / `ControlGripper` 的结果证据；
- 模块：`manipulation_core.py`、`grasp_pose_planner.py`、
  `mycobot_manipulation_driver.py`（arm 唯一 `/dev/elephant` owner）、按最终工具选型实现的
  `gripper_transport_driver.py`、`pick_place_executor.py`、`grasp_drop_verifier.py`；
- 配置：`mycobot_v3_safe.yaml`、`manipulation_geometry.yaml`、`v3_pick_place.yaml`；
- 启动/验收：`mycobot_v3_readonly_acceptance.launch.py`、`v3_pick_place.launch.py`、
  `manipulation_readiness_check.py`；
- readiness 必须检查 arm 稳定身份、Transponder、`error=0`、所选夹爪协议反馈合法（旧 AG
  路径额外要求非 `255`）、几何 `REVIEWED`、TF/目标新鲜、底盘锁止、动作端点和 transport
  owner 唯一；
- V3 首版在 task manager、language 与 perception 三处统一只允许空 `plastic_bottle`，不得
  继续放行 can、paper 或 generic 目标。

## 当前硬阻塞

- `COMPLETE_REPLACEMENT_GRIPPER_CANDIDATE_NOT_REVIEWED`
- `GRIPPER_MECHANICAL_REVISION_NOT_FROZEN`
- `GRIPPER_DISCONNECTED`
- `GRIPPER_ACTUATOR_AND_TRANSPORT_UNKNOWN`
- `MANIPULATION_COORDINATOR_NOT_IMPLEMENTED`
- `ARM_GATEWAY_SOLE_ELEPHANT_OWNER_NOT_IMPLEMENTED`
- `REAL_GRIPPER_BACKEND_NOT_IMPLEMENTED_PENDING_TOOL_SELECTION`
- `ARM_BASE_EXTRINSIC_UNMEASURED`
- `GRIPPER_TCP_UNCALIBRATED`
- `BIN_FRAME_AND_RELEASE_VOLUME_UNCALIBRATED`
- `IK_COLLISION_AND_TRAJECTORY_BACKEND_NOT_READY`
- `GRASP_VERIFICATION_NOT_READY`
- `DROP_VERIFICATION_NOT_READY`

任一状态未关闭前，V3 真实动作保持禁止。
