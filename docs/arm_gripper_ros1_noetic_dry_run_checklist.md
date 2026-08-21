# 机械臂与夹爪 ROS1 Noetic dry-run 基线与验收清单

审计日期：2026-08-14

当前结论：`BLOCKED_NO_ROS1_ARM_GRIPPER_ADAPTER`

适用范围：本地源码、文档、pure-fake 和未来隔离 Noetic dry-run；不授权连接、上电、使能或动作。

## 2026-08-19 固定瓶位 preview 增量

`ros1_overlay_src/limo_cleanup_ros1_manipulation` 现已提供 Catkin/`rospy` 形态的固定瓶位抓取
preview 包。它订阅 ROS1 `limo_cleanup_ros1_perception/PerceptionFrame`，只发布
`/cleanup/manipulation/pick_preview` JSON，不创建 arm/gripper Action client、Service proxy、
厂商 backend 或设备 transport。输出始终为 `execution_permitted=false`。

这关闭的是 ROS1 消息适配和五阶段预览缺口，不是本节所指的真实 arm/gripper gateway 缺口。
因此标题结论仍为 `BLOCKED_NO_ROS1_ARM_GRIPPER_ADAPTER`。当前提交的 policy 故意把固定瓶位、
工具姿态、TCP 抓取偏移、预抓取/抬升高度和 workspace 保持为 `null`；这些字段未实测前，preview
节点也会在加载 policy 时 fail-closed。

夹爪参数只绑定操作员提供的 `gripper_safe.yaml` SHA-256
`62508BEA0CB96817099DC8EFDE10FEB034CAD7A844A95FEFDD29A3F57A6BBD18`。节点要求显式传入
该文件路径并比较实际字节哈希；只在 policy 中自报相同字符串不足以通过。操作员批准的持续保持
成功定义在 pure-fake 中固定为：`moving=true`、反馈 `18..20`、瓶子已夹紧、无异响、无过热且
无 fault。该定义不改变 preview-only 和真实执行继续 blocked 的边界。

## 1. 本文安全边界

本文只定义缺口和未来的 fail-closed 验证方法。本轮没有启动 ROS、Catkin、`roscore`、
`roslaunch` 或 ROS graph，没有加载厂商 runtime/backend，没有建立 SSH/目标机连接，没有枚举、
检查或打开任何执行器、串口或 USB 路径，也没有发送 Action、Service、回零、校准、清错、使能、
机械臂或夹爪命令。

后文出现的 Noetic 构建、回调和进程步骤均为未来清单，不是当前执行授权。未来执行也必须满足：

- 只在本地、隔离、fake-only 环境运行；
- 不 source 厂商 overlay，不导入厂商库，不启动厂商节点；
- 不配置、不探测、不打开任何硬件 transport；
- 不向真实 Action/Service endpoint 发送请求；
- 软件 STOP 不得被表述为物理急停、断能或真实静止证据。

## 2. 当前仓库真实基线

### 2.1 现有实现是 ROS 2/Foxy 形态

| 组件 | 当前事实 | Noetic 判定 |
| --- | --- | --- |
| `src/limo_cleanup_executor` | package format 3、`ament_python`、`rclpy`；gateway 使用 ROS 2 `ActionServer`、`ReentrantCallbackGroup`、`MultiThreadedExecutor` | 不能直接由 Catkin/Noetic 构建或启动 |
| `src/limo_cleanup_interfaces` | `ament_cmake` + `rosidl_generate_interfaces` | 没有 Noetic `message_generation`/`actionlib_msgs` 产物 |
| `src/limo_cleanup_bringup` | `ament_python`、ROS 2 Python launch、`launch_ros` | 没有 ROS1 XML launch 或 Noetic 参数装载规则 |
| arm/gripper YAML | 使用 ROS 2 `ros__parameters` | 不能作为 ROS1 参数文件直接使用 |
| arm/gripper dry-run launch | ROS 2 Python launch；只允许 `backend=dry_run` | 不是 `roslaunch` 证据 |
| `arm_gateway_node.py` / `gripper_gateway_node.py` | `rclpy` gateway，显式 dry-run-only | 不存在 `rospy`/`actionlib` adapter |
| `gripper_controller.py` | 旧 ROS 2 `ControlGripper` 集成 fixture；没有独立 STOP/ACK | 不得作为 Noetic 或最终夹爪参考 adapter |
| `ros1_overlay_src` | 当前已有底盘、导航和 perception 相关 ROS1 包 | 没有机械臂、夹爪或 manipulation ROS1 包；其他 ROS1 包不能充当其 adapter |

当前 ROS 2 gateway 端点为：

| 机构 | Action | STOP | ACK | State |
| --- | --- | --- | --- | --- |
| arm | `/cleanup/arm/execute` | `/cleanup/arm/stop` | `/cleanup/arm/acknowledge_fault` | `/cleanup/arm/state` |
| gripper | `/cleanup/gripper/execute` | `/cleanup/gripper/stop` | `/cleanup/gripper/acknowledge_fault` | `/cleanup/gripper/state` |

接口源码包含 `ExecuteArmMotion`、`ExecuteGripperMotion`、`StopArm`、
`AcknowledgeArmFault`、`StopGripper`、`AcknowledgeGripperFault`、`ArmState` 和
`GripperState`。这些定义可作为语义参考，但当前生成物属于 ROS 2；不能把 ROS 2 类型支持、
QoS 或 smoke 结果当作 Noetic message/action/service 兼容证据。

### 2.2 可在 ROS 外复用的纯 Python 资产

下列资产适合作为未来 Noetic 薄 adapter 的共同内核候选：

- `arm_gateway_core.py`；
- `gripper_gateway_core.py` 与 `gripper_core.py`；
- `arm_motion_release_manifest.py`；
- `final_gripper_release_manifest.py`；
- `arm_safety_latch.py` 与 `gripper_safety_latch.py`；
- `arm_gripper_field_acceptance.py`；
- fake-only backends 和 ROS-free callback/state-machine 测试夹具。

复用的前提是 Noetic adapter 只做消息转换、调度和生命周期管理，不复制或削弱 core 的
session、authorization、command ID、epoch/generation、freshness、STOP、stationary、fault latch
和 ACK 判据。持久锁存文件 I/O、外部审批验证和其他可能阻塞的工作不得进入 core STOP 临界路径。

### 2.3 已有 Foxy 证据不能填补 Noetic 缺口

唯一目标 Foxy v3 记录是 `FAIL-before-build (status=2)`：runner 在 source Foxy 前检查 `ros2`，
因此 build、test 和 smoke 均 `NOT RUN`。后续本地 verifier 修复回归为 `60 passed / 1 skipped`，
其中跳过项是本机没有 `rclpy` 的 ROS smoke；该结果只证明本地源码门，不改变 v3 失败结论。

即使以后 ROS 2/Foxy 的 build、Action/STOP/ACK smoke 全部通过，也只能证明 ROS 2 适配层，不能证明：

- Catkin package/message/action/service 可生成；
- `rospy`/`actionlib` 回调、线程与 shutdown 语义正确；
- ROS1 queue/latch、时间、名称解析和参数加载与 ROS 2 等价；
- Noetic 进程所有权、清理或重启锁存正确；
- 任何真实 backend、transport、软件 STOP 或物理安全能力可用。

## 3. Noetic 交付缺口

以下任一项缺失，Noetic dry-run 都必须保持 `BLOCKED`：

1. 独立 Catkin 接口包，使用 `message_generation`、`message_runtime` 和 `actionlib_msgs`，生成与
   ROS 2 语义逐字段对应的 Action、Service 和 State 消息。
2. 独立 Catkin executor/adapter 包，提供 `rospy`/`actionlib` 薄适配层；不得导入厂商 runtime。
3. arm 与 gripper 各自的 ROS1 launch、fake-only 参数文件、安装规则和测试依赖。
4. ROS1 Action/STOP/ACK/state 名称、类型、queue、非 latched 状态发布和 freshness 契约。
5. 一个机构一个命令 owner；ROS1 与 ROS 2 command consumer 不得同时存活或同时接收同一命令源。
6. 独立调度的 STOP 路径、native bounded-call/cancel 能力证据门和无法保证时的
   `physical-isolation-required` 升级。
7. runtime release、release manifest、acceleration/motion profile、批准速度等级和最终工具修订的
   exact binding；不得由松散 ROS 参数覆盖已批准值。
8. 持久 safety latch 的唯一 supervisor/存储 owner、重启恢复、旧 session 拒绝和一次性 clearance
   消费契约。
9. 进程 PID/PGID 归属、持久日志、精确清理和机器可读最终报告。

当前 `cleanup_system.launch.py` 没有集成新的 arm/gripper gateway；它的可选旧夹爪 controller
也不能关闭上述缺口。

## 4. 未来 Noetic adapter 的不可绕过契约

### 4.1 唯一所有权

未来 ROS1/Noetic fake-only adapter 的默认名称先冻结如下；这些名称是
integration contract，不表示对应节点已经实现或获准启动：

| 机构 | 唯一节点 owner | Action | STOP service | ACK service | State topic |
| --- | --- | --- | --- | --- | --- |
| arm | `/cleanup_arm_gateway` | `/cleanup/arm/execute` | `/cleanup/arm/stop` | `/cleanup/arm/acknowledge_fault` | `/cleanup/arm/state` |
| gripper | `/cleanup_gripper_gateway` | `/cleanup/gripper/execute` | `/cleanup/gripper/stop` | `/cleanup/gripper/acknowledge_fault` | `/cleanup/gripper/state` |

State publisher 必须为非 latched，并携带 freshness、session、controller
boot、command ID、validity、fault 和 physical-stop-required 语义；不能只发布
位置。Actionlib 自动派生的 goal/cancel/status/feedback/result topics 全部归上表
唯一 gateway 进程所有。STOP 与 ACK 只能由对应 gateway 提供，不允许 bridge、
旧 ROS2 wrapper、旧 `ControlGripper` controller 或第二 adapter 同名注册。若
ROS master 中的 owner 无法由本次隔离 runner 精确证明，结果必须为
`UNKNOWN/BLOCKED`；不得查询另一套 ROS graph 后推断本图唯一。

| 资源 | 唯一 owner | 必须拒绝的组合 |
| --- | --- | --- |
| arm command state machine | 单个 Noetic arm gateway 进程 | 第二 arm gateway、ROS 2 arm command consumer、JOG/teleop/follow 进程 |
| gripper command state machine | 单个 Noetic gripper gateway 进程 | 第二 gripper gateway、旧 `ControlGripper` controller、ROS 2 gripper command consumer |
| arm/gripper fake backend | 对应 gateway 的单个进程内实例 | vendor client、设备 transport 或 fallback backend |
| persistent latch store | 独立 release supervisor | gateway STOP callback 内的文件系统写入、多个 writer、自报 session ID |
| Action command ID | core 生成并绑定当前 session/epoch | caller 自选 ID、重启后复用、旧结果完成新命令 |

启动前必须证明当前模式是 `ROS1_NOETIC_FAKE_ONLY`，并持有互斥的 deployment lease。存在 ROS 2
arm/gripper command consumer、第二 Noetic adapter 或 owner 无法判定时，adapter 必须拒绝 READY。
不得依靠“另一张 ROS 图中没看到节点”推断 owner 唯一。

`ROS1_NOETIC_FAKE_ONLY` 是 verifier 中独立于 `PERMANENT_LOCAL_ONLY` 和
`FIELD_AUTHORIZED_POLICY` 的 trusted boundary。它只允许 `ros_graph_allowed=true`；SSH、目标机、
设备访问、厂商 runtime、真实 Action/Service、硬件连接、field activity 和 motion 权限必须全部为
exact `false`，ARM/GRIPPER 真实 release binding 也必须为 `null`。A1 只有在该 boundary 中才可标为
`ELIGIBLE` 并进入结构化 record 校验；A0 前置结果、七项 A1 required-evidence digest 和对应外部
validator 任一缺失或不返回 singleton `True` 都必须拒绝。

`FIELD_AUTHORIZED_POLICY` 不能执行 A1。未来 field policy 只能引用先前在独立 Noetic fake-only
run 中完成并由 authority validator 核验的 A1 `PASS_LOCAL` 结果；若 A1 仍为 `BLOCKED`，即使
prerequisite callback 无条件返回 `True`，A2 及后续 field stage 也必须在 callback 前 fail-closed。
任何 field stage 本身都不得使用 `PASS_LOCAL`；其可执行状态只能是受约束的 `ELIGIBLE`，未满足时
保持 `BLOCKED` 或 `PROHIBITED`。

### 4.2 STOP、锁范围与迟到结果

STOP 不能依赖以下伪保证：

- 用 Python timeout thread 包裹一个仍在阻塞的 backend 调用；
- STOP 与普通命令共用同一 adapter `RLock`、同一单线程 callback queue 或同一阻塞 worker；
- backend `stop()` 返回即宣称 stationary、断能或物理 STOP 成功。

Noetic adapter 必须满足：

1. 普通 Action dispatch 使用单槽 worker；STOP service 使用独立 callback queue、spinner/线程、
   executor 和 lock domain。
2. core 的短状态锁只保护状态快照和 epoch/generation 更新；不得跨 backend send、query、STOP、
   validator、ID factory、持久化或日志 flush 持锁。
3. 每个外部调用前捕获 epoch；提交返回值前重新持锁并精确比较 epoch、session、command ID 和
   当前状态。STOP、close、fault 或 controller restart 递增 epoch 后，旧调用的成功、异常或反馈
   都不得覆盖新状态。
4. STOP 开始时先预留新 epoch 并进入 `STOPPING`；其后拒绝新 motion 和重复 STOP。close/fault
   可以再次 supersede，迟到 STOP 也不得复活旧状态。
5. fake backend 可用显式 barrier 模拟阻塞 send 和独立 STOP。真实 backend 只有在 manifest
   证明每个方法的 native deadline、transport cancellation、独立 STOP 通道及其截止时间后才可能
   离开 `DISABLED/BLOCKED`。
6. transport 无独立 STOP 能力、STOP 排在普通命令之后、截止时间不确定或取消后仍可能提交时，
   必须锁存 `physical-isolation-required`，Action/Service 不得报告软件 STOP 成功。
7. stationary 只能由 STOP 后、严格递增序列、合法且新鲜的多样本反馈、容差和 dwell 共同证明；
   STOP ACK 或同一时间戳重复样本不计入静止证据。

### 4.3 release/profile 精确绑定

adapter 启动和每次 motion admission 都必须核对：

- exact `runtime_release_id`；
- exact lowercase `release_manifest_sha256`；
- 独立的 acceleration/motion profile ID 与 artifact SHA-256；
- profile 内重复的 exact runtime release ID；
- 唯一、递增、已批准的 speed-grade 集合；
- named pose、limits、TCP、最终工具 revision 与同一 release 的绑定；
- bounded-call、STOP-isolation 和 hung-command STOP 报告的逐项 SHA-256 证据。

缺字段、旧 hash、大小写或内容漂移、profile/release 交叉绑定、未批准速度等级、named pose/tool
revision 不一致都必须在调用 backend 前拒绝。ROS 参数只能选择已冻结 profile，不能重新定义或
放宽批准集合。

### 4.4 持久 safety latch

未来本地机器可读锁存至少应具有：

- exclusive initial creation；已存在、孤儿 ledger、未知 sidecar 或 pending transaction 均拒绝；
- 原子 generation 更新、前一记录 SHA-256 链、同目录 durable publication 和 commit-uncertain
  marker；
- 由 store 发放且单调递增的 session epoch/nonce，caller 不能自报 session；
- 每次 STOP/physical-isolation relatch 都推进 generation，并使全部旧 session 永久失去清除资格；
- clearance 绑定 store、active generation/hash、latch epoch/nonce、最新 clearing session、完整
  release/profile、物理验证 artifact、审批 artifact 和一次性 clearance ID；
- 旧 session、旧 release、伪造 hash、重复 clearance、链截断、单边回滚、symlink/reparse/hardlink
  或 publication 不确定全部 fail-closed；
- gateway 重启后 ACTIVE 仍为 ACTIVE，不能用默认 CLEAR 或新进程 ID 清除；
- 外部 validator 必须返回 exact boolean `True`，且验证迟到时新的 relatch/session 能使结果不可提交。

本地 SHA 链不是签名。未具备受保护存储、抗整体回滚、独立审批和受限 supervisor 前，该契约只可
作为 pure-local 证据，不能授权真实 backend。

## 5. 未来隔离 Noetic dry-run 步骤

本节每一项都应由单一 runner 生成机器可读证据。任一必需项失败即停止本次 runner，并进入精确
清理；不得切换到厂商 overlay、真实 backend 或目标机路径“补测”。

### 5.1 运行前静态门

- [ ] 冻结待测源码清单、Git/tree 状态说明和逐文件 SHA-256；不覆盖用户工作树。
- [ ] 只允许新建的 Noetic interface/adapter 包及 pure-core/fake 依赖进入 bundle。
- [ ] AST/import 扫描确认 adapter、launch、config、tests 不含厂商、serial/USB、socket client、
  动态 import、设备枚举/open 或真实 backend factory。
- [ ] 检查生产 factory 只接受 `fake`；未知 backend 名称启动即失败。
- [ ] 检查 ROS1 launch 不 include 厂商、底盘、视觉、旧夹爪 controller 或 ROS 2 bridge。
- [ ] XML、YAML、Python 3.8 AST/compile、package/CMake dependency 和安装目标全部通过。
- [ ] Noetic Action/Service/State 字段与 ROS 2 参考接口逐字段 crosswalk 通过；不允许静默丢弃
  session、authorization、command ID、physical-stop 或 feedback validity 字段。
- [ ] release/profile/latch fixture 的 SHA-256 与测试期预期值完全一致。

### 5.2 隔离环境

- [ ] 使用唯一 `run_id` 和固定的本次临时根；源码副本、Catkin build/devel、ROS home、日志、
  PID、结果和清理记录全部位于该根。
- [ ] 只 source `/opt/ros/noetic/setup.bash` 和本次 fake-only overlay；明确禁止厂商 overlay。
- [ ] 使用 loopback-only 的独立 ROS master 端口、唯一 namespace 和独立日志目录；不得与现有
  master、ROS1/ROS2 graph 或默认 namespace 互通。
- [ ] runner 启动前记录端口选择、环境 allowlist 和基线进程；不做设备、USB、串口或硬件 owner
  探测。
- [ ] 所有子进程都由 runner 直接创建，记录 PID、PGID、启动时间、命令摘要和父子关系；禁止用
  宽泛名称匹配终止其他进程。

### 5.3 Catkin 构建与静态测试

- [ ] 只构建 Noetic interface 包和 arm/gripper fake adapter 包。
- [ ] message/action/service generation 成功，安装空间中类型可导入。
- [ ] Catkin test 覆盖接口 crosswalk、禁止调用扫描、pure-core、manifest、latch 和 callback driver。
- [ ] 构建/测试日志持久化，记录命令、退出码、passed/failed/skipped 数量和日志 SHA-256。
- [ ] warning allowlist 必须为空或逐条受审；缺依赖不得通过 source 其他 overlay 绕过。

### 5.4 无 ROS 的 callback/state-machine 驱动

以下测试先在不启动 master、不导入厂商 runtime 的 Python 进程中执行：

- [ ] arm/gripper goal accept/reject、cancel、STOP、ACK 和 state/feedback 映射；
- [ ] 缺 session、错误 authorization、重复 command、陈旧 state、controller boot drift 全部拒绝；
- [ ] joint/TCP/normalized position/jaw opening 非有限、越界和未知 target kind 全部拒绝；
- [ ] named pose 不存在、tool revision 不符、TCP mode 未批准和 speed grade 未批准全部拒绝；
- [ ] release/profile SHA 缺失、陈旧、伪造或交叉绑定全部拒绝；
- [ ] stationary dwell 必须由时钟真正跨过 dwell，不能降低生产判据或重复同一时间戳凑样本；
- [ ] ACK 在 STOP 未完成、静止未证实、session 陈旧、fault 不可清除或 authorization 无效时拒绝；
- [ ] callback exception 转换为 fault/aborted 结果，不能使 adapter 线程静默退出或恢复 READY。

### 5.5 STOP/并发/重启 pure-fake 负测

- [ ] 阻塞普通 send；独立 STOP 在规定 fake deadline 内完成，且不等待普通命令锁。
- [ ] STOP 先推进 epoch；随后释放旧 send，其迟到成功不得完成 Action 或覆盖 `STOPPING`、
  `FAULT_LATCHED`、`CLOSED` 或 `physical-isolation-required`。
- [ ] STOP 调用阻塞、抛错、超时或返回未确认时，锁存 persistent physical-isolation-required，
  STOP response 不得为成功。
- [ ] STOP in-flight 时新 motion 和重复 STOP 被拒绝；close/fault supersede 后迟到 STOP 不得回写。
- [ ] cancel、STOP、fault 和 controller restart 各自使旧 feedback/result/ACK 失效。
- [ ] 进程重启后 persistent ACTIVE 恢复；重启前 session/authorization/clearance 全部拒绝。
- [ ] 伪造 credential、旧 manifest/profile hash、重复 clearance ID、ledger/record 单边回滚、
  commit-pending 和 publication failure 全部保持 BLOCKED。
- [ ] fake backend 若故意声明无独立 STOP 能力，factory 和 core 均 fail-closed；测试不得把它算作
  “STOP 降级通过”。

### 5.6 隔离 Noetic in-memory smoke

只有 5.1--5.5 全绿后才进入本步骤；仍只使用 fake backend：

- [ ] 启动独立 master 和一个 arm 或 gripper gateway，禁止同时启动同机构的第二 owner。
- [ ] 精确核对 Action/STOP/ACK/state 的名称、类型、单一 owner、queue 和 state `latch=false`。
- [ ] 启动后零命令：没有自动 init、enable、home、calibrate、clear、resume 或 motion。
- [ ] 使用测试客户端只向本次隔离 namespace 的 fake endpoint 发送受控请求。
- [ ] 分别执行成功 fake action、拒绝案例、cancel、STOP 并发、stationary、ACK 和 shutdown；记录
  command/session/epoch/state 序列。
- [ ] gripper smoke 不接受退休 AG 默认参数；若输入历史非法反馈值，必须 INVALID/BLOCKED。
- [ ] smoke 日志明确写出 `backend=fake`、`vendor_import_count=0`、`hardware_command_count=0`。

### 5.7 精确清理

- [ ] 先撤销 fake command admission，再停止测试客户端和 adapter。
- [ ] 只对本 runner 记录的 PID/PGID 发送 TERM；有界等待后仅对仍存活的本任务子进程执行 KILL，
  随后 wait/reap。
- [ ] 不用宽泛 `pkill`、进程名 grep 或目录范围删除影响其他任务。
- [ ] 关闭本次独立 master，确认本次 PID 集合为空、端口释放、临时根外无本任务写入。
- [ ] 仅删除明确声明为 disposable 的 build/runtime 子目录；保留 build/test/smoke/cleanup 日志、
  result、manifest 和 SHA256SUMS。
- [ ] 清理不能证明时，结果为 `UNKNOWN/BLOCKED`，不得写 `PASS`。

## 6. 持久证据格式

每次 future run 至少保留：

```text
<run-root>/
  source_manifest.json
  environment_allowlist.json
  static_scan.json
  build.log
  test.log
  callback_contract.log
  smoke.log
  processes_before.json
  processes_started.json
  cleanup.json
  result.json
  SHA256SUMS
```

`result.json` 至少包含：schema、run ID、UTC 起止时间、Noetic/Python 版本、隔离 master/namespace、
source manifest SHA、release/profile SHA、backend=`fake`、各阶段状态与退出码、passed/failed/skipped
数量、硬件命令计数、启动/残留 PID 数量、清理状态和总判定。

状态语义固定为：

- `PASS`：本项已执行且全部断言满足；
- `BLOCKED`：缺实现、缺环境、失败、证据不完整或清理无法证明；
- `SKIPPED`：明确不在本次 fake-only 范围，例如硬件/现场项；`SKIPPED` 永远不等于通过。

总结果只有在所有必需 source/build/test/callback/smoke/cleanup 项均为 `PASS`、失败数为 0、残留数为
0 且硬件命令计数为 0 时才可为 `PASS`。任何真实 backend 仍必须单独保持 `DISABLED/BLOCKED`。

## 7. 当前验收矩阵

| 项目 | 当前结果 | 证据/原因 |
| --- | --- | --- |
| ROS 2/Foxy-only 包形态盘点 | PASS（源码审计） | `ament_python`、`ament_cmake`、`rosidl`、`rclpy`、ROS 2 launch/YAML 已确认 |
| pure-Python core/manifest/latch 复用候选 | PASS（源码候选） | 可与 ROS adapter 分离；不代表 Noetic runtime 或硬件能力 |
| Noetic Catkin interface 包 | BLOCKED | 不存在 arm/gripper Noetic message/action/service generation |
| Noetic `rospy`/`actionlib` adapter | BLOCKED | 不存在 arm/gripper adapter、callback/STOP queue 和 owner 实现 |
| Noetic launch/config/install | BLOCKED | 不存在 ROS1 launch、ROS1 参数 schema 和 Catkin 安装面 |
| Noetic Action/STOP/ACK callback/state-machine 测试 | BLOCKED / NOT RUN | 当前只有 ROS-free/ROS 2 参考测试，未实现 Noetic adapter |
| Noetic Catkin build/test | BLOCKED / NOT RUN | 本轮禁止启动 Catkin/ROS；对应包也尚不存在 |
| Noetic isolated in-memory smoke | BLOCKED / NOT RUN | 必须等待前述实现和静态门全部通过 |
| Foxy v3 target build/test/smoke | FAIL-before-build | `status=2`；build/test/smoke 未进入，禁止重解释为通过 |
| 真实 arm backend | DISABLED/BLOCKED | 缺已验证 native deadline/cancel、独立 STOP、release attestation 和受保护 latch |
| 真实 gripper backend | DISABLED/BLOCKED | 最终完整替代夹爪、controller、protocol、transport owner 和 STOP 契约未冻结 |
| ROS graph、目标机、设备、厂商 runtime、硬件/动作 | SKIPPED/PROHIBITED | 本轮硬边界；未执行且不得用软件证据填充 |

因此当前不能宣称“ROS1 Noetic arm/gripper dry-run ready”。下一交付门是先实现独立 Catkin
interfaces + fake-only thin adapters + ROS-free callback/STOP 并发测试；这些全绿后，才可在另行批准的
本地隔离 Noetic 环境执行第 5 节，不得转向目标机或硬件路径。

## 8. 审计依据

- `docs/ros1_ros2_base_bridge_contract.md`
- `docs/ros1_noetic_base_bridge_implementation.md`
- `docs/v3_pick_place_acceptance.md`
- `docs/gripper_control.md`
- `docs/foxy_arm64_deployment.md`
- `docs/arm_persistent_safety_latch.md`
- `docs/gripper_persistent_safety_latch.md`
- `docs/arm_motion_release_manifest.md`
- `docs/final_gripper_release_manifest.md`
- `docs/arm_gripper_field_acceptance_matrix.md`
- `docs/evidence/arm_foxy_dryrun_20260813_v3/README.md`
- `src/limo_cleanup_executor`
- `src/limo_cleanup_interfaces`
- `src/limo_cleanup_bringup`
- `ros1_overlay_src`
