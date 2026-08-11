# ROS 2 Foxy / ARM64 部署审计

> 2026-08-07 离线修复更新：三个 Foxy launch API 阻塞和四处
> `/mnt/c/...` 默认模型路径已经从源码移除。当前 launch 代码已改用
> `PythonExpression`、直接参数文件路径、`ParameterValue` 和动态
> `FindPackageShare`，并新增 Foxy 兼容回归测试。本文下方的首次实机
> 盘点记录用于保留修复依据；其中“launch API 阻塞”和“WSL 默认路径
> 阻塞”已经解决，并已在机器人 Foxy/aarch64 上完成复测确认。
>
> 离线验证结果：bringup 构建通过；bringup 测试 22 passed / 1 skipped；
> Foxy 专项回归 16 passed；三个 launch 的 `--show-args` 均通过；双模型
> 只读启动烟测和默认纯模拟系统烟测均通过。整个工作区当前测试汇总为
> 75 tests / 0 errors / 0 failures / 5 skipped。后续机器人原生构建、
> launch 解析、双模型加载、五图 CPU 推理和真实只读感知链也已通过。

审计日期：2026-08-07

目标机：LIMO Pro，`master` / Ubuntu 20.04.6 / aarch64 / ROS 2 Foxy

## 结论

项目源码的 Foxy launch 兼容修改已经离线完成：

1. `cleanup_system.launch.py` 已用 Foxy 支持的 `PythonExpression` 替换
   `AndSubstitution` 和 `NotSubstitution`，并阻止 mock 与 real perception
   同时启动。
2. 两个实机只读 launch 文件已直接传入 YAML 路径，不再依赖 Foxy
   不存在的 `ParameterFile`。
3. 默认模型路径已改为 `/home/agilex/limo_cleanup_ws/models/`，默认感知
   解释器改为 `python3`；WSL 烟测会显式覆盖开发机专用路径。
4. Ultralytics `8.3.21` 在 Python 3.8 上仍报告版本支持警告，但固定
   Python `3.8.10`、Jetson Torch `2.1.0a0+41361538.nv23.06` 的真实模型加载、
   两轮五图 CPU 推理和真实相机 detector/gate 已通过；该警告不再是当前阻塞。

除上述项外，项目 51 个 Python 文件均通过 Python 3.8 语法解析。Foxy 上项目使用的 `rclpy`、action、QoS、TF2、`ParameterValue(value_type=...)`、动态 `FindPackageShare` 和 `PathJoinSubstitution` API 均可用。

## 安全边界

本审计只读取操作系统、Python、ROS 包索引和环境变量。它不会：

- 启动底盘、机械臂、夹爪或相机驱动；
- 打开串口或 USB 设备；
- 发布话题、调用服务或发送 action；
- 修改 TF、udev、供电或执行机构配置。

`scripts/audit_foxy_runtime.sh` 默认也不查询 ROS 图。只有显式传入 `--check-graph` 时，才会执行一次有 10 秒上限、禁用 daemon 的只读 `ros2 topic list`。

## 实机盘点结果

| 项目 | 实机状态 | 判定 |
|---|---|---|
| Ubuntu / CPU | 20.04.6 / aarch64 | 通过 |
| ROS / Python | Foxy / 3.8.10 | 通过 |
| DDS | Domain 137、Cyclone DDS | 通过 |
| Cyclone 配置 | `/var/lib/theconstruct.rrl/cyclonedds.xml` 可读 | 通过 |
| ROS daemon | 1 个，Foxy + Cyclone + Domain 137 | 通过 |
| 原厂 ROS2 overlay | `/home/agilex/limo_ros2_ws/install/setup.bash` | 通过 |
| DaBai 驱动包 | `orbbec_camera`，仅 source 原厂 overlay 后可见 | 通过 |
| `astra_camera` | 未发现 | 不使用 |
| NumPy / OpenCV | 1.23.4 / 4.7.0 | 通过 |
| Torch | `2.1.0a0+41361538.nv23.06` | 两模型加载和 CPU 推理通过 |
| Ultralytics | `8.3.21`，保留 Python 3.8 支持警告 | 固定版本实测通过，不再阻塞 |
| Foxy launch API | 目标机缺上述三个 API；源码已改为兼容写法并新增回归测试 | 机器人复测通过 |

机器人当前稳定 DDS 配置为：

```bash
export ROS_DOMAIN_ID=137
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///var/lib/theconstruct.rrl/cyclonedds.xml
```

开发 WSL 先前使用 Domain 7。只有需要 WSL 与机器人跨机互通时，双方才必须使用一致的 Domain 和可互通的 DDS 配置；不要为了离线开发随意改动机器人当前稳定配置。

## Foxy 启动文件迁移（已实施）

当前代码已经采用以下 Humble/Foxy 兼容方式：

1. 使用 Foxy 已有的 `PythonExpression` 替换 `AndSubstitution` / `NotSubstitution`。
2. DaBai YAML 不包含 launch substitutions，直接把配置路径作为 Node parameter file 传入，不再使用 `ParameterFile(..., allow_substs=True)`。
3. 保留 `ParameterValue(..., value_type=...)`、动态 `FindPackageShare` 和 `PathJoinSubstitution`。
4. 新增 `test_foxy_launch_compat.py`，检查 Python 3.8 语法、禁止 API、launch 生成和 mock/real 排他条件。
5. Humble 离线构建、测试和 `--show-args` 已通过；Foxy/aarch64 实机复测也已完成。

已修改文件：

- `src/limo_cleanup_bringup/launch/cleanup_system.launch.py`
- `src/limo_cleanup_bringup/launch/hardware_readonly_acceptance.launch.py`
- `src/limo_cleanup_bringup/launch/real_perception_only.launch.py`

当前未发现 Foxy API 阻塞的启动文件：

- `dabai_camera.launch.py`
- `camera_extrinsics.launch.py`
- `gripper_control.launch.py`

## ARM64 感知运行时

仅把 `.pt` 改成 `.onnx` 文件名并不能消除 Ultralytics 依赖，因为当前 `dual_model_detector.py` 在模块加载时就执行 `from ultralytics import YOLO`。

以下是首次审计时的候选方案。当前交付基线已经选择并验证“固定现有 Python 3.8、Jetson
Torch 和 Ultralytics 8.3.21”，不再需要为了警告切换后端：

1. 优先方案：在独立 Python 3.8 环境中固定一个明确支持 Python 3.8、且与实机 Jetson Torch 兼容的 Ultralytics 版本，然后用两份实际模型各完成一次只读图片推理。不要直接升级实机的 Jetson Torch。
2. 备选方案：新增不导入 Ultralytics 的 ONNX Runtime 或 OpenCV DNN 后端。此方案改动更大，但能把 ROS Foxy Python 与训练环境解耦。

当前已完成两模型加载、CPU 五图推理和真实相机短时推理。以后若更换 Python、Torch、
Ultralytics、模型文件或推理设备，仍必须重新验证模型加载、首次推理内存峰值和两模型
并存内存，不能只用 import 成功作为放行依据。

当前主模型及 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `nongfu_yolov8n_best.pt` | `ABE7EAF409E3D24D255A627823F4B107A8884008AB659901C6C50479B2153512` |
| `trash_bin_yolov8n_best.pt` | `24BEB4A7941BA5D783F1937128B5F0F4307B035137889C78BE1993CAD76B8BC5` |
| `nongfu_yolov8n_best.onnx` | `873BC9A970E8F66C372B736B97D46252F9B4112B7393FDCA0AD0BD78431720C6` |
| `trash_bin_yolov8n_best.onnx` | `C9FA676D492DE1BB74868E907B60B7E0C3723181438B2FCCC832B4D5413E33E3` |

部署后应使用机器人上的稳定绝对路径，例如：

```text
/home/agilex/limo_cleanup_ws/models/nongfu_yolov8n_best.pt
/home/agilex/limo_cleanup_ws/models/trash_bin_yolov8n_best.pt
```

## 源码部署原则

Humble/x86_64 WSL 生成的 `build/`、`install/`、`log/` 和虚拟环境不能复制到 Foxy/aarch64。只传源码、配置、脚本、文档和模型，在机器人上重新解析依赖并构建。

建议传输集合：

```text
src/
scripts/
docs/
models/
.env.example
```

建议排除：

```text
build/
install/
log/
.venv/
venv/
__pycache__/
.pytest_cache/
```

机器人上的 source 顺序应固定为：

```bash
source /opt/ros/foxy/setup.bash
source /home/agilex/limo_ros2_ws/install/setup.bash
source /home/agilex/limo_cleanup_ws/install/setup.bash
```

在 launch API 和感知 Python 版本问题修复后，才执行有状态的依赖安装与构建：

```bash
cd /home/agilex/limo_cleanup_ws
rosdep install --from-paths src --ignore-src --rosdistro foxy -r -y
colcon build --symlink-install
source install/setup.bash
colcon test
colcon test-result --verbose
```

这些命令会安装依赖或写入工作区，不属于只读验收，应在代码审查和备份后单独执行。

## 只读审计用法

在机器人上审计基础 Foxy 与原厂 overlay：

```bash
cd /home/agilex/limo_cleanup_ws
bash scripts/audit_foxy_runtime.sh \
  --overlay /home/agilex/limo_ros2_ws/install/setup.bash \
  --project-root /home/agilex/limo_cleanup_ws \
  --require-perception
```

不传 `--require-perception` 时，Torch 和 Ultralytics 缺失只记为警告，适用于仅验证核心 ROS 包的场景。

## 到达“可接真实硬件”前的部署门槛

- Foxy 上所有 launch 文件可以导入并显示参数；
- 项目在 aarch64 上完成原生 `colcon build` 和测试；
- 模型路径不含 `/mnt/c/`；
- 固定并记录 Python、Torch、Ultralytics/推理后端版本；
- 两个模型在机器人上完成离线图片推理，不启动相机；
- `orbbec_camera` 从原厂 overlay 可见；
- 继续保持协作基线 Domain 137 + Cyclone DDS，除非另有经过验证的全局通信方案；
- 最后才由硬件验收窗口执行 TF、相机话题和只读握手检查。
