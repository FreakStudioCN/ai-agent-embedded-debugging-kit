# Phase R v1.1

执行规范为根目录 `FreakStudio_Codex_Embodied_Debugging_Task_v1.1.md`。默认入口使用 `PhaseRRunnerV11`；旧 PhaseR 保留作路径事务复用与历史回归。原驱动、通道、50 Hz、PWM 窗口、5 counts / 5 mm 步长、F5、节奏及预算未放宽。

## 状态、权限与硬件边界

公开状态为 NORMAL、EXPECTED_MOVE、SETTLING、REBASE_PENDING、REBASE_VALIDATING、PAUSED、RECOVERY_LOCKOUT。内部 legacy_state 仅兼容旧路径事务；落盘和事件采用 v1.1 名称。

S0 禁止使能、回零、运动、PWM 写入。S1 必须来自本次预检后的新人工授权。启动入口不再使用旧 prepare 中硬编码的历史批准；必须提供新授权、排障完成且明确解除旧锁定、清场/线缆/物理断电开关，以及当前可信机位的人工原文。异常先关闭准入，再落盘。软件 Hold 不能保证已开始的板端轨迹立即停止；底层硬故障可能释放输出，其原策略未改动。

UART 没有已核实的位置或独立物理完成查询，证据明确标为人工参考、主机 ACK/pending 生命周期和新鲜背景停稳，不冒充编码器。无声复位/失步不保证可观测。画面静止不能恢复物理信任；不明位置须人工处理。恢复类没有串口接口或 M17/G28/G1；正常运行器禁止自动 G28。

## 背景与 Rebase

`phase_r_background.py` 使用分区角点、双向 LK、RANSAC 相似变换，排除绿色轮廓完整包围框、HOG 人体、Haar 人脸及保守扩展身体区域，并支持外部活动/人体掩码。检测器不是清场批准器。

至少 20 内点、内点率 0.65，覆盖至少三个 3×3 网格、横纵跨度各至少 30%、凸包面积至少 8%。重复 ORB 描述子过多时拒绝参考。记录多个区域的变换位移、旋转、尺度、残差、排除框。特征不足/分布不足/匹配不可靠为 DRIFT_UNKNOWN，暂停。

背景 σ 定义为至少三秒新鲜静止帧中“相对参考特征的欧氏位移中位数”的样本标准差。疑似阈值 max(5 px,3σ) 持续 0.5 秒即关闭准入；确认阈值 max(12 px,6σ) 持续一秒。多区域最大变换位移也参与保守判断。合法登记运动期间只屏蔽未授权漂移分类，摄像头故障仍生效。

仅合法机位路径及可信终点允许自动视觉 Rebase。先至少三秒背景，再至少十秒角度基线；Q≥0.80、有效率≥0.85、PnP 欧氏 RMS≤5 px、角度趋势≤1°/s。噪声门槛 max(1°,3σ) 若超过 1.5°则拒绝质量，不截断数值强行通过。

接受参考时先写新 calibration_version/camera_pose_id 并作废旧比较，再发布 visual_rebase_completed。跨版本、机位、测量模式的 E0/E1/H0/H1 拒绝比较。改算法必须重新测两组数据。

## 预算、持久化和记录

每事件最多两次自动尝试，第二次失败立即锁定。背景、基线及复核总计最多 30 秒；超时锁定，后台超时工作不能提交版本。滚动 60 秒第三次恢复触发立即锁定，包括相同故障的新发作；同一连续故障的逐帧轮询不伪计新发作。正常机位比较仅在 NORMAL 时等待预算窗口，锁定后不能靠等待自动恢复。

`.runtime/phase_r_state.json` 原子保存状态、次数、滚动触发、授权及版本。重启保留锁定并撤销 S1/位置信任。持久化失败先锁准入，尽力保存 `.lockout` 标记；标记只可经人工审查授权后归档。人工审查建立新恢复周期，但保留旧次数、原因及触发历史。

每运行 recovery/ 包含 drift_events.jsonl、recovery_attempts.jsonl、calibration_versions.json、background_reference.json、recovery_summary.md；事件包含 calibration_version、recovery_state、attempt_id、evidence。

## 验证和运行

```powershell
python -B -m unittest discover -s tests -v
node simulator/check_math.mjs
node simulator/check_gripper.mjs
# 对已有的独立 S0 续跑目录回放，不打开串口：
python -B -m cv_pipeline.tools.validate_phase_r_v11 .runtime/<本次S0续跑目录>
```

`tools/preflight_v11.py <本次目录>` 枚举端口、只读 COM8、订阅共享双摄，不打开 COM3、不解除根锁定。CV 依赖为 OpenCV headless 4.13≤版本<5；本机 5.0 缺少 HOG/Haar 接口。`vision_subpixel.py` 是未通过测试的离线候选，未接入实机测量。

当前选择 `vision_lk.py`：保留经双向一致性检查的 LK 亚像素观测，取消随后整数峰值吸附；原四孔身份、PnP、几何、Q 定义及阈值不变，不新增时间平滑。修改测量方法后必须重新建立同版本基线。背景三秒按首尾源帧时间戳计算；启动先有界等待首帧，不将尚未到达的首帧误判为断流。

只有拿到新人工原文后才能使用以下入口；示意文字不能充当真实批准：

```powershell
python -B -u run_embodied_experiment.py --parent-run <父run_id> --manual-view <已验证当前机位> --manual-evidence "<本次人工位置依据>" --s1-confirmation "<本次新的S0→S1批准原文>" --cause-resolved "<排障完成且明确解除旧锁定的原文>" --clearance "<人员、全部预定线缆路径及物理断电开关确认>"
```

依次输入 prepare、activate、views、phase1、phase2、phase3、close，例如 `{"operation":"prepare"}`。质量/安全条件未通过时，即使获批也不运动。USB 重连只恢复采集，不恢复授权。

若操作者另行明确要求归零，可额外提供 `--home-confirmation "<本次明确归零请求>"`，先 prepare_homing、清场关键帧核查，再 home、activate_homed。`operator_homing.py` 独立复用原 RevisedRunner.home 和原 ExperimentGate，只允许 G4 S0/M17/G28；仅操作者调用，绝不由 Phase R 故障、重连或重试触发。归零完成还需原等待、背景停稳、三秒背景及十秒角度验证，不把 ACK 当物理完成。

`tools/smoke_v11_live_cv_no_motors.py <只读续跑目录>` 使用真实共享双摄与完全模拟的串口，走通 prepare/activate/合法到位 Rebase；恢复状态位于私有目录。其模拟命令绝不发送到硬件，也不算实机闭环。录像参数 `--events` 应传运行目录而非 JSONL 文件；事件时间兼容 time/timestamp_utc。
