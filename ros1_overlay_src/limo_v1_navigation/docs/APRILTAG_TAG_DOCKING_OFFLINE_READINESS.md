# AprilTag 定点停靠：离线准备与明日开测顺序

本准备包只定义数据边界和离线校验，不启动 ROS、不订阅相机、不发布速度，也不生成底盘目标。

## 固定配置

- 场地基准：仅 `tag36h11` ID `0–3`，恰好四张；只能作为固定场地基准。
- 可移动目标面：仅 `tag52h13` ID `0–11`，恰好十二张。`0–3` 属于物体 0，`4–7` 属于物体 1，`8–11` 属于物体 2；每组依次为 `front/right/back/left`。
- 唯一映射为 `object_id = id // 4`、`side_index = id % 4`，且
  `0/1/2/3 = front/right/back/left`。规划侧复用视觉 contract 的同一常量；交换、重复、
  缺失、记录置换或 `side_0...side_3` 均为 `ABORT`。
- family 不符、ID 越界、重复 ID、少一个侧面、物体或侧面映射不匹配，均为 `ABORT`。固定 Tag 不能混入移动物体表。

## 视觉输出契约

`limo_apriltag_docking_observation/v1` 的成功结果必须包含：

- 指定的 `tag52h13` ID、确定的物体编号和侧面；
- `camera_color_optical_frame` 中的 Tag 平移和单位四元数；
- 同一时间戳的可见性、检测置信度、重投影误差；
- 同一时间戳的 `map -> base_link` 与 `base_link -> camera_color_optical_frame` TF 输入。

freshness 由 consumer 的可信 `host_now_ns` 所有，而不是 detector 自报的“当前时间”：仅当 `0 <= host_now_ns - timestamp_ns < 250000000` 时可接受；未来时间戳或年龄达到上限均为 `ABORT`。这与 V1 的 consumer-owned freshness 和“到期即 stale”语义一致。

契约不会输出或猜测 `map_pose`/`base_pose`。未来经授权的控制器只能使用上述 TF 输入自行变换。Tag 不可见、低置信度、高重投影误差、时间戳不一致、相机位姿无效或 TF/标定缺失时，结果必须为 `ABORT`，不得外推为成功。

规划 policy 不接受 detector 或调用方直接提供的 `pose_map`。唯一入口是 host-owned 纯软件 adapter：
它把同一条视觉 observation 的规范 SHA-256、target family/ID、camera-frame pose、同时间戳
`map -> base_link` 与 `base_link -> camera_color_optical_frame` TF 几何、consumer freshness 和
host-pinned calibration identity 绑定后，机械计算
`T_map_tag = T_map_base × T_base_camera × T_camera_tag`，只向 policy 交付 sealed
`BoundTagPose`。伪造/外置 map pose、把 camera pose 改名为 map、错误 TF 方向、来源交换、过期或
calibration SHA 不一致均为 `ABORT`。

`BoundTagPose` 的标量均为只读属性，pose 使用 `mappingproxy` 和 tuple 深不可变保存。adapter 在
构造时对 target、timestamp、age、confidence、calibration SHA、observation source SHA 和完整
pose 计算 canonical bound digest；policy 每次消费前重新计算并仅使用一次性 immutable snapshot。
公开字段修改、嵌套修改、输入 alias 后改写、seal 后内部篡改或 TOCTOU 均不能晚进入规划。

外参只有一个来源：完整严格校验后的 canonical calibration payload。identity 由该 payload 派生，
`base_link -> camera` TF 的 translation/orientation 必须与 payload 机械相等；仅 SHA 标签相同但
几何不同仍为 `ABORT`。V1 配置不再另存一份 identity/translation/rotation，只嵌入同一 canonical
payload，并在 `validate_config()` 时派生 immutable calibration binding。

## 现场录入模板与静态验收

在任何真实运动前填写 `config/apriltag_tag_docking_calibration_intake_template.json`：

1. 相机内参：camera frame、分辨率、`fx/fy/cx/cy`、畸变模型/非空系数和 `calibration_timestamp_ns`。
2. `base_link -> camera_color_optical_frame` 外参：parent/child frame、平移、单位四元数和 `calibration_timestamp_ns`。
3. Tag：固定/物体 Tag 实际尺寸、四张固定 Tag 各自的 map `(x,y,z,yaw)` 测量、三个物体的长宽高、物体 Tag 中心高度、平整、非反光、无遮挡、外向朝向检查。

模板中任一必填项为空即保持 `UNFILLED_ABORT`。纯离线静态验收命令（不需要 ROS）为：

```powershell
$py = 'C:\Users\DYH\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -B ros1_overlay_src/limo_v1_navigation/scripts/validate_apriltag_docking_static.py `
  --inventory ros1_overlay_src/limo_v1_navigation/config/apriltag_tag_docking_inventory.json `
  --observations ros1_overlay_src/limo_v1_navigation/fixtures/apriltag_static_observations_valid.json `
  --calibration ros1_overlay_src/limo_v1_navigation/fixtures/apriltag_tag_docking_calibration_ready.json `
  --host-now-ns 1234567990 `
  --max-observation-age-ns 250000000
```

返回 `ACCEPT` 仅表示离线数据格式成立，`motion_authorized` 始终为 `false`。

完整规划配置由 `load_config()` 使用 strict JSON 读取：重复键、NaN/Infinity、尾随第二个 JSON
值均拒绝；field/object/tag/side 的 ID 必须是精确 JSON integer，布尔值不能冒充 `0/1`。

严格门不会把“有 6 个内参数数字和 3+4 个外参数字”当成标定就绪。输入必须完整匹配
`limo_apriltag_docking_calibration_intake/v1`：状态为 `RECORDED`，frame、分辨率、畸变模型与
系数、consumer 可核验的正时间戳、`base_link -> camera_color_optical_frame` 单位四元数、四张
`tag36h11` 的已验证 map 测量、三件物体的已验证长宽高、Tag 尺寸/中心高度和四项安装检查均
缺一不可。任何必填字段删除、`null`、错误类型或必须为真的检查项为 `false` 时均为 `ABORT`。

组合 consumer 必须显式传入可信 `host_now_ns` 与正数 `max_observation_age_ns`。即使 observation
和两条 TF 使用完全相同的时间戳，只要该时间戳已旧，仍必须 `ABORT`；时间戳同步不能替代新鲜度。
纯软件回归入口为：

```powershell
& $py -B ros1_overlay_src/limo_v1_navigation/test/test_apriltag_docking_contract.py -v
```

## 明日严格顺序

1. 静态检测：核对 family/ID/四侧面、Tag 实测尺寸、平整度、照明和遮挡；底盘保持静止。
2. 标定核验：录入并验证内参、外参与四张固定 `tag36h11` 的 map 测量值；缺任何一项即 `ABORT`。
3. 预靠近：另行获得现场运动授权后，导航仅到目标可见面前方 `0.8–1.0 m`；固定 Tag 仅做定位交叉核验。
4. 视觉精停靠：仅当目标 `tag52h13` 持续可见且契约 `ACCEPT` 时，进行最后一段到相机—Tag 平面 `0.40 m` 的低速精对准。
5. 保持与记录：记录最终距离、横向/yaw 误差和任何 `ABORT` 原因。首轮不要求自由避障或通用物体识别准确率。

任何 Tag 丢失、低质量、超时、围栏预测越界或数据契约失败，都必须停止并报告 `ABORT`；本离线包不包含控制逻辑。
