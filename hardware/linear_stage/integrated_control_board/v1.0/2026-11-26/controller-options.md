# XIAO ESP32S3 / ESP32C3 主控可替换说明

用户2026-11-26确认：本板U6可选Seeed Studio XIAO ESP32S3或XIAO ESP32C3，按XIAO标准排针位置安装一款。此说明仅限本板所用两款XIAO模组，不泛指所有ESP32开发板或所有XIAO扩展版本。

BOM原始导出U6列为XIAO ESP32C3；当前原理图标为XIAO ESP32S3。保留原始BOM不改写厂商料号，S3作为用户确认的装配替代项，每板仅安装1个U6；采购及装配时记录实际选用型号。

## 板端与芯片GPIO映射

| XIAO板端 | 本板信号 | ESP32S3 GPIO | ESP32C3 GPIO |
| --- | --- | --- | --- |
| D0 | MCU_LIMIT_L_N 左限位 | 1 | 2 |
| D1 | MCU_HOME_Z_N 回零 | 2 | 3 |
| D2 | MCU_LIMIT_R_N 右限位 | 3 | 4 |
| D3 | MCU_ENC_A_N 编码器A | 4 | 5 |
| D4 | MCU_ENC_B_N 编码器B | 5 | 6 |
| D5 | MCU_PUL 脉冲 | 6 | 7 |
| D6 | MCU_DIR 方向 | 43 | 21 |
| D7 | MCU_ENA 使能 | 44 | 20 |
| D8 | RELAY_CTRL 继电器控制 | 7 | 8 |
| D9 | 当前图中未连接 | 8 | 9 |
| D10 | 当前图中未连接 | 9 | 10 |

D编号代表XIAO板端位置，MicroPython的Pin数字使用芯片GPIO编号，两者不能混用。更换型号时需使用匹配的固件并更新GPIO配置、脉冲外设及编码器采集实现，不能直接沿用另一款芯片的固件映像或GPIO数字。

C3的D0/GPIO2和D8/GPIO8涉及启动配置；本设计分别连接输入级和继电器控制级，更换主控后应核对外部电路在上电/复位时对启动电平的影响，确认可正常启动且不误吸合。模组排针位置一致不表示启动行为或软件外设完全相同。两款模组在本新板上的实际兼容性尚未分别上电验证。

## 依据

- 用户确认：两款主控可选，2026-11-26。
- [Seeed官方XIAO ESP32C3引脚表](https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/)
- [Seeed官方XIAO ESP32S3引脚表](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)
- [本板原理图](schematic.png)
