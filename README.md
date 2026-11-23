# AI Agent Embedded Device Debugging Kit

面向 Codex 等 AI Agent 的桌面嵌入式设备自动化调试套装。工程统一组织视觉观察、机械操作、录像、测量及设备接口；**当前可用的是观察机械臂/USB相机 PoC 和离线工具，完整套装尚未交付**。

仓库由 `micropython-robot-arm` 更名，保留全部 Git 历史。现行地址：https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit 。已有克隆更新远端：

```sh
git remote set-url origin https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit.git
```

## 当前能用什么

|组件/能力|状态|入口|
|---|---|---|
|观察机械臂、夹爪|现有UART驱动、PC长连接、扫视及仿真；ok不是实测停稳|[驱动](drivers/micropython/robot_arm.py)、[会话](host_control/session.py)、[说明](docs/components/observer_arm.md)|
|USB相机、录像与观察窗口|共享JPEG/MJPEG采集、Tk监控及FFmpeg录像；已安装实际摄像头；双目/精确标定未验证|[camera](camera/server.py)、[录像](recording/recorder.py)、[监控](docs/setup/monitor.md)|
|线轨/滑台及综合控制器|规划；四轴步进+夹爪PWM、编码器、限位和保护并非现有UART库已实现|[线轨](docs/components/linear_stage.md)、[控制器](docs/components/stepper_servo_controller.md)|
|WS2812灯光|规划：补光、颜色/亮度及供电保护|[说明](docs/components/lighting.md)|
|电源/功耗|规划：USB/电池测量及被测设备断电重启|[说明](docs/components/power_meter.md)|
|USB音频|规划：成熟USB麦克风/扬声器直接连接PC|[说明](docs/components/audio.md)|
|MLX90640热成像|规划：温度矩阵、MicroPython接口及PC热图|[说明](docs/components/thermal.md)|
|Agent操作Skill|现有机械臂Skill；其他组件不冒称可用|[robot-arm-control](.agents/skills/robot-arm-control/SKILL.md)、[AGENTS](AGENTS.md)|
|绿色机械臂、桌面搭子|历史PoC，可选外部设备/仓库，不是主线安装前提|[历史示例](examples/historical_poc/README.md)|

## 最短安装和使用

PC需要Python；相机采集和录像需要FFmpeg，仿真需要Node.js进行检查。先枚举实际设备，不沿用历史COM端口。以下启动命令不发送运动指令。

```sh
git clone https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit.git
cd ai-agent-embedded-debugging-kit
python -m pip install -r requirements-pc.txt -r requirements-monitor.txt
python -m camera.server --device "2M"
```

第二个终端启动纯观察窗口（不需历史双绿臂依赖）：

```sh
python -m visual_observation
```

相机页面 http://127.0.0.1:8766/ ，快照 `/snapshot.jpg`。仿真与PC串口连接分别启动：

```sh
python -B simulator/serve.py
python -m host_control.session --port COM25
```

仿真页面 http://127.0.0.1:8767/ 。COM25只是示例，先确认实际设备。会话内 `G4 S0` 检查通信，`:snapshot` 取图，`:quit` 关闭连接并保留电机状态。使能、回零、移动和夹爪操作依据当前任务授权、现场状态及[Skill](.agents/skills/robot-arm-control/SKILL.md)执行。控制器回复与物理完成分开记录。

## 两条Agent观察路径

- **结构化数据**：相机 → 通用算法/设备适配 → JSONL → Agent。先安装 `requirements-vision.txt`；[通用轴线拟合库](perception/README.md)与[历史实验](examples/historical_poc/README.md)分别维护。`python -m observation.structured PATH/pose_stream.jsonl` 可读取已有结果，不调用模型API或设备控制。
- **直接多模态看图**：`python -m observation.multimodal --output .runtime/frame.jpg` 获取真实JPEG及元数据；Agent宿主打开/附加图片后分析。路径字符串不能代替图像输入，无需加载整套CV算法。元数据时间是PC接收时间，不冒称曝光时间。

两条路径通过帧/证据标识关联。完整流式契约、更多算法提取和统一设备SDK仍按后续实际交付推进，详见[观察接口](observation/README.md)。

## MicroPython单文件安装

保留 `robot_arm` 导入名和0.1.0清单，只安装驱动，不安装PC工具。

```python
import mip
mip.install("github:FreakStudioCN/ai-agent-embedded-debugging-kit")
from robot_arm import RobotArm
```

也可将根 `robot_arm.py` 复制到板端根目录或 `/lib/robot_arm.py`。维护源在 `drivers/micropython/robot_arm.py`；根文件及旧 `code/robot_arm.py` 是同步生成的独立副本。运行 `python tools/sync_driver.py` 同步。ESP32示例在[examples/micropython/main.py](examples/micropython/main.py)，仅导入不运动，显式调用main会使能并回零，须先修改现场接线。

## 内容放在哪里

|目录|内容|
|---|---|
|[hardware](hardware/README.md)、[firmware](firmware/README.md)|硬件范围、交付状态及设备端工程边界；未收到工程不建空板卡目录|
|drivers/micropython、host_control|驱动维护源、PC串口/事件/扫视|
|camera、recording、visual_observation、safety|共享采集、录像、显示与现有实验门禁|
|perception、observation|设备无关算法、结构化/直接图片交付|
|[mechanical](mechanical/README.md)|自研原生CAD/STEP/实际打印3MF、照片重建及原开源模型|
|examples|MicroPython示例和历史PoC，设备参数与实验编排不放通用算法库|
|docs/components、setup、experiments、archive|组件导航、安装使用、实验说明、历史记录|
|simulator、tests、tools、.agents/skills|仿真、检查、分发同步及Agent操作Skill|
|.runtime（忽略）|本机配置、日志、照片/视频及临时依赖；不提交凭据与原始录像|

## 模型、证据及兼容

- [当前试装模型](mechanical/observer_arm/gripper_camera_mount/README.md)：选定(2)包的14个SLDPRT、2个SLDASM、8个STEP以及实际打印3MF；[原生引用检查](mechanical/observer_arm/gripper_camera_mount/native-reference-check.json)。加载通过不等于实物尺寸、完整运动范围或第二套安装验收。
- [原开源机械臂](mechanical/upstream/community_robot_arm/PROVENANCE.md)：69文件固定提交、许可与散列保留；[照片重建模型](mechanical/photo_reconstruction/README.md)继续标记估算来源。
- [批准的整理方案](https://f1829ryac0m.feishu.cn/docx/Drwld0cIyoAFFuxuriXcLO6knMf)、[总任务](https://f1829ryac0m.feishu.cn/docx/Jwo1dIiAGoc7iUxGVMMcQfZrnGm)、[PoC视频](https://f1829ryac0m.feishu.cn/wiki/IWVXw7ahpiAuyckT0Qccio5ynNc)。
- 原根脚本、code/与cv_pipeline旧入口继续兼容；维护实现已迁移，避免复制两套业务逻辑。旧相机、串口和仿真命令保持可调用。更名及下载核验见[实际核验记录](docs/reorganization-verification.md)。

## 回归检查

```sh
python -B -m unittest discover -s tests -v
node simulator/check_math.mjs
node simulator/check_gripper.mjs
```

These checks are offline and do not constitute a new physical motion/accuracy test. 模型及第三方代码按各自来源许可证；本库MIT许可不覆盖第三方许可边界。
