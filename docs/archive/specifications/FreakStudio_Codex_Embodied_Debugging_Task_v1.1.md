# FreakStudio：Codex 具身智能闭环调试最终任务书

版本：v1.1（2026-11-17；新增 Phase R 异常位移恢复）
模式：B — Codex 自主设计与执行实验
目标：实机验证“自主选视角 → CV 结构化测量 → 偏差检测 → 自主补偿 → 同条件复测”的闭环，并在异常位移后执行可审计的安全恢复。**本任务授权在既有安全边界内开展实验，不授权修改安全边界。**

## 0. 执行总原则

你（Codex）是实验设计者、控制者和分析者。先读取并复用仓库既有代码与安全约束，尽量小幅增量修改；不要从零重写驱动或视觉系统。你可自行选择具体 CV 处理、观察机位、测试顺序、补偿策略与重试次数，但须完成下列验收、留证和停机条件。不要凭人类目测答案反推结果；不要把图像平面角度冒充真实绝对关节角。

**严禁在人工确认清场前使能、回零、移动任何实机机械臂。**启动先进入只读 S0，输出实机预检结果，等待操作者明确批准 S0→S1。批准仅适用于本次会话、已核准设备及既定安全范围；断开、重启或异常后重新授权。

## 1. 工作目录和需要复用的资产

- 主项目：`C:\Users\ZYS20\Desktop\FreakStudio\ROBOT`
  - 串口控制驱动与安全控制层；`exploration_monitor.py`（监控界面）；`experiment_recorder.py`（实验录像）；`embodied_demo.py`；仓库内 `robot-arm-control` 技能/说明。
- 依赖项目：`C:\Users\ZYS20\Desktop\FreakStudio\Mr-Robot-Arm`
  - `mr_robot/dual_arm.py`（双绿臂驱动与安全窗口）；`dual_wiring.py`（实际映射，定位后读取）；`fused_pose.py`（绿色分割、骨架、四孔 PnP 融合）；`second_arm_calibration.json`（绿臂 2 校准配置，定位后读取）。
- 操作前搜索并检查仓库的 `AGENTS.md`、硬件安全文档、串口指令的当前实现与上述文件。文件位置不一致时定位实际文件，**报告差异，不猜测接口**。
- 这些 Windows 路径位于操作者本地机器；如果当前运行环境无法访问 Windows COM 口或文件路径，只做静态准备并报告阻塞，禁止以模拟成功冒充实测。

## 2. 锁定的硬件拓扑（不可重映射）

| 设备 | 接口/身份 | 固定参数 | 作用 |
|---|---|---|---|
| 大机械臂/观察臂 | `COM3` | `M17` 使能、`G28` 回零、`G1` 运动 | 携带局部观察相机；须先人工清场 |
| 双绿臂共享控制器 | `COM8` | ESP32-C3，UID `70af092aeee8` | 向 PCA9685 发送 PWM counts |
| I²C / PWM 控制器 | `I2C(0, scl=Pin(9), sda=Pin(10))` | PCA9685 `0x4F`，预分频 `121`，`50 Hz` | 双绿臂共用，不得改变频率 |
| 夹爪 USB 相机 | `http://127.0.0.1:8768` | 1280×720，约 10 FPS；图像旋转 **180°** 后分析 | 随观察臂移动的局部视角 |
| 外部全局 USB 相机 | `http://127.0.0.1:8769` | 1280×720，约 15 FPS | 固定全局观察、安全及对照 |

### 2.1 已验证映射及软件参考零位

| 关节 | 绿臂 1 PCA 通道 | 绿臂 1 参考零位（counts） | 绿臂 2 PCA 通道 | 绿臂 2 参考零位（counts） |
|---|---:|---:|---:|---:|
| Base 底座 | CH12 | 307 | CH11 | 307 |
| Shoulder 肩部 | CH13 | 287 | CH10 | 307 |
| Elbow 肘部 | CH14 | 297 | CH9 | 307 |
| Gripper 夹爪 | CH15 | **从代码核实；本轮默认不动作** | CH8 | **从代码核实；本轮默认不动作** |

上述 counts 是**软件参考零位，不是绝对角度，也不是限位值**。实测安全窗口和速度限制必须从 `mr_robot/dual_arm.py`、`second_arm_calibration.json` 等现有配置读取（历史示例：底座 297–357、肩/肘 297–337 counts，仅为例子，绝不据此覆盖实际配置）。驱动与配置不一致时采取更保守的交集，停止自动运动并向人报告待确认差异。除已映射 CH8–CH15 外，不允许触及其他 PCA 通道，特别是 CH0–CH7。

绿臂 2 的底座、肩、肘均观察到换向回差；本轮仅选择**单个俯仰关节**进行辨识与补偿，优先 CH9 肘部或 CH10 肩部（依据图像可观测性自主选择），其他关节保持经过安全确认的软件参考位置。请勿自行驱动夹爪。

### 2.2 观察臂机位

只允许使用现有 `robot-arm-control` 安全控制层及 `embodied_demo.py` 已验证的安全工作空间和预设机位。已知例子 `X0 Y164 Z120`，**不能仅凭此示例推断其他安全机位**。从仓库提取有效机位列表，若不足 2 个则报告限制，不自行创造未经验证的轨迹；任何两点间移动的整条路径亦必须由既有安全控制层判定安全。禁止修改安全工作空间、速度限制、回零逻辑和动作拦截逻辑。

## 3. 架构与 LLM 看图策略

1. **硬件层**：COM3 观察臂、COM8 双绿臂、两路摄像头。
2. **执行与安全层**：复用串口驱动、限位、运动超时、人工授权门禁、录像与监控组件；只有通过此层才能请求硬件运动。
3. **CV 层**：后台持续处理相机流，复用 `fused_pose.py`，输出高频结构化测量和事件统计。默认无人看图/LLM 看图。
4. **Codex 决策层**：只使用 JSONL 的有效窗口统计进行常规实验决策、误差计算与调参；不逐帧读图、不把视频帧灌入模型上下文。

所谓“95% CV / 5% 关键看图”是**运行方式约束**，不是随机每 20 帧看 1 帧。仅允许在：(a) 动作前清场核查；(b) 持续低置信度/跟踪报错或双摄矛盾时排障；(c) 每轮结束成果抽检时，看少量有时间戳的关键图。每次记录 `image_inspection` 事件、触发原因、帧路径及数量。禁止把人工视觉判断替换为正式角度测量。

## 4. `.runtime/` 文件与 JSONL 规范

运行输出统一放到主项目 `.runtime/`，为每次执行生成唯一 `run_id`，所有文件可追溯。JSONL 每行是一个独立 JSON 对象，使用 UTF-8，包含 `schema_version`、`run_id`；时间同时记录 UTC ISO8601 `timestamp_utc` 与单调时钟 `monotonic_ms`（计算时序以单调时钟为准）。无效数据用 `null` 和 `invalid_reason`，不要伪造数值。

### 4.1 `.runtime/<run_id>/pose_stream.jsonl`

按 `camera_id × arm_id × frame` 输出测量（必要时可降采样写盘，但 CV 实时处理不中断）：

| 字段 | 类型 | 必需含义 |
|---|---|---|
| `schema_version`, `run_id` | string | 数据协议版本、实验 ID |
| `timestamp_utc`, `monotonic_ms`, `frame_id` | string, number, int | 时间与帧顺序 |
| `camera_id` | enum | `wrist_8768` / `global_8769` |
| `camera_pose_id`, `camera_moving` | string, bool | 当前视角和观察臂运动标志 |
| `calibration_version` | string | 对应的视觉基线版本；任何 Rebase 后变更 |
| `arm_id`, `motion_id` | string, string/null | `green_1` / `green_2`；指令关联 |
| `track_valid`, `invalid_reason` | bool, string/null | 跟踪有效性；遮挡、丢帧、PnP 失败等 |
| `keypoints_px` | object | 命名关节 `base/shoulder/elbow/tip` 的 `[x,y]` 或 null；坐标以已旋转的分析帧为准 |
| `link_angles_deg` | object | 图像平面连杆方向；明确角度零方向及正方向 |
| `joint_angles_deg` | object | 可观测的**近似/投影**关节角；不可观测则 null |
| `measurement_mode` | enum | `2d_projected` / `pnp_derived` / 其他有定义模式 |
| `rms_px` | float/null | 四孔重投影 RMS；无 PnP 解时 null，不能等同于 0 |
| `confidence` | float/null | 0–1；须在代码文档写明算法及阈值含义 |
| `is_stationary` | bool | 窗口停稳状态，非单帧主观判断 |

例子（**示意值，非实测**）：

```json
{"schema_version":"1.0","run_id":"run_001","timestamp_utc":"2026-11-17T08:00:00Z","monotonic_ms":123456,"frame_id":1842,"camera_id":"wrist_8768","camera_pose_id":"view_02","camera_moving":false,"arm_id":"green_2","motion_id":"trial_003","track_valid":true,"invalid_reason":null,"keypoints_px":{"base":[420.1,356.2],"shoulder":[433.0,328.0],"elbow":[461.5,281.4],"tip":[493.2,218.9]},"link_angles_deg":{"upper":-61.0,"forearm":-63.1},"joint_angles_deg":{"elbow":2.1},"measurement_mode":"2d_projected","rms_px":2.4,"confidence":0.91,"is_stationary":true}
```

### 4.2 `.runtime/<run_id>/experiment_events.jsonl`

事件统一有 `schema_version`, `run_id`, `timestamp_utc`, `monotonic_ms`, `event`, `motion_id`（可 null）、`details`。应支持：

- `preflight`、`human_clearance_requested`、`human_clearance_granted`、`human_clearance_denied`、`safety_pause`、`resume_authorized`、`abort`；人工授权事件记录操作者确认与本次授权范围，**不可自动生成批准**。
- `move_requested`、`move_accepted`、`move_rejected`、`move_started`、`move_completed`、`move_timeout`；记录设备、关节/通道、起始与目标 PWM counts、方向、限速、参数版本、指令时间和安全检查结果。
- `camera_view_selected`、`camera_move_started`、`camera_move_completed`、`image_inspection`。
- `settled_measurement`、`settle_timeout`、`tracking_failure`、`measurement_conflict`。
- `parameter_proposed`、`parameter_applied`、`parameter_rolled_back`、`trial_result`、`phase_result`。
- Phase R 事件：`observer_drift_suspected`、`observer_drift_confirmed`、`recovery_started`、`visual_rebase_started`、`visual_rebase_completed`、`visual_rebase_failed`、`recovery_lockout`、`recovery_authorized`、`experiment_baseline_invalidated`、`experiment_resumed`。所有恢复事件含 `calibration_version`、`recovery_state`、`attempt_id` 和相应证据字段。

`settled_measurement.details` 至少包含：`camera_id`, `camera_pose_id`, `calibration_version`, `arm_id`, `joint`, `pwm_counts`, `approach_direction`, `window_ms`, `valid_frames`, `valid_ratio`, `confidence_median`, `rms_px_median`, `angle_median_deg`, `angle_std_deg`, `angle_drift_deg_per_s`, `stationary`, `measurement_mode`, `parameter_version`。多摄像头不混算均值。另记录该窗口与运动完成之间的延迟。

### 4.3 停稳初始门槛（基线后可保守调整）

**同时满足**：运动完成后至少等待 `500 ms`；连续窗口至少 `1200 ms`；有效帧比例 ≥ `0.85`；有效帧置信度中位数 ≥ `0.80`；PnP 模式下 RMS 中位数 ≤ `5 px`；主测量角度标准差 ≤ `1.5°`；角度线性趋势绝对值 ≤ `1.0°/s`；观察臂静止、视角 ID 稳定、无目标 ID 交换。2D 无 PnP 时 RMS 为 null，必须依据其余有效性条件，不可把 null 当通过 PnP 门槛。超过 `5 s` 无法停稳，则返回 `settle_timeout`，不得强行拿末帧作测量。

Phase 0 实测噪声后，允许按 `max(1°, 3×baseline_angle_std)` 更新角度噪声阈值，但上限仍为 `1.5°`，超出则判视觉质量不足并排障；不得为了通过测试放松有效帧率、RMS、置信度或安全门槛。角度漂移和重复性以同一测量模式、相同视角比较。

### 4.4 看图排查触发

| 条件 | 行为 |
|---|---|
| 启动实机运动之前 | 全局/夹爪相机各取 1–2 帧供清场辅助；**必须等待人工清场确认**，不能单凭图批准 |
| 置信度 `<0.60` 持续 ≥2 s | 暂停新动作、记录事件，最多看 1–3 帧并诊断 |
| PnP `rms_px >8` 持续 ≥1 s，或连续求解失败 | 暂停新动作、记录事件，最多看 1–3 帧 |
| 连续 ≥2 s 目标失踪或 ID 反复切换 | 暂停新动作，查看同步关键帧 |
| 双摄状态冲突且无法用视角差解释 | 暂停并查看对应时间关键帧；不同投影角不直接数值相减 |
| 每轮实验结束 | 仅少量前后关键帧抽检，保留证据 |

如果调整了 CV 算法、坐标定义或观察视角，旧 `E0` 与新 `E1` 不可直接比较；须以同一版本和同一锁定视角重测基线及复测。监控可面向人显示实时画面，不代表 Codex 获准逐帧读取。

## 5. 自主实验阶段（S1 批准后才允许动作）

### Phase 0 — 预检、清场和静止 CV 基线

1. **S0 只读**：定位并阅读全部既有模块和安全配置，记录 Git 版本、COM 设备身份、双摄可用性与图像旋转方式、PWM 限位、速度限制、可用安全机位及其移动路径；检查 `COM8` 的 ESP32 UID，验证 PCA 参数配置；任何冲突先停止报告。
2. 运行只读相机采集，保存清场关键帧；要求操作者确认大/小臂的活动范围无人员、线缆、障碍物及潜在夹点，确认急停可用。**没有显式 S1 授权不得调用 `M17`、`G28`、`G1` 或写入绿臂 PWM。**
3. 获得人工授权后，按仓库既有安全控制逻辑执行观察臂 `M17` 和 `G28`；需要确认回零路径安全。绿臂依既有安全控制逻辑保持参考姿态，夹爪不动作。
4. 固定当前观察机位，每臂采集 ≥10 s 静止数据；估计关键点噪声、各角度标准差、跟踪有效率、置信度/RMS 分布及缓慢漂移。验证双绿臂 ID 不交换。
5. 若噪声无法支持可检测偏差，暂停调参并先排障。保存 `baseline.json` 和 `phase_0.md`。

### Phase 0.5 — 观察臂主动选择最佳机位（核心验收项）

1. 从**仓库列出的已验证、路径安全的机位**中选择 2–3 个（不足则如实记录）。每次小步、安全限速切换，等待观察臂和画面停稳。
2. 每个机位在绿臂固定姿态下采样相同窗口，计算 `valid_ratio`、`confidence_median`、`rms_px_median`、角度抖动、目标遮挡率和两个目标的可分离性。
3. Codex 自主说明多指标取舍并选定最可靠的有效机位，保留机位质量对比与选择理由。无 PnP 时不以 null RMS 排名。
4. **锁定此机位至 Phase 3 完成。** 若不得不改变机位，当前可比实验批次作废，重新建立同视角基线。全局相机持续记录，正式角度误差只来自预先选定的一路主测量。

### Phase 1 — 单关节 PWM→视觉局部响应辨识

1. 根据可观测性，选择绿臂 2 的 CH9（Elbow）或 CH10（Shoulder）作为主试验关节；保持其他关节在核准的参考 counts，锁定其参数。
2. 在该关节**真实配置安全窗口内**选择多个小幅测试点和增量，不直接输入绝对度数命令；统一接近方向；每点至少 3 次停稳测量，记录 `PWM counts` 与近似视觉角度。
3. 估计局部斜率 `a = Δvisual_angle_deg / ΔPWM_counts`、方向和拟合残差；检查响应是否高于静止噪声、是否单调、是否存在明显不可用的投影变化。
4. 单次指令增量、运动节奏和最大动作次数均不得超过仓库已验证设置；如果配置没有明确可信的增量/频率约束，先停下请人确认，不自行发明大幅安全动作。
5. 产出 `phase_1.md`、局部模型参数及拟合质量，不将局部斜率当成全行程精确换算。

### Phase 2 — 绿臂 2 单关节换向回差辨识

1. 在已确认的安全中间目标 `P` 附近选一个允许的 `Δ`，分别从 `P-Δ → P`（低侧接近，A）及 `P+Δ → P`（高侧接近，B）。每个**中间点和整条运动路径**都必须在安全窗口及限速内。
2. 其他关节固定，观察机位与 CV 版本固定。A、B 各至少 5 次交错重复，统一停稳统计；记录实际起点、接近方向、目标 PWM、角度中位数与波动。
3. 定义 `H0 = |median(theta_A) - median(theta_B)|`。判定 H0 是否显著超过静止角度噪声和组内重复测量散布；必要时做更多有限次复测，但不得无限循环。
4. 额外挑选至少一个安全目标点作为 Phase 3 **留出验证点**，不能用它调补偿参数。若回差不显著或视觉不可观测，诚实报告“证据不足”，停止相关自动调参。
5. 产出 `phase_2.md`、原始重复样本、`H0`、置信/散布统计及图表。

### Phase 3 — Codex 自主补偿、回退与同条件复测

1. 仅允许修改独立的**实验补偿配置**，自主选择策略：A. 统一同向接近及预备偏移 `Δ`；B. 按接近方向设不同目标 PWM counts；C. 基于 Phase 1 局部斜率的小步迭代。最终发往电机的**每个** counts 必须再次经过原有不可改安全层校验。
2. 每次补偿都写 `parameter_proposed`（旧值、新值、依据、预期结果）及 `parameter_applied`；相同机位、CV 版本、目标定义和运动流程下测试；不得用修改检测算法制造改善。
3. 若优化的是双向接近的一致性，使用 `H1 = |median(theta_A_after)-median(theta_B_after)|`，与 `H0` 对比；若优化的是统一同向接近的重复性，则用**同一目标姿态的重复测量散布** `R0/R1` 对比，不得偷换成回差改善。
4. 用至少一个**未参与调参的留出目标点**进行复核，且每种被比较路径保持足够重复次数。改善应超过测量噪声和重复性波动；建议将 `≥20%` 相对改善作为 PoC 的初始参考门槛，若统计不支持则报告不确定，而非宣布成功。
5. 如果补偿无效、变差、超出安全范围或达到试验预算，**回退到前一个已核准补偿版本**并停止该策略；不得更改底层限位来追求指标。
6. Codex 至少尝试完成 3 次有效、可追踪的“测量→诊断→调参→复测”循环（在安全和可观测条件允许时）；各轮的 `E0/E1` 或 `H0/H1`、参数与理由完整记录。未达到则报告真实完成次数和阻塞原因。
7. 产出 `phase_3.md`、前后统计、留出验证、策略与参数版本、失败和回退记录、最终判断。

### Phase R — 观察臂异常位移检测、视觉 Rebase 与安全恢复（始终启用）

Phase R 并非只在 Phase 3 后执行；它是覆盖 Phase 0–3、观察臂换机位、暂停与恢复全过程的后台状态机。**视觉基线重标定不是机械臂回零；除经独立授权的正常运动程序外，恢复逻辑绝不可自动调用 `M17`、`G28` 或 `G1`。**

#### R.1 双重证据与三种 Situation

后台 `observer_pose_monitor` 同时消费：（1）执行层可信的观察臂运动事件、`motion_id`、命令确认/完成状态、位置反馈（如果设备提供）及控制器复位/连接状态；（2）来自腕部相机的静态背景特征跟踪。优先采用 RANSAC 仿射或单应性估计相机画面整体漂移；排除两台绿色机械臂的检测框/运动掩码、人体与**人脸区域**，避免目标自己运动引起误报。背景特征需分布于多处静态区域，不能只依赖同一小块重复纹理；若背景整体可能运动或跟踪不可靠则标记 `UNKNOWN`。

| 情形 | 证据 | 处置与权限 |
|---|---|---|
| **Situation A：合法主动移动** | 合法 `motion_id`，通过既有安全层批准的预设路径，运动执行/结束有可靠确认且位置可信；视场变化与命令时间吻合 | 运动期间暂停测量比较；到达已批准机位、双臂和画面静止后允许自动执行**仅视觉** Rebase，更新 `camera_pose_id` 与 `calibration_version`。这不构成对未知位移的自动解锁 |
| **Situation B：静态视觉漂移** | 无合法观察臂运动命令，背景特征显示明显视场变化；控制器可能仍报告静止 | 立即进入 `PAUSED`，禁止新实机运动。可只读采样、诊断、重新建立候选视觉参考，但**不得自动恢复运动**；需人工排查相机支架、画面裁切、线缆等并重新确认 S1 |
| **Situation C：物理位置失信** | 控制器重启、位置状态无效/未知、疑似失步或受外力移动、状态冲突、通信丢失，或无法证明所在机位与路径安全 | `PAUSED` 并标记 `controller_position_trusted=false`。**不准自动发送 `G28`、`G1` 或为恢复而使能 `M17`**；人工排查、清场、确认回零路径后重新授权，由经验证的正常安全程序处理。视觉 Rebase 不能恢复物理位置可信度 |

**不得把“存在 motion_id”单独当作合法运动证据**：必须同时确认安全层批准、命令阶段匹配、没有超时/失败/急停和终点机位可信。也不得把“画面看起来稳定”当作物理位置可信证据。相机掉线后自动重连**只恢复采集**，不自动离开 `PAUSED`，更不恢复任何电机运动。

#### R.2 初始位移判断与质量门槛

以每个已验证 `camera_pose_id` 的静态背景为参考，剔除活动目标和人脸区域，对剩余特征做 RANSAC 估计，按整段稳定窗口综合判断；以下均为**初始工程阈值**，须在 Phase 0 的静态噪声与合法切换回放中检验，不能为了继续运动放宽安全标准：

| 项目 | 疑似漂移 | 确认视觉漂移 |
|---|---|---|
| 背景特征中位像素位移 | `> max(5 px, 3×σ_background)` | `> max(12 px, 6×σ_background)` |
| 连续持续时长 | `≥ 0.5 s` | `≥ 1.0 s` |
| 可用静态匹配特征 | `≥ 20` | `≥ 20` |
| RANSAC 内点比例 | `≥ 0.65` | `≥ 0.65` |
| 授权观察臂动作 | 无与时间一致的获批动作 | 无与时间一致的获批动作 |

`σ_background` 是固定机位静止录像中背景漂移幅度的噪声统计，计算口径须写明。摄像机旋转、尺度变化或图像被裁切时不应只用平均平移量，需将仿射/单应性变换在多个参考区域的位移和模型残差一并记录。至少同时记录 `drift_px`、阈值、`duration_ms`、`background_inliers`、`inlier_ratio`、`motion_id`、`controller_position_trusted`。无法提取足够背景特征时不得判定安全；记录 `DRIFT_UNKNOWN`，暂停可能依赖此视角的运动，并请求排障。观察臂合法运动期间暂时屏蔽“未授权漂移”分类，但**不屏蔽摄像头断流、限位和碰撞风险检查**。

#### R.3 统一状态机

状态：`NORMAL`、`EXPECTED_MOVE`、`SETTLING`、`REBASE_PENDING`、`REBASE_VALIDATING`、`PAUSED`、`RECOVERY_LOCKOUT`。所有转换在 `experiment_events.jsonl` 中落盘；运行中只允许存在一个 `attempt_id` 的 Rebase，避免并发恢复。

1. `NORMAL → EXPECTED_MOVE`：仅在安全层已批准正常主动观察动作时。运动期间禁止收集用于 E₀/E₁ 的数据。
2. `EXPECTED_MOVE → SETTLING`：控制器确认完成、目标机位可信；否则 `PAUSED`。
3. `SETTLING → REBASE_PENDING → REBASE_VALIDATING`：图像停稳后采集新静态背景特征、候选基线；成功验证后 `NORMAL`，否则 `PAUSED` 或 `RECOVERY_LOCKOUT`。
4. `NORMAL/EXPECTED_MOVE/SETTLING → PAUSED`：Situation B/C、位置状态矛盾、摄像头断流、身份异常或已有安全层的任一硬故障。进入 `PAUSED` 的原子动作是**先禁止新运动指令**，再持久化故障状态和日志。安全停车/保持由现有安全层负责。
5. `PAUSED → REBASE_PENDING`：仅允许**不涉及电机运动**的诊断和候选视觉重标定；即使候选成功，也不得自行退出安全暂停。只有人工明确排障、清场并重新授予 S1，且物理位置与安全机位已验证可信，才能进入 `REBASE_VALIDATING` 并按检查结果恢复。
6. 任何状态 → `RECOVERY_LOCKOUT`：超出次数/时限预算、重复异常或持久化故障。锁定时禁止自动移动、自动解锁；重启不清除。只有操作者明确确认原因排除并重新授权才能解除。

#### R.4 自动视觉 Rebase 的实际步骤

仅在 Situation A 已完成获批的机位移动、位置可信且安全层仍允许时，可全自动执行以下**静态数据操作**；Situation B/C 可做只读候选分析，但不得自动恢复实机运动：

1. 确认观察臂、两台绿臂均已静止，运动完成状态有效，摄像机分辨率、视角源、180° 图像旋转及时间戳正常。
2. 在**当前机位静止**条件下采集至少 `3 s` 静态背景，重建并校验 RANSAC 特征参考；确认足够背景特征、有效率及低漂移。
3. 再采集至少 `10 s` 视觉静止基线，输出角度标准差、关键点抖动、置信度与 PnP RMS 分布，通过 Phase 0 相同且不可任意放宽的质量门槛。
4. **先写入新 `calibration_version` 与 `camera_pose_id`，标记旧可比基线失效**；`E0/E1`、`H0/H1` 不允许跨版本比较，必须在新视觉版本、同一固定机位、同一 CV 算法下重测可比较的两组数据。保留旧版历史日志，不删除。
5. 通过后记录 `visual_rebase_completed`；只有 Situation A 且安全层授权持续有效、未发生故障时才允许继续正常实验。Situation B/C 仍需要人工恢复流程；任何失败都按 R.5 处理。

**注意**：无需做相机内参、手眼或双摄精确外参标定。Rebase 的含义只是重建当前机位的视觉坐标和静止噪声参考，不能当作机械臂物理位置估计或绝对空间标定。

#### R.5 防死循环预算与持久化

- 每个异常事件最多 **2 次自动静态 Rebase 尝试**，第二次失败立即 `RECOVERY_LOCKOUT`；不允许以改变事件 ID/重新启动进程的方式重新计数。
- 任意滚动 **60 秒内累计 3 次恢复触发**（含同一故障的重复断流/漂移）立即 `RECOVERY_LOCKOUT`。
- 单次尝试总持续时间上限 **30 秒**；超时当作失败计数，不能无限等待。若 10 秒基线和其他步骤无法在预算内完成，记录失败并停止，不能省略基线来强行完成。
- `RECOVERY_LOCKOUT`、故障原因、预算计数、S1 授权状态持久化保存；程序重启或相机自动重连不能清除锁定或重新授权。必须由人工排障后明确解除锁定并重新进行 S0/S1 验证。
- 不允许通过自动 `G28`、`G1`、重启控制器、放宽限位或降低 CV 门槛来规避预算。物理急停独立于软件停止。

#### R.6 Phase R 测试矩阵（先回放，后实机）

至少在历史录像/录制模拟注入中测试：合法机位切换、无指令静态视场漂移、控制器位置失信、USB 断流重连、两台绿臂运动但观察臂静止、人员经过并被排除、低纹理/遮挡导致背景特征不足、RANSAC 误匹配、连续异常触发 LOCKOUT、进程重启后 LOCKOUT 持久化、Rebase 后 E₀/E₁ 跨版本拒绝比较。各场景断言不越权发出运动命令。通过后才进入人工授权的实机验证；实机仅在安全机位内测试合法视角切换，不刻意制造危险机械失步、拔插 USB 或碰撞。

#### R.7 恢复事件示例（数值仅作示意）

```json
{"schema_version":"1.1","run_id":"run_001","timestamp_utc":"2026-11-17T08:20:00Z","monotonic_ms":252000,"event":"observer_drift_confirmed","motion_id":null,"details":{"camera_id":"wrist_8768","camera_pose_id":"view_02","calibration_version":"cal_02","drift_px":15.2,"drift_threshold_px":12.0,"duration_ms":1200,"background_inliers":42,"inlier_ratio":0.81,"controller_position_trusted":false,"recovery_state":"PAUSED","automatic_motion_allowed":false,"attempt_id":"recovery_003"}}
```

新增专属输出：`.runtime/<run_id>/recovery/drift_events.jsonl`、`recovery_attempts.jsonl`、`calibration_versions.json`、`background_reference.json`、`recovery_summary.md`。记录每次触发、模型质量、状态转换、预算、人工恢复批准、数据版本和已失效的实验比较；必要时保存触发关键帧，而不是连续 LLM 看图。`background_reference.json` 可以存特征描述和相对图像路径，避免内嵌大量像素数据。

## 6. 参数修改权限边界

**允许 Codex 修改（仅实验配置、版本化、可回退）**：同向接近的 `Δ`、方向相关 PWM 补偿、局部校正步长（始终受真实安全窗口及最大单次变化限制）、停稳角度标准差阈值（仅 Phase 0 后按本协议保守公式）、已验证机位列表中的选择、有限的重测次数、CV 算法或记录逻辑（改算法须重新跑可比基线）、Phase R 背景特征实现（不得放宽 R.5 预算或安全语义）。

**严禁修改或绕过**：PWM 硬件限位、观察臂工作空间和轨迹安全判定、最大运动速度、安全门禁、急停/超时逻辑、Phase R LOCKOUT 持久化和次数预算、`50 Hz` PCA 频率、通道映射、未映射的 CH0–CH7、未核实的夹爪控制、ESP32 引脚与 I²C 地址。不得直接向串口发送绕过既有安全控制层的运动指令。不得自动伪造人类授权或禁用异常检测。

**允许改代码但不允许放宽保护**：可新增薄适配层、数据采集/统计、实验编排、可回退补偿模块、日志及测试；修改既有驱动或安全模块须仅限兼容性修复且不得改变安全语义，若必须触及安全关键代码，先停止请人审查。

## 7. 安全中断、暂停及恢复

触发下列任一条件，**立即禁止继续下发新运动指令**，进入 `safety_pause`，保存已收到的日志/关键帧并通知操作者：

- COM3/COM8 断开、UID/端口身份不符、控制 ACK 丢失、运动超时或响应异常。
- 摄像头画面超时/断流、绿臂目标连续 ≥2 s 丢失、`confidence <0.60` 连续 ≥2 s、PnP RMS >8 px 持续 ≥1 s 或严重 ID 错配。
- 观察臂位置未知、机位/路径不在已验证范围、运动中出现新障碍/线缆风险、舵机疑似卡滞或机械碰撞。
- 指令参数、目标 counts 或中途经过点超出不可变安全窗口；现有配置/设备实际身份与任务书矛盾。
- 操作者请求停止、授权撤销、实验预算或超时上限触发。

**停止新指令**不等于盲目断电：依据已验证的安全控制层执行受控停止/保持；不要自行选择可能导致机械臂坠落或撞击的失能方式。软件停止不是物理急停的替代。异常后不得自动恢复运动；保留故障现场、补偿参数和未完成试验状态，需人工排障并重新给予授权。若不能证明 S1 门禁、急停、限位和安全停机有效，则只完成 S0 静态分析。

**Phase R 与本节同时生效，以更严格的规则为准**：合法已批准机位切换可执行静态自动视觉 Rebase；任何未知位移、位置失信或 USB 断流一律进入 `PAUSED`，数据流重连不自动恢复运动。恢复次数超限进入持久化 `RECOVERY_LOCKOUT`。

## 8. `.runtime/` 交付清单

每次运行在主仓库生成（示意目录）：

```text
ROBOT/.runtime/<run_id>/
  preflight.json                 # 设备身份、读取配置、安全限位与版本快照
  safety_gate.json               # 人工授权/撤销记录；不含伪造批准
  pose_stream.jsonl             # CV 连续结构化数据
  experiment_events.jsonl       # 指令、窗口测量、异常、调参、回退
  baseline.json                 # 静止噪声及有效性分布
  camera_view_comparison.json   # 机位质量比较与选型
  local_pwm_response.json       # 局部 PWM→视觉角度辨识
  backlash_trials.json          # A/B 接近路径及重复试验
  compensation_versions.json   # 每轮参数、策略、回退与安全核验
  phase_0.md
  phase_0_5.md
  phase_1.md
  phase_2.md
  phase_3.md
  summary.md                    # 5 项验收结论、失败原因、下一步
  media/                       # 录像、触发抽检的少量关键帧
  plots/                       # 统计图；须可追溯原始 JSONL
  recovery/
    drift_events.jsonl          # 视觉漂移的双重证据与触发
    recovery_attempts.jsonl     # 尝试次数、状态转换与授权
    calibration_versions.json   # 新旧视觉版本及失效关系
    background_reference.json   # 静态特征参考元数据
    recovery_summary.md         # 恢复结果、LOCKOUT 与排障记录
```

尽量复用 `exploration_monitor.py` 展示状态、`experiment_recorder.py` 录像，记录启动参数和录像时间戳。避免将大体积逐帧图像或视频直接读入 LLM 上下文。

## 9. 验收标准及最终报告

1. **自主观察**：Codex 在获准的 2–3 个安全机位间自主比较 CV 质量，锁定其选择并解释依据；如只有一个机位则此项不得判通过。
2. **结构化视觉**：至少区分两台绿臂，持续记录可观测的关键点和一个主关节的近似角度；基线噪声可量化。
3. **偏差识别**：在受控重复试验中证明单关节回差或响应偏差显著高于测量噪声。
4. **自主调参与复测**：独立提出有证据的补偿策略，在同视角/同测量方法和留出点上证明指标有意义改善；失败应如实记录，不得写“成功”。
5. **可复现**：尽量完成至少 3 次有效闭环，保留动作输入、视觉窗口、参数版本、日志、统计图及成果录像。

最终 `summary.md` 对每项标记 `PASS / FAIL / BLOCKED`，写明实际执行次数、具体测量误差、噪声、改善率、观测限制、异常与回退，以及“哪些部分由 Codex 自主决定”。另报告 Phase R 的检测召回/误报、恢复尝试、人工接管、LOCKOUT 与跨版本数据作废次数。严禁以模拟结果代替实机验收。

## 10. 明确排除范围

本轮不做毫米级三维重建、精确相机内参或双摄外参标定、手眼标定、全工作空间高精度逆运动学、复杂动力学/力控、模型训练、逐帧 LLM 视觉伺服、高速连续闭环、多关节同时校正、夹爪抓取和任何未经验证的新机位/新安全窗口。可以做**基础视觉有效性自检**与**受控相对角度对比**，但不能夸称绝对标定精度。

## 11. 启动执行顺序

**立刻开始 S0 只读预检和准备**：阅读仓库、核验硬件配置、整理安全边界、确认相机可用、设计适配层、Phase R 状态机和日志接口，先用历史录像及故障注入验证恢复逻辑，并说明需操作者批准的动作。**任何实机使能/回零/移动/绿臂 PWM 写入均须先人工确认 S0→S1。**批准后执行 Phase 0、0.5、1、2、3；Phase R 全程常驻，依据证据自主迭代。遇到缺失限位、冲突配置、摄像头不可用、位置信任缺失或危险迹象，暂停并汇报，不要通过猜测或降低安全标准继续。
