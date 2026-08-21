# 固定瓶位矿泉水瓶抓取 ROS1/Noetic 进度

日期：2026-08-19
状态：`ROS1_PREVIEW_CORE_PASS / REAL_EXECUTION_BLOCKED`

## 本轮边界

- 默认运行面为 ROS1 Noetic；新实现位于 `ros1_overlay_src`，没有复用 ROS2 gateway。
- 本轮没有启动 `roscore`、ROS graph、相机、机械臂或夹爪节点。
- 没有访问设备路径、厂商 runtime、网络或 SSH，没有连接、上电、使能或动作。
- 现有导航和视觉控制源码未修改；新包只消费既有 ROS1 `PerceptionFrame` 契约。

## 已实现

新增 Catkin 包 `limo_cleanup_ros1_manipulation`：

- `fixed_bottle_pick_core.py`：ROS 无关的固定瓶位规划核心；
- `fixed_bottle_pick_preview_node.py`：`rospy` preview-only adapter；
- ROS1 XML launch、Catkin package/build/install 文件；
- host-owned 严格 JSON policy；
- pure-fake 正反测试和 ROS1/静态禁止扫描。

ROS1 适配器订阅既有感知包的准确话题 `/cleanup/perception/frames`（复数）；该名称已与
`perception_frame_collector.py`、`typed_raw_binding.py` 和现有 publisher 源码交叉核对并由
静态测试固定，禁止回退到不存在的单数 `/cleanup/perception/frame`。

有效预览严格生成五个阶段：

1. 夹爪张开；
2. 机械臂到预抓取位；
3. 垂直下探到抓取位；
4. 夹爪以操作员标定的参数持续夹持；
5. 机械臂垂直抬升。

所有输出固定为 `execution_permitted=false` 和
`PREVIEW_ONLY_REAL_EXECUTION_BLOCKED`，当前没有可将预览直接转成真实命令的代码。

## 夹爪参数绑定

来源：`C:\Users\DYH\Desktop\gripper\gripper_safe.yaml`
来源 SHA-256：
`62508BEA0CB96817099DC8EFDE10FEB034CAD7A844A95FEFDD29A3F57A6BBD18`

绑定参数：

| 字段 | 值 |
| --- | --- |
| gripper type | `1` |
| open target | `100` |
| 60 mm bottle target | `5` |
| speed | `30` |
| protect current | `300` |
| success | `moving=true`、反馈 `18..20`、瓶子夹紧、无异响、无过热、无 fault |

preview 节点要求显式传入原始 gripper 配置文件并比较实际文件字节 SHA-256；伪造、缺失或变更
文件均拒绝。

## 已通过测试

- 新包 pure-fake：`17 passed / 0 failed / 0 skipped`；
- 既有 ROS1/Noetic 边界回归：`7 passed / 0 failed / 0 skipped`；
- Python 3.8 AST：`6/6`；
- in-memory compile：`6/6`；
- JSON parse：`1/1`；
- XML parse：`2/2`；
- 新运行文件中的 ROS2、厂商 runtime、设备路径、Action client、Service proxy 命中：`0`。

上述均为本地软件证据，不是现场、硬件或动作 PASS。

## 2026-08-19 ROS1 目标机只读观察

- 目标机 `master` 为 ROS1 Noetic；本任务未启动或重启 ROS master、相机或任何控制节点。
- 感知包归档上传至固定隔离目录
  `/tmp/limo_pick_perception_20260819_v1`；上传归档 SHA-256 为
  `11423d705051165a884cc509a371481619eada8beac0f10a24ceada4fabe8c67`。
- Catkin 构建 `build_rc=0`。测试的 Python 3.8 `ast.Index` 兼容修复 SHA-256 为
  `cf9d74b2222dc6e98263bd6f847941494dba4cf8dad3794eb4f1db4113db45ad`；
  目标机最终聚合为 `57 passed / 0 failed / 0 skipped`。
- 两个模型文件大小和 SHA-256 与 `model_bindings.json` 完全相同；目标机已安装的
  torch distribution 报告 `2.1.0a0+41361538.nv23.6`，与契约中的
  `2.1.0a0+41361538.nv23.06` 字符串不完全相同，因此不得称为正式安装证据 PASS。
- 唯一一次 `perception_v2_readonly.launch` 已精确停止且无 detector 残留。首帧为
  `valid=false`、`rgbd_contract_rejected`：RGB 是 `640x480`，depth 是 `640x400`，
  depth CameraInfo 的 `frame_id` 为空；相机参数同时显示
  `color_depth_synchronization=false`、`depth_align=false`。
- 相机内部 `camera_depth_optical_frame -> camera_color_optical_frame` TF 存在；
  当前 ROS graph 没有 `base_link`，因此相机观测不能转换为机械臂坐标。
- 单帧只读 RGB 探针脚本 SHA-256 为
  `a815afb331320311b8a1e940ef45715f212f4c9d72ac911de765d7bc6000ee50`。
  输出 JSON SHA-256 为
  `4b51e0f9aaddb81e211a7340139b8c222fdf2b70deaffef3d2eecb5240dbb92e`。
  目视复核证明矿泉水瓶没有出现在该帧；两个模型框均位于绿色支架/螺钉上，属于误检，
  不得作为抓取目标。
- 本轮没有发布控制消息、调用相机服务、访问执行器端口，且底盘、机械臂和夹爪均未动作。

## 2026-08-20 双相机身份

- 原 DaBai RGB-D 相机继续通过 ROS1 发布
  `/camera/color/image_raw`、`/camera/depth/image_raw` 和 `/camera/depth/points`。
- 新末端 UVC 相机身份为 JoyandAI `JYU2C-2083`，序列号
  `JYU2C-2083-2603103`。稳定采集路径为
  `/dev/v4l/by-id/usb-JoyandAI_JYU2C-2083_JYU2C-2083-2603103-video-index0`。
- `/dev/video0` 具有 `:capture:` capability；`/dev/video1` 与其序列号、USB interface
  和物理拓扑相同，但没有 capture capability，因此不是第二台物理相机。
- 现场已有 `guvcview -d /dev/video0` 进程。本任务没有并发打开该设备、改变相机控制项或
  终止该进程。
- 新末端相机当前没有 ROS1 topic、CameraInfo 内参或相机到夹爪 TCP 的外参，故仅可作为人工
  观察源；尚不能授权视觉伺服或真实抓取动作。

## 当前缺失的实际几何输入

提交的 `fixed_bottle_pick_offline.json` 中以下字段故意为 `null`，因此真实 policy 尚不能加载：

- 瓶心在 `arm_base_link` 中的固定三维位置和允许偏差；
- 瓶子固定朝向的现场/夹具确认 ID；当前视觉消息没有姿态字段；
- 夹爪工具 `roll/pitch/yaw`；
- 瓶心到实际抓取 TCP 的三维偏移；
- 预抓取净空、抬升高度；
- 三轴允许 workspace；
- `base_link -> arm_base_link`、相机到机械臂链和 `gripper_tcp` 的实测变换。

不得用单元测试中的合成坐标 `[0.20, 0.00, 0.04] m` 或姿态 `[pi, 0, 0]` 作为现场值。

## 下一恢复入口

先让瓶子进入现有 RGB 画面的可见地面区域，再做无动作的固定摆放测量/视觉预览：记录一帧 ROS1
`PerceptionFrame`，确认 `tf_target_frame=arm_base_link`、目标新鲜、唯一且位于固定位置容差内。
随后填入并复核上述几何字段，运行 preview 得到五阶段数值计划。

只有计划数值、碰撞/地面净空、速度等级、实体 STOP/急停条件均单独确认后，才停在
`move_pregrasp` 第一段真实动作前请求动作级授权。不得一次性执行完整抓取。
