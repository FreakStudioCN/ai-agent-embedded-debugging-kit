# 飞书待更新稿：集成式线轨控制板

目标文档：[AI Agent嵌入式设备自动化调试套装｜开发任务说明](https://f1829ryac0m.feishu.cn/docx/Jwo1dIiAGoc7iUxGVMMcQfZrnGm)。状态：仅整理候选内容，尚未写入云文档。本稿不改变现有规划、验收记录或历史任务范围。

## 建议补入“2.1 现成电动滑台 + 视觉观察单元”的内容

2026-11-26更新：线轨输入电平转换板扩展为“集成式线轨控制板 / Integrated Linear Stage Control Board”，图面版本v1.0。保留三路限位/回零与编码器A/B输入电平转换、PUL/DIR/ENA驱动信号接口，新增步进电机驱动器电源控制继电器。

运动控制接口U5（COM+、PUL−、DIR−、ENA−）与电源开关接口U7（NC、COM、NO）分开定义：U5用于驱动器逻辑输入，U7用于驱动器电源通断，不能用于电机绕组连接。U7 COM在当前图中已接板上12V，并非独立浮空触点公共端。H1短接1–2选择3.3V公共端，短接2–3选择5V公共端，不得三脚同时短接。

主控U6可选XIAO ESP32S3或XIAO ESP32C3，每板装配一款。BOM原导出列C3、原理图标S3，用户确认两款可选；文档附两款GPIO映射及固件差异，替换后须核对启动行为和实际功能，不把排针位置一致写成软件可直接互换。

背面截图已标注FreakStudio、板名、v1.0及NC/COM/NO。新版粗框工业风功能ICON已生成并归档，展示信号输入、滑台控制和继电器电源通断；当前归档正面截图尚未包含新ICON，因此不写成“正面已添加新ICON”。

最新BOM原始XLSX、可读CSV、接线说明、主控替代说明与原理图/PCB正反面截图均已整理到套装仓库。本次是设计资料同步，未修改或部署运行固件；新板ERC/DRC、丝印制造尺寸、继电器负载及实物功能尚未验证。

## 对应入口

- [嘉立创工程](https://u.lceda.cn/account/user/projects/index/detail?project=787da6d030f54902b2a4eebc46c4ca98&listType=all)
- [仓库资料目录](https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit/tree/main/hardware/linear_stage/integrated_control_board/v1.0/2026-11-26)
- [接线说明](wiring.md)
- [最新BOM说明](bom-notes.md)
- [主控可替换说明](controller-options.md)

## 建议新增的文档版本记录

| 版本号 | 修订日期 | 修改人 | 修改内容 |
| --- | --- | --- | --- |
| 待发布时按云文档当前版本递增 | 待实际写入日期 | 赵岩松 | 补充集成式线轨控制板继电器电源控制、接口区分、最新BOM及XIAO S3/C3主控替代说明，关联仓库资料；保留未验证项。 |

正式更新时应与原文当前版本核对后合并为一条记录，保留历史。不得把本稿视为已发布版本，也不得把新ICON未导入、实物未验证写成已完成。
