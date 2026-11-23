# Single-axis MicroPython library

维护源为根tb6600.py和linear_stage_inputs.py。板级引脚仅放firmware，禁止导入即操作硬件。传感器只接受电平转换后的逻辑或外部解码器快照，不默认接脚、不自动回零/校零。修改后运行python -B -m unittest discover -s tests -v。硬件运动必须遵守本轮用户给定范围，日志留.runtime。无编码器证据不能称实测毫米位置。套装仓库通过drivers/micropython/linear_stage子模块固定本库提交；先推送本库，再更新套装指针。套装tools/sync_linear_stage.py仅同步板级示例/说明，不复制驱动实现。
