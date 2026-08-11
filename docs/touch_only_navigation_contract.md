# touch_only 导航站位接口基线

当前 `touch_only` 仍是 mock/dry-run。新增的
`limo_cleanup_executor.touch_standoff.plan_touch_standoff()` 只做二维几何计算，不创建 ROS
节点、不连接 Nav2、不发布速度，也不启动底盘或机械臂。

## 输入契约

- 目标点必须先经 TF 转换到稳定导航坐标系 `map` 或 `odom`；
- 当前 `base_link` 的 `robot_x/robot_y` 必须从同一时刻、同一坐标系的 TF/定位结果传入；
  禁止假设机器人位于 `map/odom` 原点；
- 禁止直接把 `camera_*`、`base_link` 或 `arm_base_link` 坐标传给导航；
- `standoff_distance` 必须由实测 `base_link -> arm_base`、软触碰头 TCP、机械臂安全可达范围
  和瓶子碰撞包络计算后显式传入；当前不提供默认值；
- 所有数值必须有限，目标距离必须大于站位距离和最小安全余量。

输出包含站位点 `goal_x/goal_y` 和朝向目标的 `goal_yaw`。该结果只是候选几何目标，不代表
碰撞检查、Nav2 可达性或机械臂可达性通过。

## 接入真实链路前的硬阻塞

1. 履带 Stage 0～4 分级验收通过，底盘停车和唯一命令链已验证；
2. 实测 `base_link -> arm_base` 与触碰头 TCP，不使用照片目测外参；
3. 目标从相机坐标转换到 `map/odom`，并检查 TF 时间戳和检测新鲜度；
4. Nav2 到站成功后撤销底盘运动授权，确认底盘锁止，再允许独立机械臂验收；
5. 无力/触觉传感器时只能报告“到达预定触碰位姿”，不能声称已确认物理接触。

当前不得把此模块接到真实 Nav2 action，也不得据此设置 `allow_base_motion=true` 或
`allow_arm_motion=true`。
