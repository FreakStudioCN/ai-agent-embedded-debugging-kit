# 独立探索监控窗口

## 启动

```powershell
python -m pip install -r requirements-monitor.txt
python exploration_monitor.py --rotation 180
```

也可双击 `start_monitor.cmd`。需要带 Tk 的 Python 安装。窗口直接读取 `http://127.0.0.1:8766/stream.mjpg`，后台线程持续接收 JPEG 帧，主线程约每30毫秒检查最新帧。单帧槽随新图覆盖，减少旧帧排队。保留流的原始采集尺寸和速率，显示时按窗口等比缩放。源服务当前为1280×720、10 FPS，后续可在相机服务调整采集参数。

180°方向已经由用户查看四种示意图确认。`--rotation` 支持0、90、180、270度，正数为逆时针。旋转仅作用于监控显示及回放，原始抓帧仍保留原方向。检测标注采用旋转后正向图像的归一化坐标。

窗口只订阅视频和本地日志，串口由 `code/pc_session.py` 独占。关闭窗口只结束显示。视频异常会标记离线或过期并重连，探索 Agent 根据画面和控制状态决定后续动作。

## 真实事件链路

监控增量读取 `.runtime/` 顶层所有 JSONL 文件。串口会话自动记录实际写入完成、控制器回复、等待、取图、异常和关闭事件。`sending` 表示整条命令已经写入 UART，`acknowledged` 表示收到 `ok`；两者均保留物理完成待确认状态。

Agent 在实际观察和计划时输出中英双语公开摘要。独立 CLI 只写事件，持续视频不依赖摘要发布速度。

```powershell
python code/exploration_events.py --event observation --text '实际观察内容' --text-en 'Actual observation'
python code/exploration_events.py --event interpretation --text '当前判断' --text-en 'Current interpretation'
python code/exploration_events.py --event next_action --text '下一步及简短理由' --text-en 'Next action and brief reason'
python code/exploration_events.py --event result --text '实际结果及不确定性' --text-en 'Observed result and uncertainty'
```

这些命令展示字段用法。正式会话填入该轮真实摘要。程序启动时仅显示等待状态，不生成探索内容。思考面板由 Agent 主动输出的可公开说明组成。

`motion_verified` 仅在 Agent 比较新鲜画面、判断当前动作实际停稳后发布。须关联准确指令与证据帧。新运动指令会重新进入待确认状态。

```powershell
python code/exploration_events.py --event motion_verified --text '实际停稳观察' --text-en 'Actual settling observation' --command '本轮准确指令' --frame '证据图片绝对路径'
```

Agent 应在同一个串口会话中逐次完成观察、判断、发布动作计划、发送指令、等待、再观察、记录结果。`ok` 的显示状态不会自动变成已停稳。当前没有精确位置反馈，左侧 XYZ 只合并实际发送过的指令轴，未提供的轴显示破折号。

## 标注格式

使用 `--data fields.json` 传入额外字段，包含 `target_en`、`annotations`、实验编号或视觉分析结果。`target` 可用 `--target` 指定。每个标注包含 `label`、`label_en` 和归一化矩形 `box=[x0,y0,x1,y1]`。该矩形相对于旋转后的完整图像，主窗口会按实际缩放定位。运动开始会清除旧标注，新的观察可重新发布。

## 日志与回放

原始串口与 Agent 事件完整写入 `.runtime/*.jsonl`，界面时间线为流畅显示限制可见行数，原始日志保留全部记录。日志时间存储为带时区 ISO8601，界面显示 UTC+8。

“保存事件回放 / Save replay”将本次已读取事件按时间合并到用户选择的 JSONL 文件。“打开回放 / Open replay”按原时间间隔重播事件，并显示事件关联的原始抓帧。保存的 JSONL 保留图像路径，因此迁移回放时需一并保留相应图片。

回放画面来源于已留存图片，实时模式持续接收视频流。点击“实时 / Live”返回当前事件状态和最新视频。回放、暂停及关闭窗口均不会发送机械臂指令。

## 测试

```powershell
python -B -m unittest discover -s tests -v
```

测试覆盖流帧解析、半行日志、增量去重、命令与回复和视觉停稳状态的区分。真实视频、双语摘要、实际串口事件、窗口缩放和回放另通过本机集成验证。
