# LIMO Cleanup 源码基线快照（2026-08-11）

## 来源

- 原工作区：`/home/dyh/robotics/workspaces/limo_cleanup_ws`
- 工作副本：`C:\Users\DYH\Desktop\ai scout develop\limo_cleanup_ws`
- 只读归档：`C:\Users\DYH\Desktop\ai scout develop\limo_cleanup_ws_source_2026-08-11.tar.gz`
- 归档 SHA256：`EC5FBF510451ACD9A1588C1941A57EC85632EFEA5463170835159769AA043AC8`

归档保留 `.git`、已跟踪修改和未跟踪源码，排除了 `build/`、`install/`、`log/`、
`__pycache__/` 和 `.pytest_cache/`。原 WSL 工作区未被修改。

## Git 基线

- 分支：`main`
- HEAD：`40b3b74a33e0b5c4ee474985a3d7e7a62de1aa5b`
- HEAD 说明：`feat: add safe mycobot gripper control`
- 复制时状态项：`35`
- 已跟踪差异：`22` 个文件，约 `457 insertions / 96 deletions`

这些未提交内容包含 2026-08-08 已验收的相机、真实感知、Foxy 兼容、语音和
`touch_only` dry-run 工作。后续新增的履带底盘控制工作只在本工作副本中进行，验证完成前
不回写 WSL 或机器人。

## 当前动作安全边界

- 底盘运动默认禁用。
- 机械臂运动默认禁用。
- 夹爪控制器默认禁用。
- 不向真实 `/cmd_vel`、导航目标、机械臂或夹爪接口发布命令。
- 履带采用与四轮差速相同的滑移转向模型，只允许 `linear.x` 和 `angular.z`。
