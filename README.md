# RobotArm 驱动与 Codex 观察调试环境

仓库统一维护 MicroPython UART 驱动、真实摄像头、HTML 三维仿真和 Codex 操作 skill。工作方式为观察、提出假设、执行小动作、等待停稳、再次观察并记录结论。

## 给 Codex 的入口

实时观看探索请运行 `python exploration_monitor.py` 或双击 `start_monitor.cmd`。这是独立 Tk 窗口，直接订阅现有 MJPEG 流并读取真实事件日志。按用户确认默认旋转180°，提供双语摘要、动作状态、时间线和事件回放。使用方法见 [监控说明](docs/monitor.md)。

打开本仓库后读取 [AGENTS.md](AGENTS.md) 与 [robot-arm-control skill](.agents/skills/robot-arm-control/SKILL.md)。可以直接给出“观察周围”“小步验证 X/Y/Z 方向”“对照实物调试夹爪”等目标。用户明确授权自主探索后，Codex 可以根据实时画面选择动作和观察顺序。

首次实体探索需一次确认无人进入活动范围、明确的小步安全路径和操作者可直接切断执行器电源。此后根据画面持续推进。历史测试目标和仿真参考范围需要结合当前现场使用。

## 目录

| 路径 | 用途 |
| --- | --- |
| `code/robot_arm.py` | MicroPython 单文件 UART 驱动 |
| `code/pc_control.py` | PCUART 与单条命令 CLI |
| `code/pc_session.py` | 持续串口会话、取图、等待与 JSONL 日志 |
| `code/main.py` | ESP32 示例，显式调用 main() 会使能并回零 |
| `camera_server.py` | FFmpeg 共享采集与 MJPEG/单帧接口 |
| `simulator/index.html` | 整机运动学、轨迹与摄像头调试界面 |
| `simulator/gripper.html` | 夹爪局部结构与开合调试 |
| `.agents/skills/robot-arm-control/` | Codex 自主观察与操作指导 |
| `docs/driver.md` | 驱动 API、接线、安装及错误处理 |
| `夹爪模型/重建模型/` | 参数化重建源码及尺寸假设 |
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

电脑语音可运行 `python code/pc_speech.py "你好，我是你的机械臂。"`，复用 Windows 已安装的中文 TTS 声音与默认音频输出。可用 `--voice`、`--output`、`--rate` 和 `--volume` 选择声音、设备、语速与合成音量。语音事件自动进入监控日志。

串口参数为115200/8N1。当前设备曾使用 COM23，运行前核对实际端口。程序启动只打开连接，在同一终端逐行输入。

```text
G4 S0
:status
:snapshot
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

## MicroPython 安装

将 `code/robot_arm.py` 复制到开发板根目录或 `/lib/robot_arm.py`，使用 `from robot_arm import RobotArm`。`package.json` 保持0.1.0驱动包路径，仅安装该模块。接线、电平注意事项与 API 见 [驱动文档](docs/driver.md)。

## 验证

图像局部位移分析可用 `python -m pip install -r requirements-vision.txt` 安装可选依赖，再运行 `python tools/compare_frames.py BEFORE.jpg AFTER.jpg --region X0 Y0 X1 Y1`。固定背景的像素变化辅助观察记录，物理到位仍需结合现场判断。

```powershell
python -B -m unittest discover -s tests -v
node simulator/check_math.mjs
node simulator/check_gripper.mjs
```

安装 `trimesh` 与 `manifold3d` 后，可运行 `python -B simulator/check_mount.py` 核对夹爪与腕部交集。参数化 CAD 重建需要 `cadquery-ocp-novtk`，本机的独立安装目录为 `夹爪模型/建模工具`。更多模型假设见重建 README。

## 模型与资料

模型来源、固定提交、校验值与第三方许可见 [仿真说明](simulator/README.md)。上游 CAD 和图形采用 CC BY 4.0，上游参考固件采用 GPL-3.0，Three.js 采用 MIT，各自许可文件随资源保留。根目录 MIT 适用于本项目原创代码，第三方材料遵循其各自许可。

实拍照片、摄像头历史抓帧、Word 建模委托文档、临时依赖和旧ZIP留在本机。夹爪和相机支架的照片及尺寸整理位于[建模需求云文档](https://f1829ryac0m.feishu.cn/docx/RSxudp1YDoLvPUx1OuncDcQJn7r)。相机十字形两组相对孔中心距17 mm由用户提供，其余照片估算尺寸待复核。
