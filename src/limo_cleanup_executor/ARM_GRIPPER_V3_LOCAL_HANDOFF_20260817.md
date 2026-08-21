# 机械臂与夹爪 V3 本地软件交接（暂停点）

日期：2026-08-17
状态：本地定向修复可测试；evidence authority、ROS1 现场兼容与真实执行器能力继续 `BLOCKED`。

## 2026-08-18 AG 首次动作异常增量

- 操作员确认接入的是原厂 AG 控制器/电机与新机械机构的混合工具；这与当前 manifest 中
  `COMPLETE_REPLACEMENT`、`legacy_ag_components_retained=false` 冲突，工具身份尚未冻结。
- 在一次性授权下，现场仅调用一次 `set_gripper_value(26, 10, 1)`。动作前反馈为 `25`、
  `moving=0`；随后现场观察夹爪运行至最大开度，约 1.3 秒后反馈为 `105`、`moving=1`。
- 该事件定级为 `FAIL_POSITION_MAPPING_UNBOUNDED` 和 `MOTION_UNRESOLVED`，不是端点、行程、
  静止、ACK 或校准成功证据。操作员随后报告已拔下夹爪线；不得重新插接或继续动作试错。
- exact `pymycobot 3.3.4` 离线审计证明显式 `gripper_type=1` 发送
  `FE FE 05 67 1A 0A 01 FA`，而厂家 AG 底层资料只定义两参数
  `FE FE 04 67 value speed FA`。Atom 固件是否支持扩展帧未知；SDK 又不会校验反馈 `0..100`
  范围、footer 或 checksum。`command_return=None` 是 fire-and-forget，不是 ACK；`close()`
  也只关闭串口，不是 STOP。
- 根因仍可能是固件/帧变体不匹配、端点校准漂移、新机构方向/比例/硬限位失配或畸形响应。
  未取得厂商帧确认、冻结 BOM/CAD 与独立停止能力前，真实 backend、归零、校准、全行程和
  夹瓶加力均保持 `BLOCKED`。
- 完整原始输出、源码哈希、协议差异和重新进入门槛见
  `docs/evidence/ARM_GRIPPER_AG_FIRST_MOTION_INCIDENT_20260818.md`。

## 2026-08-18 两份旧版官方手册审计增量

- 已只读核对《myCobot 开发引导手册 V20210112》（SHA-256
  `5D4F2999C2AA7A04C3BA588949FF86691502630F801302D1B10B0180E2148A11`）和《myCobot
  用户手册 V20201231》（SHA-256
  `A51565C2B55AECA21F4888B17F469C5B818D8B75416943A341C363279F7F87F2`）。
- 开发指南只证明当时 Basic `transponder` / Atom `atomMain` 的 115200、8N1、
  `FE FE LEN CMD ... FA` 框架及旧 `0x66 + state`/`setGripper(0/1)` 表面。它没有给出
  当前 `0x65/0x67/0x69`、`gripper_type`、力矩、电流、校准、独立 STOP 或 ACK 契约。
- 用户手册的上电、关节使能、J1--J6 校零/测试和 Atom 固件恢复都针对当时机械臂本体；不得
  用作当前自定义舵机--齿轮--连杆夹爪的归零、行程、力矩、供电或停止步骤。
- `8V/5A`、`5V@500mA`、`4.8--7.4V`、`1.5 kg·cm`、J1--J6 零点 `2048` 和
  `setGripper(0/1)` 全部禁止外推为当前夹爪参数或命令。
- 手册未记录某扩展并不证明扩展不存在；准确结论是手册不足以授权或判定扩展，也不绑定本机
  当前 Basic/Atom 固件和 `pymycobot 3.3.4`。
- 官方 Git 本地快照是部分克隆，相关分支源码 blob 未落盘；离线审计只能记录 refs，不能宣称
  已核验分支实现。一次缺失 blob 补取在网络连接前失败，此后已禁止 lazy fetch，未改动现场状态。
- 再次接线前必须取得：MyStudio 版本、Basic/AtomMain 精确版本/构建 ID 与兼容矩阵、控制器/
  电机身份、供电和针脚规范、精确帧与合法反馈范围、独立 STOP/物理隔离能力、冻结 BOM/CAD/
  齿轮比/方向/硬限位，以及外部量具和测力方案。上述项目仍全部 `BLOCKED`。

## 现场硬边界

- 机械臂和夹爪绝对不动。
- 禁止枚举、访问或打开执行器端口；禁止连接、上电、使能、回零、探测或发送动作。
- 禁止加载真实 backend、连接 ROS graph、SSH/网络或厂商 runtime。
- 软件 STOP 不能替代现场物理急停、断电或独立安全通道。
- 本轮收口仅运行本地静态、编译、isolated runner 与 pure-fake 测试；未进行任何设备、ROS、网络或实体访问。

## 已完成的代码安全修复

- arm/gripper core 保持 fail-closed：STOP、epoch/generation、迟到结果隔离、`motion_unresolved` 与 `physical_stop_required` 持久锁存路径已建立；真实 backend 仍禁用。
- 真实 arm backend 不允许默认动态 import/open；缺少显式注入和可验证 bounded-call/独立 STOP 能力时保持 `DISABLED/BLOCKED`。
- 已修复 unittest isolated runner 中嵌套 Python 子进程无法导入固定 package root、以及子进程可能写 workspace bytecode 的问题。作用域内只注入固定 import roots、`PYTHONDONTWRITEBYTECODE=1` 和 `PYTHONNOUSERSITE=1`，退出时验证并恢复原环境。
- evidence generator 已加入 host-owned same-FD runner bootstrap：对固定 runner 使用 `O_NOFOLLOW`、同一文件描述符读取、SHA-256 校验后再 compile/exec，阻断 runner 路径 `X→Y→X` ABA 替换。
- runner 报告中的实际 `workspace_source_reads` 与 host source identity 机械绑定；target 实际 loader bytes 不一致时拒绝。static audit scope 也必须与 exact source identity map 一致。
- ROS smoke 继续只允许 `STATIC_AST_NOT_EXECUTED_ROS_GRAPH_PROHIBITED`，不能记为 PASS；ROS2/Foxy 只属于 offline/legacy，不能证明 ROS1/Noetic 现场兼容。

## 当前可核验测试

使用 bundled Python：

`C:\Users\DYH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`

结果：

- generator isolated contract：10 passed / 0 failed / 0 skipped。
- aggregator isolated contract：37 passed / 0 failed / 0 skipped。
- arm persistent safety latch：36 passed / 0 failed / 2 skipped；skip 原因为当前平台不提供 directory/file symlink 能力。
- gripper persistent safety latch：31 passed / 0 failed / 0 skipped。
- arm/gripper 本地静态门：82 files，Python 3.8 AST 47/47，in-memory compile 47/47，static/text/ordinary-lock violations 0/0/0。

这些结果只证明当前本地软件定向门，不是 field、release、delivery、ROS1 或硬件 PASS。

## Evidence authority 尚未完成

- `audit_tools/arm_gripper_local_evidence_aggregator.py` 中 expected policy SHA 仍为全零 sentinel，expected source closure 仍为空；这是有意的全局 fail-closed 状态。
- `audit_tools/arm_gripper_local_v3_policy.json` 尚未冻结/生成。
- aggregator 成功路径仍 `fail-closed` 且尚未封存；23 target exact case-map、完整 skip 分母、source closure SHA、producer/runner/raw-output binding 尚未做最终全量验证。
- 未生成 candidate 或 final evidence。历史 524/519/5 只可保留为 `STALE_NOT_RELEASE_EVIDENCE`。
- generator same-FD ABA 核心防护及当前合成置换/绑定定向门已经通过；但“真实执行期文件替换”的并发负测尚未实现，必须作为未来 evidence-integrity 增强项，不能用现有定向门替代。

## 剩余阻塞

- 固定 4-suite/23-target authority、exact case-map、exact source closure 与 policy raw SHA。
- 完成并红队复核 aggregator host-owned reservation、same-FD generator 启动、producer stdout/stderr/RC、suite/raw inventory 与 source-before/after 的独立验证。
- 运行 23 target 全量并分别统计 passed/failed/skipped；required skip 必须保持 readiness `BLOCKED`。
- ROS1/Noetic `rospy/actionlib` adapter、ownership/schema/进程清单仍缺失；ROS2 测试不得提升为 Noetic 兼容证据。
- 新夹爪的准确型号、厂商资料、通信协议、额定电压/电流、行程、力/速度范围、反馈/故障码、独立停止能力及机械安装/TCP 数据仍需资料或现场测量。已被证实错误的 AG 参数不得复用。
- 未经后续动作级明确授权，不验证真实端口、backend、STOP 能力或任何机械动作。

## 新夹爪接入后的恢复入口

仅在用户明确发送“新夹爪已接入/继续”后恢复本任务。恢复顺序：

1. 先只读核对本文件、相关源文件身份和工作树，保留用户改动；仍不访问端口或 ROS graph。
2. 先离线登记新夹爪型号、datasheet、协议、额定电气参数、机械接口和需要现场测量的未知项；旧 AG 参数保持 fail-closed。
3. 只在 fake backend 中补新型号的 manifest/config/协议契约与限位、超时、STOP、错误恢复负测。
4. 再恢复 evidence policy/closure 与 23 target 本地全量，生成的证据仍只能是 local-offline evidence。
5. 如果后续确需连接、上电、使能或动作，必须在动作前另列具体动作、速度/力限值、物理急停/断电条件与现场人员要求，并等待当次动作级明确授权。

## 本轮涉及的本地文件

- `audit_tools/arm_gripper_local_evidence_aggregator.py`
- `audit_tools/arm_gripper_local_evidence_generator.py`
- `audit_tools/test_arm_gripper_local_evidence_aggregator.py`
- `audit_tools/test_arm_gripper_local_evidence_generator.py`
- `audit_tools/run_unittest_file_tests.py`
- `audit_tools/run_pytest_style_tests.py`
- `audit_tools/arm_gripper_local_static_audit.py`

暂停条件已满足：不再继续 policy、23 target 或 evidence 生成，等待用户明确恢复指令。
