# 工业输入预留契约

型号和线色来自用户本轮提供，未对这些实际传感器上电测量。3只SN04-P：BN棕10–30V、BU蓝0V、BK黑PNP NO；分别命名center/minimum/maximum。HN3806-AB-600F（锐乐尔电气）：红DC5–24V、黑0V、白OUTA、绿OUTB，600线AB相，PNP输出已由用户于2026-11-24确认；确切内部输出级/负载能力待原图。具体输出级及负载能力无厂家原始手册佐证，不套用其他品牌F后缀定义。

## 电气边界

上述输出不能直接接3.3V GPIO，包括5V供电的编码器。必须使用适合PNP源型输出的隔离/电平转换输入及必要保护，验证转换后的高低电平、反相、带宽和上电行为。隔离方案的现场0V与MCU地按实际电路设计，不默认两侧短接；未提供电路，因此不指定电阻值、隔离器或引脚。SN04-P常开输出不能可靠区分未触发与断线。软件读取不等于硬件保护。

- SN04-P供电/输出类型可参考供应商资料：https://www.fuyuautomation.com/resource/attachments/beedc8eb2d8a4209a6e2e22fc2fbfd13_33.pdf ，不代替当前器件的现场核验。
- ESP32S3电气参数：https://files.seeedstudio.com/wiki/SeeedStudio-XIAO-ESP32S3/res/esp32-s3_datasheet.pdf 。

## 三路开关

```python
from linear_stage_inputs import SwitchInputs
inputs = SwitchInputs(active_levels=(1, 1, 1))
print(inputs.read())  # center/minimum/maximum 均为None，未配置
# 接入转换器后传入各Pin.value等无参数回调，并按实测填写三路active_levels。
```

active_levels是转换后GPIO侧极性，与PNP标签不能直接等同。回调异常原样抛出，非法返回值报错，缺失通道为None。无自动去抖、IRQ、联锁或运动禁止；实际保护、采样间隔和端点停车距离需后续明确。中位触发不自动置零。DIR=0/1尚未映射机械最小/最大方向。

## 编码器

```python
from linear_stage_inputs import IncrementalEncoder
feedback = IncrementalEncoder()
print(feedback.read())  # 未配置，不提供虚假的计数或位置
# feedback = IncrementalEncoder(read_count=validated_decoder_snapshot, decoding=4, sign=1)
```

600线为A相每圈600周期；x1/x2/x4的计数定义必须与外部解码器一致，分别600/1200/2400计数每编码器轴圈。未默认x4，回调必须原子读取有符号累计计数。接口不会安装Python高频IRQ；须验证硬件计数器/外部解码器的吞吐、溢出和原子快照，在最大转速下不丢计数。x4时每转2400边沿是解码定义，不是已经实测的能力。

返回shaft_turns_from_counter_origin仅表示编码器计数器原点起的转数，不是绝对角度、已回零位置或滑台毫米。断电初始原点未知；末端安装关系、每圈对应毫米、方向、减速/传动、参考点未确认。没有Z相资料，不预留成已有Z相能力。精确位置、参考/回零、闭环校验后续实现。未配置接口不会自动停止当前驱动；当前运动验证仍是用户现场看护的开环测试。


## 2026-11-24资料复核与待办（无新增接线/实测）

|对象|已有依据|尚缺证据|下一步核对|
|---|---|---|---|
|SN04-P ×3|用户给定型号、BN 10–30V/BU 0V/BK PNP NO|与当前实物匹配的厂家图、输出高低电压/漏电流、转换板型号、三路GPIO|核对铭牌/原图及输出负载条件；先确认转换后电平/反相，再分别登记中位与两端限位|
|HN3806-AB-600F|用户给定600线AB、红5–24V/黑0V/白A/绿B；锐乐尔电气|用户已确认PNP；适配电平转换仍需实际输出电平、最大频率/负载、两路电平转换/解码器、安装关系|型号对应原图及电路资料留待后补；不再将PNP类型列为未知，也不把PNP与推挽当作同一电路|
|电平转换|目标是将实际工业输出转换成合法的3.3V逻辑输入；未选定器件/电路|5路输入（3开关+A/B）的接线、输出级、带宽、滤波、隔离和上电状态|开关与编码器分别评估；不能以慢速开关光耦输入板已适配推定AB高速计数可用|

NPN导通时通常向0V灌电流，负载接V+与输出之间；PNP导通时通常从V+拉电流，负载接输出与0V之间。它们在适配负载下体现为拉低/拉高，未导通时可能高阻/存在泄漏，不能将“PNP未触发必为0V”或“NPN未触发必为3.3V”写死。推挽可主动拉高和拉低，不能只按PNP名称选择接法。这些是输出原理，不证明当前器件内部电路已经确认。

若**编码器轴自身**为300rpm，600线A相约3000周期/秒，x4计数约12000边沿/秒；这是选型核算值，不是已实测转速或吞吐。最大实际轴速与传动关系未确认，须留带宽余量，并核对滤波是否吞脉冲、计数溢出和原子快照。ESP32-S3硬件PCNT可作为后续解码候选，但没有因此宣称当前MicroPython固件已提供可用PCNT接口。

目前未取得新商家确认记录、转换电路、实测电平/波形或传感器读数；本轮没有给工业输入上电或连接GPIO。回零、限位联锁、编码器闭环继续标未完成。下一项依赖是对应实物的原图/供电与输出确认，随后才是转换后电平和读数验证。

通用原理依据：[OMRON NPN/PNP说明](https://www.ia.omron.com/support/faq/answer/41/faq00379/)；计数候选依据：[Espressif ESP32-S3 PCNT](https://docs.espressif.com/projects/esp-idf/en/v6.0.3/esp32s3/api-reference/peripherals/pcnt.html)。原引用的供应商SN04-P PDF本次请求超时，HN3806精确型号的原厂文档未检索到，均不以其他品牌的手册代替当前实物确认。

用户2026-11-24补充：编码器是PNP；尺寸/CAD与转换板资料暂不追加索取，后续补齐。未将确认类型写成已完成输出电平测量或GPIO接入。
