# 自主探索实验录像

`experiment_recorder.py` 独立运行，订阅现有 MJPEG 服务和 JSONL 事件，使用 FFmpeg 后台采集原生 Python 监控窗口。采集过程无需移动窗口。程序没有串口接口，运动仍由原控制会话负责。

## 开始与停止

先保持摄像头服务及独立监控窗口正常运行。监控窗口标题默认为 `具身探索监控台 · Embodied AI Monitor`。安装 FFmpeg、FFprobe，并使用已有监控程序的 Python 环境。

```powershell
python experiment_recorder.py record --output .runtime/recordings/my-session
```

另一个终端可通过文件请求正常封装并结束录像。也可以在录像终端按 Ctrl+C。

```powershell
New-Item -ItemType File .runtime/recordings/my-session/STOP
```

`--seconds 120` 可以设置录制时长。所有 FFmpeg 子进程在后台运行。相机画面使用原 MJPEG 编码复制，监控窗口使用低开销 H.264 编码，默认采集10 FPS。摄像头当前服务为1280×720、10 FPS。监控窗口应保持可见且未最小化，gdigrab 在最小化或窗口状态变化时可能失去有效内容。实际采集验证需要检查录下的画面。

## 外部机位

本次外部机位由操作者自行拍摄，之后提供原片。现阶段保存两路电脑端原始视频，清单中的 `external_pending` 保持为 true。外部原片到齐后，测量它的第一帧相对 `manifest.json` 中 `started_utc` 的秒数偏移。可以用两路均能看到的一次已记录机械动作起点对齐，并记录误差。正值表示外部视频比电脑端录制晚开始，负值表示更早。

下面的 `-3.5` 仅演示参数格式，使用时填写实测偏移。

```powershell
python experiment_recorder.py import-external .runtime/recordings/my-session C:/video/external.mp4 --offset -3.5 --evidence "根据共同可见动作起点对齐，估计误差0.1秒"
python experiment_recorder.py export .runtime/recordings/my-session --layout both
```

导入会复制完整原片并记录 SHA-256、原始路径、偏移及对齐依据。输出使用三路共同覆盖的时间区间。偏移错误会造成动作与字幕错位，软件不会自动推断手机文件的拍摄时钟。

有独立在线机位时，也支持 `record --external http://camera/live` 或 `--external dshow:设备名`。夹爪相机继续复用共享服务。

## 输出与同步

- `vision.mkv` 保存原始倒置的第一人称画面。
- `monitor.mkv` 保存整个真实监控窗口。导出时裁取右侧真实决策面板，与独立第一人称画面组合。
- `external-original.*` 保留后续导入的外部原片，在线外部机位保存为 `external.mkv`。
- `events.jsonl` 保存录制期间的原始事件及 UTC 时间戳。`context.jsonl` 单独保留开始前的上下文。`original-logs/` 保存结束时的原始日志副本，`frames/` 保存事件引用的照片。
- `manifest.json` 记录采集命令、UTC 起止、进程退出状态及媒体信息。出现采集失败会标记 failed 并停止其他录像进程。
- `landscape-three.mp4` 为1920×1080，`portrait-three.mp4` 为1080×1920。外部原片尚未提供时生成后缀 `-two.mp4` 的双路预览，并在报告中标记外部素材待补充。
- `.ass` 保存按真实事件生成的中英双语字幕。字幕区分指令发送、控制器回复和视觉确认停稳。历史事件不会加入本次字幕。
- 每个导出文件有同名 JSON 报告，记录导出起点 UTC、源视频及共同覆盖时长。画面显示该 UTC 起点和经过时长。

```powershell
python experiment_recorder.py export .runtime/recordings/my-session --layout both
python experiment_recorder.py export .runtime/recordings/my-session --layout landscape --start 20 --duration 60
python experiment_recorder.py verify .runtime/recordings/my-session
```

`verify` 对原始录像及导出视频逐帧解码，记录帧数、实际帧率、尺寸和事件时间范围，写入 `verification.json`。字幕保持最近一次真实公开摘要，并独立更新指令状态，便于同时阅读决策和随后收到的回复。

电脑端两路使用主机接收时间写入 Matroska PTS。相机曝光、USB 传输、UI 渲染与编码具有各自延迟，因此时间轴用于软件级同步。外部机位以实测偏移同步，保留误差说明。相机在成片中按用户已确认的180°方向显示。所有导出保留完整原始素材，支持重新剪辑。

## 与探索 Agent 配合

录像开始后，Agent 继续通过 `code/exploration_events.py` 发布当时的真实 observation、interpretation、next_action、result。长连接入口自动写入 sending 和 acknowledged。Agent 等待并比较新鲜画面后，写入包含准确指令和证据帧的 motion_verified。事件轮询与窗口录制在独立进程中运行。

快速扫视演示复用单路 USB 录像模式。可独立使用 `record --usb-only` 采集原片，再用 `export-usb <录像目录>` 导出正向 MP4。 [快速扫视](quick-scan.md)

本程序保留当前控制器的运动限制和原有安全流程。结束录像不会发送机械臂运动指令。视频及现场日志留在忽略目录 `.runtime/`。

## 90秒故事剪辑

先导入外部原片、生成横竖屏三画面母版，再使用实际录像选段计划剪辑。

```powershell
python experiment_recorder.py edit .runtime/recordings/first-day-20261116 --plan .runtime/recordings/first-day-20261116/story-plan.json --layout both
```

本次计划按用户提供的六段结构，总长90秒。0至5秒突出外部机位中的真实动作，5至15秒介绍身体与第一人称视角，15至30秒呈现桌面观察，30至50秒关联决策与运动，50至75秒由两段实际换角度及不确定性记录组成，75至90秒以真实结果和用户提供的问题结尾。

计划中的 `source_start` 是相对三画面母版开头的秒数，`duration` 为选段时长，`title_en`、`title_zh` 为双语剪辑文案，`view: body` 为外部机位开场特写。竖屏开场裁取机械臂末端所在区域。其余段落保留三画面和源 UTC，时间跳跃对应实际剪辑切点。每段按原速播放，原始事件摘要与编辑文案分别显示。

输出为 `story-90-landscape.mp4` 与 `story-90-portrait.mp4`。同名 JSON 保存每段源 UTC、剪辑时间、原始文件及 FFmpeg 命令，方便核对与修改。成片默认静音，导入的外部原片保留原始音轨。`verify` 同时检查故事剪辑和三画面母版。
