# LIMO AI Scout V1～V3 产品路线图与验收标准

日期：2026-08-11
更新：2026-08-12 13:45 +08:00
状态：当前最高级产品基线，覆盖此前以 `touch_only` 为最终目标的阶段性描述。

`touch_only` 仍可作为机械臂安全、坐标和任务状态机的中间验证，但最终产品路线固定为：

| 版本 | 目标 | 当前状态 |
| --- | --- | --- |
| V1 | 环境扫描、建图定位与自主避障 | ROS1 手动底盘运动已通过；V1 实机完成度 0%，地图/waypoint 未冻结，YDLidar/SLAM/move_base 未验收 |
| V2 | “小莫小莫”唤醒、简单物体识别、停下、到垃圾桶旁边去 | 语音 42 tests 与严格 payload 解析通过；真实麦克风、bridge 和 waypoint 导航未验收 |
| V3 | myCobot 280 M5 + 经正式选型、冻结和验收的末端工具完成空矿泉水瓶定点投送闭环 | 机械臂只读通信通过；工具选型、夹爪、几何、动作和闭环均未验收 |

任何版本的真实运动都必须在动作前当次通知现场人员并取得单次明确授权。当前只有主开关可
作为物理断电手段；语音“停下/紧急停止”和软件 cancel 不能替代物理断电。

## 共同底盘架构

V1 优先使用机器人原生 ROS1 Noetic 栈：

```text
YDLidar -> ROS1 /scan -> ROS1 SLAM/定位 -> ROS1 move_base
                                      -> ROS1 safety watchdog/mux
                                      -> 私有 /cleanup/base/driver_cmd_vel
                                      -> ROS1 limo_base_node
                                      -> /dev/ttyTHS0
```

ROS1 `limo_base_node` 是 `/dev/ttyTHS0` 的唯一 owner。ROS2 清理系统需要控制底盘时，必须遵守
`docs/ros1_ros2_base_bridge_contract.md`：ROS2 安全网关 → 受限单向 bridge → ROS1 watchdog →
私有 `/cleanup/base/driver_cmd_vel` → remap 后的 ROS1 driver。ROS1 与 ROS2 底盘 driver 永禁
并发，公开 ROS1 `/cmd_vel` 在自动模式下必须零端点。

当前 bridge 状态固定为
`IMPLEMENTED_LOCALLY_UNVERIFIED / ZERO-STAGE RUNNER BLOCKED / NONZERO_NAV_BLOCKED`。installed V1
public wrapper/core 已 native-only，固定 `/v1/nav_cmd_vel`，不能直接进入 integrated request；Bridge
integrated runner 私有生成唯一 map_server/AMCL/move_base，并从 sealed map + 6 config 加载。该架构
子项与离线 `94/75/49/9/V1 29` 回归虽通过，第三轮独立终审仍 **REJECT**：PRE_CORE 缺地图参数、
snapshot manifest 参数类型错误、缺全局单 runner 锁、TERM/KILL 孙进程、逐 spawn lease/auth 空窗、
zero-stage/controller 无安全交接、第二次 wait cleanup、PRE_CORE hash 缺口、十帧窗口坏帧保留和
Tmini `±100°` 与 health gate `±π` 冲突均未关闭。

2026-08-12 14:45 final source 复核增量：两份 RELEASE 文档和 24/24 managed SHA MATCH，离线
`117/79/9/V1 35` 及 static/bash/XML/compileall PASS；原 PrivatePipe 尾随恶意标签缺口已关闭。
但真实 producer 的合法 READY→heartbeat 两次短写可在一个 pipe read 中合并，而 consumer 固定要求
READY 为批次末条，已独立复现 MAP/FULL 两条合法序列均 BLOCK。因此 source 仍 REJECT；04:45 旧
P0/P1 只保留历史，当前阻塞为该 P1 合法启动竞态。runtime/site/nonzero 与地图/waypoint/safety
source 继续 BLOCK。

V1 虽不依赖 ROS1/ROS2 bridge，也必须先关闭 `ROS1_DRIVER_COMMAND_TIMEOUT_UNVERIFIED`：证明

V1 perception-only field 包的深入只读结论仍为 `REJECT_FOR_FIELD_RELEASE`：自制授权 ID 可重复
通过，SIGTERM 可遗留独立 session child，运行期仅末尾一次速度/图快照，NaN angle 和
`fuser rc=1+stderr` 存在误判，result-file 在动作后创建存在证据竞态；odom/TF freshness/finite、
scan ranges、TF endpoint 和 namespace 防绕过也未闭合。离线 `35/35` 不改变 V1 实机 0%。
速度流中断后底盘会在有界时间内停车，或在 ROS1-only 路径加入同等 fail-closed watchdog。

## V1：环境扫描与自主避障

### 范围

1. 使用 YDLidar 发布稳定 `/scan`，确认激光 frame、安装方向、最小/最大量程和遮挡区。
2. 使用 ROS1 SLAM 建立测试场地图并保存；重新启动后可加载地图完成定位。
3. 使用 ROS1 `move_base` 完成地图内 waypoint 导航、静态避障、动态障碍停车/重规划和取消。
4. 机械臂和夹爪保持禁动；V1 不执行识别后抓取或投放。
5. V1 首先在 ROS1 原生栈独立验收。ROS2 bridge 只在 ROS1 导航基线稳定后单独分级接入。

当前实机完成度为 `0%`：`active map_id=NOT_AVAILABLE_MAP_NOT_FROZEN`，
`trash_bin_staging=NOT_AVAILABLE_UNMEASURED`，禁止在 launch、waypoint、语音或 bridge 配置中
填入猜测地图名或坐标。

V1 perception-only 现场包已经本地准备：默认 dry-run，动作路径仅启动 base+YDLidar，固定
`pub_odom_tf=true`、私有 `/v1/driver_cmd_vel`，脚本无速度 Publisher；离线 `35/35`、overlay/Catkin
static audit 与 compile PASS。其状态仅为 `PREPARED_LOCALLY_NOT_RUN`。独立 field-release 审计仍
**REJECT**：一次性授权 ID 不具备签发/时效/session binding/消费，异步 TERM/HUP 清理不安全，且
采样期间没有持续速度端点监控；结果文件、TF owner、forbidden nodes、NaN/fuser/现场 TTY 门也需
收紧。修复并重新复审前不得运行该包，不能用它把 V1 实机完成度从 `0%` 提升。

### 验收门

- **传感器与 TF**：连续 10 分钟 `/scan` 无持续丢帧，激光朝向正确；`map -> odom`、
  `odom -> base_link`、`base_link -> laser` 各有唯一 owner，无重复 TF。
- **建图与重定位**：完成一张可保存、可重新加载的测试区地图；重启定位后机器人位置与朝向
  无明显跳变，异常必须量化记录。
- **waypoint**：在清空、低速场地完成至少 5 次预设点导航，5 次均无碰撞、无未知速度发布者，
  到点误差和用时逐次记录。
- **避障**：至少 3 次在路径中加入软障碍物；机器人不得接触障碍物，必须停车或生成安全新
  路径。局部规划器振荡、原地持续打滑或路径不可达必须 fail-closed。
- **故障与取消**：分别注入激光丢失、里程计/定位失效、规划器退出、目标取消和速度流中断；
  每种情况都必须停车且不恢复旧目标。至少 3 次取消验证均使导航退出并保持零命令。
- **物理停止**：主开关是当前唯一可控的物理断电手段，但独立的断电、停车距离、恢复和旧目标
  不自动续跑验收尚未完成；该项通过前保持硬阻塞。
- **所有权**：ROS1 `limo_base_node` 是 UART 唯一 owner；ROS1/ROS2 图和进程表中没有第二个
  driver、teleop、手柄、Nav2 或未知速度发布者。

全部通过后 V1 才记为完成。仅能键盘驾驶不等于 V1 通过。

## V2：唤醒、识别与垃圾桶语义导航

### 固定交互范围

- 唤醒词：`小莫小莫`；
- 简单物体识别：先限定少量明确类别，并输出类别、置信度、时间戳和 frame；
- 指令：`停下`、`到垃圾桶旁边去`；
- 所有导航请求仍由 V1 的 ROS1 `move_base` 执行，不新增第二套底盘 driver。

`小莫小莫` 是普通任务的唤醒门，低置信度或非白名单文本不得转发。运动请求需要复述确认；
“停下/停止任务/紧急停止”无需确认，并可绕过唤醒门直接进入高层 cancel 与软件归零链，但
仍不能替代物理断电。

ROS2 语音/任务层接入 ROS1 `move_base` 时，优先桥接窄化的 goal/cancel/status 接口，不让语音
节点发布速度。若使用底层 Twist bridge，则必须先完成 watchdog、断链停车、里程计和 TF 的
全部验收。

### 已移除的交付范围

V2 正式不交付“到这里来”“到我这里”“到说话人处”等说话人相对导航，不规划麦克风阵列、
DOA 或视觉人+深度定位。相关短语不得成为发布版 intent，也不得触发导航请求。

### 垃圾桶导航分两阶段

1. **V2.0 地图 waypoint**：先把垃圾桶旁安全停靠点保存为命名 waypoint；“到垃圾桶旁”只
   调用该固定点，并由 move_base 避障到达。
2. **V2.1 视觉精定位**：在 waypoint 附近用垃圾桶检测、AprilTag/ArUco 或深度几何做最终
   对准。视觉结果无效时保留 waypoint 到位状态，不盲目继续靠近。

### 验收门

- **唤醒**：固定现场至少 20 次正常说出唤醒词，成功不少于 18 次；另用至少 20 条不含唤醒词
  的语句测试，误唤醒不超过 1 次。所有原始计数必须保留，不能只写“可用”。
- **停下**：导航中连续 5 次“停下”均取消当前目标、撤销软件运动授权并使命令链归零；该
  口令仍不替代主开关。
- **垃圾桶 waypoint**：在 V1 已通过的地图中连续 5 次到达指定安全停靠点，无碰撞、无绕行
  发布者；记录到点误差。视觉精定位单独计分，不得掩盖 waypoint 失败。
- **物体识别**：对每个首版类别保存正样本、混合场景和纯背景结果；背景误触发、类别混淆和
  无有效深度都必须可追踪，不能直接触发 V3 动作。

## V3：矿泉水瓶定点投送闭环

### 硬件与动作定义

- 机械臂：Elephant Robotics myCobot 280 M5；
- 末端执行器：原 `mycobot_gripper_ag` 与 `v1gripper` 完整替代候选之间尚未完成正式选型；
  任一方案都必须冻结工具修订并独立验收，替代工具不能沿用 AG 参数；
- 投送动作固定为“夹取后运输到垃圾桶上方并释放”，不使用投掷动作；
- 首版只处理空矿泉水瓶和已批准的固定取放区域。

详细架构、只读身份、几何/碰撞、抓取/释放证据与 V3-0～V3-7 分级标准见
`docs/v3_pick_place_acceptance.md`。

### 已知基线与当前阻塞

- `/dev/elephant` 已确认 VID:PID `1a86:55d4`、SN `5B09024480`、`115200`；M5 在
  Transponder/USB UART 下本体只读连续三轮 `9/9`，`controller=1`、`power=1`、`error=0`；
- 旧 AG 当前物理断开；其历史 `get_gripper_value(1)=255` 是 INVALID/DISCONNECTED，绝非全开，
  但该 API/语义不能自动继承给替代夹爪；
- `C:\Users\DYH\Desktop\v1gripper` 判定为带自身舵机/传动的完整替代夹爪候选，不是 AG
  适配件。初始快照 87 个文件，最终快照仅 1 SLDASM + 33 SLDPRT；19 STEP 缺失原因未知。
  法兰、工具修订、装配、TCP、包络、质量/质心/惯量尚未 REVIEWED；
- 上层必须由单一 manipulation coordinator 拥有命令。arm gateway 独占 `/dev/elephant`；只有
  BOM 证明保留 AG/Atom 链路时才由同一 MyCobot gateway 控夹爪，否则替代夹爪必须有独立且
  唯一的受控 transport owner。现 `PymycobotGripperBackend` 是构造即拒绝且不调用注入
  factory 的永久 fail-closed 占位符，不再提供旧 AG 协议示例；
- 当前没有真实 arm backend、IK/轨迹/碰撞、抓取验证或释放验证，全部真实动作保持 BLOCKED。

### 闭环阶段

```text
检测矿泉水瓶
  -> 选择桶外且可达目标
  -> 底盘/机械臂接近预抓取位姿
  -> 夹爪抓取
  -> 抓取状态验证
  -> 运输到垃圾桶安全释放位姿
  -> 夹爪释放
  -> 结果验证与任务结束
```

不得省略抓取验证、运输锁定或释放后验证；不得以甩臂、快速抛掷或惯性投送替代释放。

### 前置门

- V1 已通过，底盘能安全到达并停车；V3 可先由受控界面触发，不强制依赖 V2 语音；
- task manager、language 与 perception 对 V3 统一只允许空 `plastic_bottle`；
- `base_link -> arm_base_link`、相机到机械臂、`arm_flange -> gripper_tcp` 外参完成三次测量与复核；
- 冻结使用原 AG 还是完整替代夹爪；确认执行器、电压/峰值电流、控制器、通信、反馈、断能和
  唯一 transport owner 后，再做夹爪断电连接、开合方向、行程和空瓶夹持力独立验收；
- MoveIt/IK、关节限位、碰撞包络、负载、线缆、预抓取/撤回路径和底盘锁止均通过；
- 原厂 `mycobot_follow` 永久禁用；真实机械臂与夹爪动作必须使用项目安全 backend；
- 任一失败都停止并请求人工处理，首版禁止自动二次抓取。

### 验收门

- **感知**：桶外单瓶可生成唯一抓取目标；桶内瓶被过滤；空桶、混合图和纯背景不误触发动作。
- **接近**：底盘到位后锁止，机械臂只在批准包络内从预抓取位姿接近；目标或 TF 过期立即停止。
- **抓取**：正式闭环至少同时使用夹爪开度/电流与抬升后视觉两类证据确认瓶子被夹住；
  无确认不得进入运输。
- **运输与释放**：运输全程不碰撞车体、地面、人员或垃圾桶；到达固定释放位姿后打开夹爪，
  不进行投掷。首版禁止底盘与机械臂同时运动；底盘运动前机械臂必须收回批准的运输姿态。
- **结果验证**：确认瓶子已离开夹爪并位于垃圾桶内；不确定时报告失败并停止，不自动重试。
- **批量标准**：依次完成 V3-0～V3-6 后，受控范围连续 20 次完整闭环至少 19 次功能成功；
  安全绕过、碰撞、非预期运动、掉瓶后继续行驶、错误桶位释放和未授权自动重试均为 0。

## 版本依赖与当前下一步

```text
V1 ROS1 传感器/建图/导航
  ├-> V2 语音与语义目标
  └-> V3 检测-抓取-运输-释放闭环

V2 与 V3 都通过后，可再允许语音触发 V3；V3 验收本身可先由受控界面触发。
```

当前优先级：

1. V1 installed native-only 路径与新五 release/interface SHA 已离线冻结；只感知包离线 V1
   `35/35` 及 static audit PASS，但现场发布审计 REJECT。先修复一次性授权、TERM/HUP 后代清理、
   采样期持续速度监控、结果/TF/forbidden-node 门；同时修正
   Bridge runner 的 PRE_CORE 参数与 snapshot 类型、单实例/后代 cleanup/逐 spawn lease、zero-stage
   controller 交接、scan 连续窗口及 Tmini 角范围合同，再验证唯一 `odom -> base_link` owner、
   `/scan` 4.8～7.2 Hz 和运行期 TF/时间戳门；之后才申请现场只读/零输出验收；
2. 完成并冻结项目地图，记录 `active_map_id`、地图制品哈希和实测 `trash_bin_staging`；当前禁止
   使用 vendor `map1017` 或任何猜测坐标；
3. confidence-first 感知修复已离线达到人工正确 `49/54`、背景 `0/24`、mix
   `15 active / 15 filtered`；证据目录为
   `C:\Users\DYH\Desktop\limo_graphtest\evidence\perception_selector_fix_20260812`。视觉 MD SHA-256
   `759c40bb104fd09ff3833a1d86c315acfbe790d180e41f38c385f507291259ec`，`matrix.json` SHA-256
   `0ca55ef487c11222f1c9288eec57ae776f40daff7b624ce27b98d3e1966f9696`，机器 diff SHA-256
   `666a937ada9f46dcbaad7607490ae2d99d37fd381f2a0d70cbbc23523dca0db2`，源码 diff SHA-256
   `2d75e13e642524071957d6ed32c89fabb926a7508b5ea372bc80a3656a0437e5`；机器 diff 仅改变
   `IMG_8949` 的 selected bottle。状态仍为 `LOCAL_FIX_VERIFIED_NOT_DEPLOYED / REAL_MACHINE_PENDING`；
   下一步固化源码/制品并做机器人只读复验。保持 `conf=0.35`，禁止降到 `0.25`；
4. bridge 已确认 sticky 撤权、generation、normal cleanup retain-safety、endpoint/QoS、native-only
   V1 和 sealed builder 子项通过；只有本轮新 P0/P1 全部关闭并加入行为回归后，才进入 Catkin/跨图
   零输出验收。真实移动仍需新的单次授权；
5. V2 继续完成真人麦克风、唤醒/误触发和真实 waypoint 导航；“到这里来”保持 unsupported；
6. V3 等机械臂几何、最终末端工具和独立动作安全验收完成后再启动，绝不首次运行完整闭环。

跨版本还需单独验证 Jetson 同时运行 SLAM、导航、双模型与 Vosk 时的 CPU/GPU、
内存和控制延迟；并确认主开关能否同时切断底盘与机械臂独立电源的危险能量。
