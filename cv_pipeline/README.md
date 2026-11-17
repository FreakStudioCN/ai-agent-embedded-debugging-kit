# CV 识别与 JSONL 实验

图像由 OpenCV 后台处理，产生带质量与版本的测量记录，统计和实验代码读取这些记录进行决策。

## 目录与模块

| 模块 | 职责 |
| --- | --- |
| `contour_axis_2d.py` | 每帧轮廓分支、连杆候选、PCA/fitLine 轴角与拒绝门控 |
| `experiment_cv.py` | 后台 CV 流、姿态记录、窗口统计及旧 fused_pose 适配 |
| `monitor_pose.py` | 监控 UI 可选姿态叠加工作线程 |
| `experiment_runner.py`、`experiment_phases.py` | 实验组织、视角比较、响应与补偿统计 |
| `phase_r*.py`、`operator_homing.py` | 观察臂异常检测、重标定、恢复与人工门禁 |
| `recovery_*.py`、`verify_after_enable.py` | 恢复及状态检查工具 |
| `vision_lk.py`、`vision_subpixel.py`、`vision_fixed_reference.py`、`vision_planar_registration.py` | 历史视觉候选实现，供既有实验和回放使用 |
| `embodied_demo.py` | 历史双臂演示、串口会话适配与多视角采集 |
| `run_embodied_experiment.py` | 需要显式人工授权参数的实机实验入口 |
| `tools/` | 离线评估、ROI 重绘、报告、Phase R 验证及显式诊断工具 |

旧 fused_pose 依赖来自相邻仓库 `../Mr-Robot-Arm/mr_robot_desktop/`。轮廓检测模块可独立导入，历史比较器会按需加载该依赖。当前轮廓候选尚未通过实物测量验收，资格结论见 [算法说明](../docs/contour-axis-2d.md)。

## 从仓库根目录使用

```powershell
python -m pip install -r requirements-cv.txt
python -B -m cv_pipeline.tools.evaluate_contour_axis --quick
python -B -m cv_pipeline.tools.validate_contour_entities --output .runtime/<run_id>
python -B -m cv_pipeline.tools.render_contour_replay --output .runtime/<run_id>
```

每帧结果写入 `pose_stream.jsonl`，包含 `measurement_mode`、`parameter_version`、`calibration_version`、`detection_quality`、`geometry_quality`、`measurement_valid`、当前 ROI 和拒绝原因。无效角度为 `null`。实验事件写入 `experiment_events.jsonl`，录像与源码快照位于各次 `.runtime/<run_id>/`。

实机入口的参数可通过以下命令查看。

```powershell
python -B -m cv_pipeline.run_embodied_experiment --help
```

实际调用遵守 S0/S1 人工清场门禁、持久化 PAUSED/LOCKOUT 状态和 Phase R 恢复规则，流程见 [v1.1 任务书](../FreakStudio_Codex_Embodied_Debugging_Task_v1.1.md) 与 [恢复说明](../docs/phase-r-v11.md)。

## 维护与兼容

新增代码使用 `from cv_pipeline.contour_axis_2d import ContourAxisDetector` 等包路径。根目录同名模块将旧导入映射到同一模块对象，历史调用者和补丁操作可继续使用。`tools/evaluate_contour_axis.py` 等原脚本转发到本目录工具。

相机、驱动、安全层、录像和历史运行目录位于仓库共用位置。运行路径仍以仓库根目录解析，源文件路径反映当前包位置。整理前的运行记录和源码快照可用于复核历史版本。
