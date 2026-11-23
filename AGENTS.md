# AI Agent Embedded Device Debugging Kit 工作区

本仓库组织完整AI Agent嵌入式设备自动化调试套装。当前可用观察臂、USB相机及离线工具；其他硬件按docs/components状态登记。绿色机械臂和桌面搭子仅为历史PoC。

- 实机操作、查看周围、夹爪调试和运动仿真先读取 `.agents/skills/robot-arm-control/SKILL.md`。
- 通用算法位于 `perception/`、双观察路径位于 `observation/`；设备专用CV/JSONL与恢复实现位于 `examples/historical_poc/`，`cv_pipeline/`保留兼容入口，原始画面观察入口位于 `visual_observation/`。新增导入使用包路径，根目录同名模块与 `tools/` 旧入口为兼容转发。相机、驱动、`experiment_safety.py` 和录像工具共用。
- 驱动实现位于 `drivers/micropython/robot_arm.py`，PC适配位于 `host_control/pc_uart.py`，长连接入口为 `host_control/session.py`。根目录同名脚本保留旧入口。`package.json` 保持 MicroPython 单文件安装。
- 根目录 `robot_arm.py` 与 `example.py` 保留可独立复制到 MicroPython 的分发副本。修改驱动维护源或 `examples/micropython/main.py` 后运行 `python tools/sync_driver.py`，测试会核对副本一致性。
- `simulator/index.html`、`simulator/gripper.html` 是 Codex 与用户共用的调试界面。结合其输入、参数与状态，以及摄像头和串口记录判断实机行为。
- 当前控制器的 `ok` 曾早于实际停稳。运动后等待并观察新鲜画面，确认稳定再继续。
- 按当前会话授权自主推进。用户要求自由观察或移动时，可以选择运动目标、范围和观察顺序，无需逐段重复确认。
- 修改代码后运行 `python -B -m unittest discover -s tests -v`、`node simulator/check_math.mjs`、`node simulator/check_gripper.mjs`。文档修改核对路径与示例。
- 运行照片与日志放 `.runtime/`。实拍资料和本机 CAD 依赖留在忽略目录。模型来源与许可证见 `simulator/README.md` 及上游目录。
