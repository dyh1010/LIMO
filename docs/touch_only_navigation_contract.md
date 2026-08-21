# touch_only 导航站位接口基线

当前 `touch_only` 仍是 mock/dry-run。新增的
`limo_cleanup_executor.touch_standoff.plan_touch_standoff()` 只做二维几何计算，不创建 ROS
节点、不连接 Nav2、不发布速度，也不启动底盘或机械臂。

当前实机底盘由 ROS1 Noetic `limo_base_node` 唯一占用 `/dev/ttyTHS0`。ROS2 清理系统到
ROS1 的受限单向 bridge、catkin wrapper、ROS1 fail-closed watchdog 与私有
`/cleanup/base/driver_cmd_vel` 已在本地实现并通过离线测试；Catkin 构建、ROS1/ROS2
跨图运行、机器人全零、断链停车、状态/TF 和实机运动仍未验证，状态为
`ROS1_ROS2_BASE_BRIDGE_IMPLEMENTED_LOCALLY_UNVERIFIED`。旧 ROS2 vendor Stage 2/3 流程
只保留为历史诊断，不是导航执行路径。

## 输入契约

- 目标点必须先经已验收的 TF 转换到稳定导航坐标系 `map` 或 `odom`；当前 ROS1 → ROS2
  状态/TF bridge 未通过，因此该输入条件尚不成立；
- 当前 `base_link` 的 `robot_x/robot_y` 必须从同一时刻、同一坐标系的 TF/定位结果传入；
  禁止假设机器人位于 `map/odom` 原点；
- 禁止直接把 `camera_*`、`base_link` 或 `arm_base_link` 坐标传给导航；
- `standoff_distance` 必须由实测 `base_link -> arm_base`、软触碰头 TCP、机械臂安全可达范围
  和瓶子碰撞包络计算后显式传入；当前不提供默认值；
- 所有数值必须有限，目标距离必须大于站位距离和最小安全余量。

输出包含站位点 `goal_x/goal_y` 和朝向目标的 `goal_yaw`。该结果只是候选几何目标，不代表
碰撞检查、Nav2 可达性或机械臂可达性通过。

## 接入真实链路前的硬阻塞

1. `docs/ros1_ros2_base_bridge_contract.md` 第 1～5 级全部通过：ROS1 driver 唯一占用 UART、
   bridge/watchdog 离线契约、全零链、断链停车和单次短脉冲均已有证据；
2. 自动模式下公开 ROS1 `/cmd_vel` 无端点，ROS2 安全输出只能经受限单向 bridge、ROS1
   watchdog 和私有 `/cleanup/base/driver_cmd_vel` 到达 ROS1 `limo_base_node`；
3. ROS1 → ROS2 的 `/odom`、`/imu`、底盘状态、`/tf`、`/tf_static` 完成消息兼容和唯一
   TF owner 验收；`map -> odom` 只归定位 / SLAM，`odom -> base_link` 只归 ROS1 driver；
4. 实测 `base_link -> arm_base` 与触碰头 TCP，不使用照片目测外参；
5. 目标从相机坐标转换到 `map/odom`，并检查 TF 时间戳、bridge 新鲜度和检测新鲜度；
6. Nav2 只能向 ROS2 `/cleanup/base/cmd_vel_request` 请求速度，不得直接发布 ROS1
   `/cmd_vel`、私有 driver 话题或绕过安全网关；
7. Nav2 到站成功后撤销底盘运动授权，确认 ROS1 watchdog 输出持续全零且底盘锁止，
   再允许独立机械臂验收；
8. 无力/触觉传感器时只能报告“到达预定触碰位姿”，不能声称已确认物理接触。

当前不得把此模块接到真实 Nav2 action，也不得据此设置 `allow_base_motion=true` 或
`allow_arm_motion=true`。V1 不等待 bridge，可继续 mock/dry-run 与只读验收，但不包含真实
自动导航或底盘运动；任何底盘运动仍需当次通知现场人员并取得新的单次授权。
