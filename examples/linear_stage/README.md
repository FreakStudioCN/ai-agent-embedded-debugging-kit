# 线轨最小离线示例

从仓库根目录执行，Python标准库即可，无新增依赖：

```sh
python -B -m host_control.linear_stage hardware/linear_stage/inventory.json
python -B -m unittest discover -s tests -p test_linear_stage.py -v
```

第一条列出缺失字段，当前清单预期退出码2；完整且格式正确返回0仅表示参数核验通过，不表示可运动或实机验收通过。没有串口打开、设备识别或模拟设备响应。

`AxisCalibration` 是纯单位换算：steps/mm = 电机整步/转 × 细分 × 电机转数/输出转数 ÷ 输出每转毫米。丝杆填导程（多头丝杆不是螺距）；同步带按实际带轮每转位移填写。direction只定义脉冲计数到正坐标的符号。位移按最近脉冲量化，半脉冲远离零；绝对目标检查要求原点和参数已成立，不能替代回零或运行时限位保护。步数换算是推算位移，不是编码器实测位置。测试中的数字全部为合成数据。

本轮TB6600有限脉冲与停止示例已增加，见[安装和REPL步骤](../../firmware/linear_stage/README.md)及[exercise.py](exercise.py)。ENA低电平使能已确认；安全方向及脉冲额度待现场确认，不自动运行。现场流程及验收边界见[组件说明](../../docs/components/linear_stage.md)。
