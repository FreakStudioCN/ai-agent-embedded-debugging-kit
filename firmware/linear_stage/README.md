# XIAO ESP32S3 / TB6600 最小验证

仅用MicroPython标准模块与esp32.RMT，无第三方板端依赖。不要作为main.py自动启动，不刷写固件、不覆盖现有main.py。已于2026-11-23烧录官方MicroPython v1.29.0 Octal-SPIRAM版本，REPL和RMT模块存在性检查通过；原实现参考v1.26 API，具体RMT构造/发送/轮询接口已在本板实际运行通过；真实波形仍未测量。PC现有mpremote 1.29.0可用于复制，无新增业务依赖。

普通克隆已包含驱动源码；先断开电机功率电源，确认板型与端口；此次由COM35烧录后，MicroPython REPL重新枚举为COM21（序列号E806909E85200000）。COM36是原同设备另一接口，不另行烧录。下次操作仍重新枚举，将YOUR_PORT替换为实际端口：

```sh
mpremote connect list
mpremote connect YOUR_PORT resume exec "import sys, os, esp32; print(sys.implementation); print(os.uname()); print(hasattr(esp32, 'RMT'))"
mpremote connect YOUR_PORT fs cp drivers/micropython/linear_stage/tb6600.py :tb6600.py
mpremote connect YOUR_PORT fs cp firmware/linear_stage/bringup.py :bringup.py
mpremote connect YOUR_PORT fs cp examples/linear_stage/exercise.py :stage_exercise.py
mpremote connect YOUR_PORT repl
```

复制工具可能软复位，先关闭电机功率电源。不要对其他设备端口试连。已确认负端共GND和3.3V可驱动；ENA已确认低电平使能、高电平释放；仍需现场确认安全脉冲方向/额度。

以下为REPL模板，三个大写变量必须按现场核验赋值：SAFE_BUDGET（1..12800累计额度）、SAFE_PULSES（1..额度）、DIRECTION_LEVEL（0/1，不代表已知机械正向）。无默认可安全移动数值。

```python
from bringup import create
from stage_exercise import exercise
import asyncio
stage = create(pulse_budget=SAFE_BUDGET)
print(stage.status())
# 静态检查信号、ENA、电源及净空后才执行
print(asyncio.run(exercise(stage, SAFE_PULSES, DIRECTION_LEVEL)))
# 另一轮需另行核对净空且总请求不超累计预算；验证中途停止
print(asyncio.run(exercise(stage, SAFE_PULSES, DIRECTION_LEVEL, stop_after_ms=15)))
```

也可在同一REPL `stage.start(...)`、`stage.update()`、`stage.stop()` 手动逐步验证：start只接受命令不发脉冲，update每次最多发一个，stop后继续update直至stopped。`status`区分accepted/running/completed/stopping/stopped/fault；completed_pulses是RMT已完成数，不是编码器反馈。故障锁定不自动重试，待排查且断开功率电源后重建对象。异常时单次最多仍有一个有限脉冲在途，物理结果未知。

板级配置固定低电平使能（enable_level=0），拒绝传入1。创建时ENA高电平释放，start后ENA低电平锁轴，完成和正常stop保持低电平；`deinit()`仅在无在途脉冲时释放RMT并禁用驱动，会失去保持力，须先支撑负载。上电、重启、复位行为及引脚毛刺均需现场核验，软件不能替代硬件禁止/急停输入。

验收先在功率电源关闭时用示波器/逻辑分析仪核对10us高电平、1us计时分辨率、脉冲数与DIR建立时间（1ms）；100Hz是每脉冲最低周期，Python调度可拉长低电平间隔。再在已确认净空中验证短脉冲、停止后不再发新脉冲、无自动重启/续跑。记录实际波形、运动方向、位移和停稳观察，不以REPL无异常代替实机通过。本轮不验证回零、毫米精度或加减速。

本板已完成两个方向各1脉冲和停止测试，用户反馈保持锁轴、无明显异常、位移看不出来；不代表可见短行程或毫米定位通过。已安装tb6600.py和bringup.py，未配置开机自动运行。测试后保留低电平锁轴。

本轮用户已确认两个方向各6400脉冲安全，驱动v0.2.0将单次硬上限设为6400，累计硬上限12800；额度仍须显式传入。此前32脉冲上限及两脉冲测试属于历史验证记录。没有毫米传动参数，不将脉冲换算为实测行程；6400脉冲按用户3200脉冲/圈配置对应电机2圈。示例超时按请求脉冲数计算，不再沿用仅适合极短动作的固定2秒。

最新1600Hz测试：驱动v0.3.0，高频RMT有限批次；两个方向各6400脉冲，约4.12秒/方向，用户反馈“振动减小，往返正常”。批次内设定1600Hz，计入间隙整段平均约1555脉冲/秒。实际波形/定位误差未测量。1600Hz时stop最多允许当前32脉冲/20ms批次完成，随后不再追加；高频中途停止仅离线测试通过，实际停止距离和时延尚未测量。运动完成后保持ENA=0，不自动重复。

最新2400Hz设置测试：驱动v0.3.1，周期最近整数微秒量化为417us，单批最多32脉冲/约13.344ms。各方向6400脉冲约2.83秒，累计RMT完成12800，ENA=0保持锁轴；现场振动及机械回位表现待反馈。批次间有间隙，不承诺连续精确2400Hz。

最新3200Hz设置测试：v0.3.2，周期量化313us，单批最多32脉冲/10.016ms。各方向6400脉冲约2.18秒，RMT累计完成12800，ENA=0保持锁轴；实际波形和定位精度未测，现场反馈待确认。批次间有间隙，整段平均约2930脉冲/秒，不承诺连续精确3200Hz。

## 300rpm请求的历史实验

[rpm_300_test.py](rpm_300_test.py)从此前本地未提交实验完整迁入；它不扩大常规TB6600驱动的频率和预算。历史3200/32000脉冲实验与当时授权见组件验证记录，旧授权不是当前位置可重复使用的余量。导入仅用于计划检查；直接执行脚本会请求实际运动，本次迁移不执行它。
