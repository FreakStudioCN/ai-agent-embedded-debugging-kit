# RobotArm 驱动与 Codex 观察调试环境

仓库统一维护 MicroPython UART 驱动、真实摄像头、HTML 三维仿真和 Codex 操作 skill。工作方式为观察、提出假设、执行小动作、等待停稳、再次观察并记录结论。

## 选择视觉工作流

| 工作流 | 源码与说明 | 入口 | 主要输出 |
| --- | --- | --- | --- |
| CV 识别与 JSONL 实验 | [cv_pipeline/](cv_pipeline/README.md) | `python -m cv_pipeline.tools.evaluate_contour_axis --quick` | 当前帧检测、质量、有效性、版本化 JSONL、叠加录像与实验报告 |
| 画面观察与人工/Codex 判断 | [visual_observation/](visual_observation/README.md) | `python -m visual_observation` 或 `start_visual_observation.cmd` | 摄像头画面、观察摘要、串口动作事件与回放 |

CV 工作流收纳轮廓主轴、旧 fused_pose 适配、LK 等视觉实现，以及 Phase 0–3、Phase R 和恢复入口。画面观察入口默认显示原始画面，观察与决策由操作者或 Codex 完成。两者共用相机服务、串口驱动、录像工具和 `experiment_safety.py` 安全层。

根目录同名 Python 文件与 `tools/` 中的旧 CV 脚本提供兼容转发，实际维护位置在上述目录。旧 `exploration_monitor.py` 与 `start_monitor.cmd` 保留原有骨架叠加默认行为，纯画面入口使用 `python -m visual_observation`。

## 给 Codex 的入口

实时观看探索请运行 `python exploration_monitor.py` 或双击 `start_monitor.cmd`。这是独立 Tk 窗口，直接订阅现有 MJPEG 流并读取真实事件日志。按用户确认默认旋转180°，提供双语摘要、动作状态、时间线和事件回放。使用方法见 [监控说明](docs/monitor.md)。

双绿臂表演与观察臂多机位采集使用 `embodied_demo.py`。本机接线、准备态、复现命令、实测误差和三路录像见 [实机演示记录](docs/embodied-demo.md)。

打开本仓库后读取 [AGENTS.md](AGENTS.md) 与 [robot-arm-control skill](.agents/skills/robot-arm-control/SKILL.md)。可以直接给出“观察周围”“小步验证 X/Y/Z 方向”“对照实物调试夹爪”等目标。用户明确授权自主探索后，Codex 可以根据实时画面选择动作和观察顺序。

首次实体探索需一次确认无人进入活动范围、明确的小步安全路径和操作者可直接切断执行器电源。此后根据画面持续推进。历史测试目标和仿真参考范围需要结合当前现场使用。

## 目录

| 路径 | 用途 |
| --- | --- |
| `code/robot_arm.py` | MicroPython 单文件 UART 驱动 |
| `code/pc_control.py` | PCUART 与单条命令 CLI |
| `code/pc_session.py` | 持续串口会话、取图、等待与 JSONL 日志 |
| `code/main.py` | ESP32 示例，显式调用 main() 会使能并回零 |
| `cv_pipeline/` | CV 识别、JSONL 测量、实验阶段、恢复及离线验证 |
| `visual_observation/` | 画面观察监控窗口与入口 |
| `experiment_safety.py` | 共用安全门禁与硬件限位 |
| `experiment_recorder.py` | 共用多视角录像与导出 |
| `camera_server.py` | FFmpeg 共享采集与 MJPEG/单帧接口 |
| `simulator/index.html` | 整机运动学、轨迹与摄像头调试界面 |
| `simulator/gripper.html` | 夹爪局部结构与开合调试 |
| `.agents/skills/robot-arm-control/` | Codex 自主观察与操作指导 |
| `docs/driver.md` | 驱动 API、接线、安装及错误处理 |
| `simulator/models/custom_gripper/` | 夹爪模型、参数化建模源码及尺寸假设 |
| `.runtime/` | 本机运行日志与照片，Git 忽略 |

根目录 `robot_arm.py`、`example.py` 保留可独立复制到 MicroPython 的分发副本。源码维护在 `code/`，修改后运行 `python tools/sync_driver.py` 同步，测试会核对一致性。根目录 `pc_control.py` 加载 `code/` 实现。原 `robot_arm_driver/` 内容保留为本机旧副本并被 Git 忽略，Git 历史及 origin 已迁入当前根目录。

## 启动调试环境

安装 Python、pyserial，摄像头另需 PATH 中有 FFmpeg。仿真检查需要 Node.js。

```powershell
python -m pip install -r requirements-pc.txt
python -B camera_server.py
```

在其他终端启动仿真与交互串口。

```powershell
python -B simulator/serve.py
python -u code/pc_session.py --port COM23
```

相机默认设备 `2M`、1280×720、10 FPS，可用 `--device`、`--width`、`--fps` 调整。已有采集服务时复用它。

- 摄像头页面为 http://127.0.0.1:8766/ 。
- 单帧接口为 http://127.0.0.1:8766/snapshot.jpg 。
- 状态接口为 http://127.0.0.1:8766/api/status 。
- 整机仿真为 http://127.0.0.1:8767/ ，夹爪页为 http://127.0.0.1:8767/gripper.html 。

HTML 中的动作控制用于仿真，实物通过串口会话操作。界面、skill 和 UART 日志构成同一调试环境。

## 交互串口

串口参数为115200/8N1。当前设备曾使用 COM23，运行前核对实际端口。程序启动只打开连接，在同一终端逐行输入。

```text
G4 S0
:status
:snapshot
:scan
:wait 5
:await
:quit
```

`G4 S0` 检查通信，`:snapshot` 保存新图并返回绝对路径，`:await` 继续等候超时指令的原回复。`:quit` 释放串口，保持电机状态。可以输入单行 G/M 指令，或将指令与等待组合。

```json
{"command":"G1 X5 F5","settle":5}
```

这个目标只是语法示例。实体动作按当前授权与实际路径选择。`M17` 使能电机，`G28` 回零；回零路径明确安全后再执行。`M3` 闭合、`M5` 打开夹爪。XYZ 为毫米，F 为毫米每秒且最小5，I/J 为即时角度目标。详细 IO/12V 等接口见驱动文档。

2026-11-16 实测曾在收到 `ok` 后观察到继续移动。回复、等待时间与视觉停稳分别记录。程序输出 `physical_completion=unverified`，实际完成需结合新鲜画面确认。当前资料没有位置反馈与已确认的硬件急停指令，目标坐标只能作为指令记录。

同一端口保持一个调用者，每次一条运动指令。超时保留 pending 状态，查看画面并等待原回复。120秒 UART 超时用于停止等待回复并阻止后续发送，无法停止已在执行的物理动作。

桌面观察可以在同一个串口会话中输入「快速扫一圈」或 `:scan`，自动沿标定路线移动、取图并保存逐方向报告。 [快速扫视](docs/quick-scan.md)

输入 `:dynamic` 或「双设备动态演示」可以录制机械臂与 MttoRobot 的联动，同时保存 USB 原画和具身探索监控台录屏。 [双设备动态演示](docs/quick-scan.md#双设备动态演示)

## MicroPython 安装

将 `code/robot_arm.py` 复制到开发板根目录或 `/lib/robot_arm.py`，使用 `from robot_arm import RobotArm`。`package.json` 保持0.1.0驱动包路径，仅安装该模块。接线、电平注意事项与 API 见 [驱动文档](docs/driver.md)。

## 验证

图像局部位移分析可用 `python -m pip install -r requirements-vision.txt` 安装可选依赖，再运行 `python tools/compare_frames.py BEFORE.jpg AFTER.jpg --region X0 Y0 X1 Y1`。固定背景的像素变化辅助观察记录，物理到位仍需结合现场判断。

```powershell
python -B -m unittest discover -s tests -v
node simulator/check_math.mjs
node simulator/check_gripper.mjs
```

安装 `trimesh` 与 `manifold3d` 后，可运行 `python -B simulator/check_mount.py` 核对夹爪与腕部交集。参数化 CAD 重建需要 `cadquery-ocp-novtk`，生成命令及模型假设见 [夹爪建模说明](simulator/models/custom_gripper/README.md)。

## 模型与资料

模型来源、固定提交、校验值与第三方许可见 [仿真说明](simulator/README.md)。上游 CAD 和图形采用 CC BY 4.0，上游参考固件采用 GPL-3.0，Three.js 采用 MIT，各自许可文件随资源保留。根目录 MIT 适用于本项目原创代码，第三方材料遵循其各自许可。

本地实拍照片、建模委托资料、运行录像、临时依赖和旧 ZIP 通过 `.gitignore` 排除。相机十字形两组相对孔中心距17 mm由用户提供，其余照片估算尺寸待复核。
