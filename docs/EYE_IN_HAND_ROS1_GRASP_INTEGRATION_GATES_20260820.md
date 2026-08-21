# ROS1/Noetic 双相机末端视觉抓取集成门

状态：`IMPLEMENTATION_IN_PROGRESS / REAL_ARM_EXECUTION_BLOCKED`

## 正确运行链路

```text
DaBai RGB-D（粗定位、瓶子身份、地面三维点）
  -> 时间同步与 RGB-depth 对齐
  -> base/arm_base 外参
  -> 可达性与预抓取候选
  -> JYU2C 腕部单目（盲区内重检测）
  -> 腕部内参 + flange-to-camera 手眼外参
  -> 地面约束/主相机三维先验 + 图像闭环
  -> IK、关节/地面/自碰撞检查
  -> 分段机械臂动作
  -> 最终重检测与夹爪闭合
  -> 抬升后视觉随动 + 夹爪反馈验证
```

YOLO 标签 `.txt` 只用于训练数据；Jetson 运行时加载冻结模型，并对实时图像执行推理。标签文件
不得作为运行时目标坐标输入。

## 当前真实完成度

| 门 | 当前状态 | 证据/缺口 |
|---|---|---|
| 主相机 ROS1 RGB-D | `BLOCKED_ALIGNMENT` | RGB `640x480`、depth `640x400`；depth align/sync 关闭，现有 adapter 正确拒绝 |
| 主相机 YOLO | `MODEL_EXISTS_DOMAIN_FALSE_POSITIVES` | 已冻结瓶模型，但真实腕部帧误检绿色夹爪且漏检瓶子 |
| 腕部相机身份/采集 | `PASS_READONLY_MAPPING` | 当前 JYU2C `1bcf:2281`、序列号 `JYU2C-2083-2603103`，稳定 by-id index0 当前解析到 `/dev/video2`；禁止用不稳定 `/dev/videoN` 绑定身份 |
| 腕部相机数据集 | `BLOCKED_INSUFFICIENT` | 只有单个候选正样本、30 帧高度相关手持参考和少量负样本；未冻结 train/val/test |
| 腕部相机内参 | `CANDIDATE_IDENTITY_REBIND_REQUIRED` | v2 腕部视角候选 K/D 已求解，但原 manifest 未机械绑定 by-id/VID/PID/实际节点，正式手眼输入仍阻塞 |
| 手眼外参 | `MISSING` | 无固定标定板、无多姿态 `T_base_flange` + `T_camera_target` 对 |
| 双相机时间/坐标交叉验证 | `MISSING` | 无共同时间基准和 `base_link -> arm_base_link` 实测变换 |
| 像素到机械臂坐标 | `BLOCKED` | 单目像素本身没有尺度；必须结合深度/地面平面和已验收外参 |
| ROS1 manipulation | `PREVIEW_ONLY` | 固定瓶位 core 输出五阶段预览；没有真实 adapter、IK/碰撞执行或硬件 STOP owner |
| 夹爪静态瓶夹持 | `PASS_SCOPED` | type=1, target=20, feedback=21, speed=30, protect_current=300, hold=15 s |

## 最小闭环顺序

1. **数据门**：采集腕部相机正样本（远/中/近、瓶身各旋转、不同光照）以及夹爪-only、空地面、
   鞋/桶/绿色结构等负样本；人工复核 YOLO 框；按采集 session 分 train/val/test，防止相邻视频帧泄漏。
2. **模型门**：在工作站训练/微调瓶子 detector；冻结模型、dataset manifest、类别表和推理阈值；
   在腕部独立 test session 上证明瓶召回和绿色夹爪误检门。
3. **Jetson 门**：转换并绑定 Jetson 实际 runtime 支持的模型格式，ROS1 节点发布 bbox、置信度、
   帧时间戳与模型 SHA；推理延迟和丢帧需实测。
4. **标定门**：固定已知尺寸的 ChArUco/棋盘；先标 JYU2C 内参，再用至少 10 个分散机械臂姿态
   求 `T_flange_camera`；用未参与求解的验证姿态报告像素重投影和三维误差。机械臂运动必须逐段授权。
5. **主相机门**：开启并验证 RGB-depth alignment/synchronization，补齐 CameraInfo frame ID，冻结
   `base/arm_base` 外参；发布可转换到 `arm_base_link` 的粗三维目标。
6. **融合与规划门**：主相机负责粗目标，腕部相机负责盲区重检测和 final alignment；所有目标必须
   新鲜、唯一、模型身份匹配。规划前验证 IK、关节限位、地面净空、夹爪/相机/线缆碰撞包络。
7. **执行门**：预抓取、接近、闭合、抬升分段执行；每段后重检测，任何失联、目标漂移、STOP
   不确定或反馈异常均物理隔离并禁止自动重试。

## 下一现场输入

正式手眼标定需要一个固定、已知格长的平面标定板。没有标定板时，可以继续采集/训练 YOLO，
但不能把腕部像素可靠转换成机械臂物理坐标。所需输入为：

- 打印好的 ChArUco/棋盘（平整粘贴），提供实际方格边长毫米值；
- 标定板固定在地面/刚性支架上，整个多姿态采集期间绝不移动；
- 机械臂扫掠区清空、底盘锁止、物理断能在手、观察员持续在场；
- 每一个非零姿态动作分别确认，先采图/姿态对，绝不直接进入抓瓶。
