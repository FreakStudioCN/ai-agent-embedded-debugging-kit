# 线轨硬件资料

现有实机采用XIAO ESP32S3 + 独立TB6600进行单轴有限脉冲验证。2026-11-26新增集成式线轨控制板设计截图与ICON归档；新板尚未完成实物验证，与后续多轴综合控制板规划区分。

- [集成式线轨控制板 v1.0：原理图、PCB、新ICON、接线、最新BOM及主控替代说明](integrated_control_board/v1.0/2026-11-26/README.md)
- [采购链接、实际型号/参数与待补尺寸](specifications.md)
- [机器可读清单与最新已记录实验](inventory.json)
- [工业传感器/电平转换核对](sensor-inputs.md)
- [历史来源、许可证与迁入记录](provenance.json)
- [板端接线/安装步骤](../../firmware/linear_stage/README.md)
- [机械/CAD资料状态](../../mechanical/linear_stage/README.md)
- [验证与现场反馈记录](../../docs/components/linear_stage-verification.md)

采购参考：https://m.tb.cn/h.jPBVUNk?tk=7tkJ63pNKF4 （总任务2.1原链接）。页面本次未成功读取，未收到滑台CAD或原始硬件工程；尺寸/导程/行程等待厂家资料或量具实测。商品链接不作为CAD，旧脉冲数量不作为实测毫米。

D0/GPIO1→ENA+、D1/GPIO2→DIR+、D2/GPIO3→PUL+、负端共GND；ENA低锁轴/高释放为用户确认。详细供电、信号和原始依据见specifications.md，传感器工业输出不得直接接3.3V GPIO。

2026-11-24起硬件、固件、驱动、示例、测试和文档均在套装直接维护，不再外部同步。以前的核对过程完整保存在docs/archive/linear_stage_source/hardware-notes-before-integration.md；其中未知/限制是当时状态，以当前清单及组件验证记录为准。

资料来源为总任务第2.1、2.3、4.2–4.3节及已记录的用户确认；规划不作为到货证据。

[实物视频截帧](../../docs/assets/readme/linear-stage.jpg)及[图片来源](../../docs/assets/readme/README.md)随双语README资料保留；照片不证明尺寸/定位精度，也不代替CAD。
