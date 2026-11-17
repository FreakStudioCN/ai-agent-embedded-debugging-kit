# 画面观察与人工/Codex 判断

此入口显示摄像头画面，由操作者或 Codex 观察场景、判断运动与停稳，并记录观察、解释、下一步和结果。窗口读取串口动作及观察事件，支持时间线回放。

## 启动

从仓库根目录执行，复用现场已有相机服务。

```powershell
python -m pip install -r requirements-monitor.txt
python -m visual_observation --camera http://127.0.0.1:8768 --rotation 180
```

也可运行 `start_visual_observation.cmd`。默认显示原始画面。实际相机地址根据当前采集服务选择，参数通过 `python -m visual_observation --help` 查看。

观察摘要与 UART 事件仍使用 `.runtime/` 中的 JSONL，记录内容包括图像路径、发送指令、控制器回复和人工/Codex 判断。CV 工作流另有检测质量、角度有效性和参数版本等测量字段，详见 [CV 工作流](../cv_pipeline/README.md)。

交互串口使用 `code/pc_session.py`，动作与人工授权要求见 [操作 skill](../.agents/skills/robot-arm-control/SKILL.md)。相机采集使用 `camera_server.py`，多视角录像使用 `experiment_recorder.py`。

## 可选骨架叠加与旧入口

监控界面共用一套 UI。选用骨架叠加时安装 `requirements-cv.txt`，通过窗口开关或 `--skeleton` 启用 `cv_pipeline.monitor_pose` 工作线程。

旧 `python exploration_monitor.py`、`start_monitor.cmd` 继续采用原有骨架叠加默认设置。监控参数与操作说明见 [监控文档](../docs/monitor.md)。
