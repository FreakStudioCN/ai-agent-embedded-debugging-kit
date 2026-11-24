# 线轨板端驱动（套装内直接维护）

当前维护源为本目录tb6600.py、linear_stage_inputs.py，不是Git子模块。普通克隆套装即可获得源码，不需要独立线轨仓库权限或初始化。

板级引脚与RMT构造在firmware/linear_stage/bringup.py；3200Hz以上的300rpm请求是firmware/linear_stage/rpm_300_test.py实验，不扩大TB6600驱动0.3.2本身的50–3200Hz承诺。使用例程在examples/linear_stage，测试在tests，硬件/电平转换说明在hardware/linear_stage，组件入口在docs/components/linear_stage.md。

开发时直接在本仓库修改、测试、提交和推送，不再更新外部提交指针或运行同步脚本。部署到板端复制本目录中的原文件，勿复制父目录的旧PC导入兼容转发。导入模块不分配GPIO或发脉冲。

原来源：https://github.com/FreakStudioCN/micropython-linear-stage ，8b184a4；MIT许可证及原署名见LICENSE。历史记录和文件散列见hardware/linear_stage/provenance.json及docs/archive/linear_stage_source；旧仓库不删除，迁入后不作为套装的同步上游。
