# 双模型离线感知验证报告（2026-08-07）

## 目的

验证主任务规则：垃圾桶内部的瓶子属于已经投放完成的目标，应被忽略；桶外瓶仍应生成
抓取目标。此次只验证二维检测与空间过滤，不涉及深度、TF、底盘或机械臂控制。

## 模型与固定推理参数

```text
瓶模型：C:\Users\DYH\Desktop\limo_graphtest\models\nongfu_yolov8n_best.pt
桶模型：C:\Users\DYH\Desktop\limo_graphtest\models\trash_bin_yolov8n_best.pt
confidence: 0.5
NMS IoU:  0.45
逐图推理：是
```

桶内过滤最终参数：

```text
opening_height_ratio: 0.62
opening_margin_ratio: 0.0
in_bin_overlap:        0.30
```

规则为：瓶框中心位于垃圾桶框全宽的上部 62%，且瓶框与该区域的交叠面积达到瓶框面积
30% 以上，则标记为 `already_in_bin`，不发布为可执行目标。

## 调参过程

初始值 `height=0.55、margin=0.08` 在 `IMG_9030` 上未能过滤桶内瓶。瓶中心只比区域下边界
低约 59 像素。将高度增至 0.60 后 `IMG_9030` 正确过滤，但近距离俯视图中垃圾桶检测框
偏向一侧，水平内缩导致 `IMG_8985、IMG_8997` 漏过滤；取消水平内缩后两张均通过。
`IMG_8973` 的瓶中心高度比例约为 0.606，最终将高度设为 0.62。

作为安全对照，桶外瓶中最接近桶框上边缘的对应中心比例约为 0.86，仍与 0.62 保持明显
间隔。单图复验确认 `IMG_8973` 被过滤，而桶外 `IMG_9024` 继续保留。

## 最终结果

### 混合场景 70 张

```text
垃圾桶有检测：69
瓶子有检测：  24
桶内瓶过滤：   9
桶外活动瓶：  15
```

15 张活动瓶严格为：

```text
IMG_9014.JPG ～ IMG_9028.JPG
```

逐图目视确认它们均位于垃圾桶外，应该继续作为抓取目标。已知空桶样本
`IMG_8975.JPG、IMG_8979.JPG` 均为垃圾桶有检测、瓶子零检测。

### 桶外单瓶 54 张

```text
瓶子有检测：        46
保留活动目标：      46
错误过滤：           0
垃圾桶模型误检图片： 9
```

垃圾桶误检未与瓶目标形成满足规则的空间关系，因此没有误删任何桶外瓶。剩余 8 张为当前
v6 已知漏检，不属于空间过滤回归。

### 纯背景 24 张

```text
瓶子检测：   0
垃圾桶检测： 0
活动目标：   0
```

## 代码质量与构建

- Python 语法检查通过。
- `perception_core` 7 项单元测试全部通过。
- ament_flake8 检查通过，无问题。
- `limo_cleanup_perception` 与 `limo_cleanup_bringup` 使用 symlink install 构建通过。
- ROS2 包测试汇总为 38 tests、0 errors、0 failures、5 skipped。
- `ros2 pkg executables` 能列出 `dual_model_detector` 与 `offline_dual_detector`。
- `cleanup_system.launch.py --show-args` 参数解析通过；未启动真实节点或运动控制。

## 后台运行结论

单纯从 WSL shell 使用 `nohup` 后退出，Windows 可能回收没有宿主进程持有的 WSL 发行版，
因此后台任务不可靠。当前采用隐藏的 Windows `wsl.exe` 进程持有 worker，成功完成整批推理，
并分别记录 Windows PID、stdout 和 stderr。

## 限制与到货后复验

- 当前数据来自同一垃圾桶和办公室环境，不能代替车载低机位独立测试。
- 桶口仍是垃圾桶二维框的几何近似；实机相机视角变化后必须重新审核。
- RGB、对齐深度和 CameraInfo 到货后才能验证三维反投影。
- 二维过滤通过不代表抓取或投放闭环已完成；三维误差验收前继续使用模拟执行器。
