# 机械臂工作区

本仓库将 MicroPython UART 驱动、实机摄像头、HTML 仿真和 Codex 操作技能放在同一版本历史中。

- 实机操作、查看周围、夹爪调试和运动仿真先读取 `.agents/skills/robot-arm-control/SKILL.md`。
- 驱动实现位于 `code/robot_arm.py`，PC 适配位于 `code/pc_control.py`，长连接入口为 `code/pc_session.py`。根目录同名脚本保留旧入口。`package.json` 保持 MicroPython 单文件安装。
- 根目录 `robot_arm.py` 与 `example.py` 保留可独立复制到 MicroPython 的分发副本。修改 `code/` 对应源码后运行 `python tools/sync_driver.py`，测试会核对副本一致性。
- `simulator/index.html`、`simulator/gripper.html` 是 Codex 与用户共用的调试界面。结合其输入、参数与状态，以及摄像头和串口记录判断实机行为。
- 当前控制器的 `ok` 曾早于实际停稳。运动后等待并观察新鲜画面，确认稳定再继续。
- 按当前会话授权自主推进。用户要求自由观察或移动时，可以选择运动目标、范围和观察顺序，无需逐段重复确认。
- 修改代码后运行 `python -B -m unittest discover -s tests -v`、`node simulator/check_math.mjs`、`node simulator/check_gripper.mjs`。文档修改核对路径与示例。
- 运行照片与日志放 `.runtime/`。实拍资料和本机 CAD 依赖留在忽略目录。模型来源与许可证见 `simulator/README.md` 及上游目录。
