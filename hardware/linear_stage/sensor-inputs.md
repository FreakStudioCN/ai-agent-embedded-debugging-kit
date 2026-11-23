# 工业输入预留契约

型号和线色来自用户本轮提供，未对这些实际传感器上电测量。3只SN04-P：BN棕10–30V、BU蓝0V、BK黑PNP NO；分别命名center/minimum/maximum。HN3806-AB-600F（锐乐尔电气）：红DC5–24V、黑0V、白OUTA、绿OUTB，600线AB相，后缀F按用户资料为PNP/推挽。具体输出级及负载能力无厂家原始手册佐证，不套用其他品牌F后缀定义。

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
