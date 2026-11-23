# Phase R：异常视角位移与视觉基线版本

> 本文保留为 v1.0 历史实现说明；其中状态、预算、命令示例及阈值不再作为当前规范。当前默认入口已升级，使用 [Phase R v1.1](phase-r-v11.md) 和根目录 v1.1 任务书，旧授权不生效。

入口为 `run_embodied_experiment.py`，默认启用 `PhaseRRunner`，继续复用 `ExperimentGate`、原串口驱动、CV后台和JSONL。此层只增加准入限制，未修改PWM窗口、50Hz频率、通道、单次步长、速度、回零或底层硬件故障处理。原目录保持不变，新运行通过parent_run_id关联。

## 判断依据与边界

- 腕部图像静态背景排除绿色目标，使用240个角点、双向LK和RANSAC相似变换；至少20个内点、内点率≥0.65。相对已接受基线的中位位移>5px、旋转>0.75°或尺度变化>1.5%判为视角漂移。阈值属于视觉事件检测，不是机械安全限位，也不是毫米位置精度。
- 控制证据显式区分IDLE、MOVING、WAIT_SETTLE、UNKNOWN。当前固件没有已核实的独立位置和运动完成查询，所以状态来源如实标记为“人工确认基准＋主机命令/ACK生命周期＋背景停稳”，不把ACK当实际停止或编码器反馈。
- 仅在原安全层批准、已登记目标与子段、运动ID一致的观察臂事务中允许背景变化；其他位移立即PAUSED。摄像头异常、位置不可信、运动ID矛盾、背景特征不可用也关闭所有新动作。
- 本模块没有任何G28/G1、失能或重连指令。集成运行器明确拒绝自动G28；从未知位置不能自行建立基准。S1授权与可信位置是两个独立条件。

## 状态、恢复与版本

`UNINITIALIZED → READY → MOVING → SETTLING → RECALIBRATING → READY` 是受控路径；异常转入PAUSED或LOCKOUT。

正常移动的整条连线及每个≤5mm子段由原安全层检查；中途只允许已登记的下一子段，绿臂动作仍被禁止。到已验证目标后，连续新鲜背景先确认停稳，再采集至少10秒腕部基线，保留有效率、Q、RMS、角度σ与漂移门槛。测量失败最多自动重采一次，总次数≤2，不发送补救运动。相机/位置异常不进入这类重试。

两次重标定失败或两个不同异常事件进入持久化LOCKOUT；同一故障反复轮询不会假计为两次。状态位于 `.runtime/phase_r_state.json`，原子写入，重启保留LOCKOUT；损坏的状态文件也按LOCKOUT处理。当前未提供自动解除LOCKOUT接口，不应删除状态文件绕过它。需人工审查后明确处理。

每次接受新基线都生成唯一 `calibration_version`，保留旧样本并记录 `comparisons_invalidated`。JSONL帧、停稳窗口和误差样本携带该版本。不同版本、视角或方法不能比较E0/E1；版本变化后必须重测基线、局部模型及被比较试验。跨版本混合窗口不能判停稳。

主要事件：`observer_segment_registered`、`calibration_invalidated`、`recalibration_attempt`、`recalibration_failed`、`calibration_updated`、`comparisons_invalidated`、`comparison_rejected`、`safety_pause`、`lockout`。统一使用schema_version/run_id/UTC/单调时钟，原有发送、回复、窗口和参数事件继续保留。

## 验证与实机使用

先执行：

```powershell
python -B -m cv_pipeline.tools.validate_phase_r
python -B -m unittest discover -s tests -v
node simulator/check_math.mjs
node simulator/check_gripper.mjs
```

离线脚本回放真实腕部录像，测试“若没有登记合法运动”的背景漂移拦截；其IDLE输入是明确的反事实测试，不是声称原录像中的G28没有获得授权。合法到位后的重标定、一败后二次成功、两败锁定和版本拒绝使用标注为模拟的输入，绝不计入实机实验成功。

只有操作者明确确认当前已验证机位及S1清场后，才能使用对应人工证据启动。例如操作者现场确认已归零且基准未再改变时可指定HOME；不能从历史ok或旧图猜HOME。

```powershell
python -B -u run_embodied_experiment.py --parent-run continuation_20261117T080656_ca017927 --manual-view HOME --manual-evidence "本次操作者现场确认现在机械臂处于归零状态；S0→S1已清场授权"
```

随后按单行JSON调用prepare、activate、views、phase1、phase2、phase3、close；不接受任意板端命令。prepare/activate先复核设备与当前静止视觉，激活新基线后才允许已验证机位路径。任何新异常都锁住准入，不能因自动重连恢复运动。

背景注册不能证明无人员、无障碍或USB线缆受力正常；物理急停仍依赖现场电源开关。软件停止新指令不能保证已经开始的动作瞬间停止。
