# MicroPython Single-axis Linear Stage

独立维护的单轴TB6600驱动库，XIAO ESP32S3板级适配与工业传感器接口。组织仓库：[FreakStudioCN/micropython-linear-stage](https://github.com/FreakStudioCN/micropython-linear-stage)，私有可见性。运动驱动版本0.3.2，传感器接口版本0.1.0。

## 文件与安装

- `tb6600.py`：单文件、硬件对象注入；有限脉冲、累计预算、RMT批次、状态及软件停止。
- `linear_stage_inputs.py`：三路开关逻辑读取与外部AB计数器适配，导入不分配GPIO、不注册IRQ。
- `firmware/linear_stage/bringup.py`：已验证D0/GPIO1→ENA+、D1/GPIO2→DIR+、D2/GPIO3→PUL+；负端共GND，ENA低使能/高释放。
- `examples/exercise.py`：手动调用的板端最小运行示例，无开机自动动作。
- `hardware/inputs.json`及[传感器接入约定](docs/inputs.md)：用户给定型号、供电、输出与待定项。
- [来源和验证](docs/verification.md)。

Python标准库运行离线测试：`python -B -m unittest discover -s tests -v`。板端为MicroPython ESP32S3 + esp32.RMT，当前实测v1.29.0 Octal-SPIRAM；不需第三方运行库。先枚举实际端口再复制：

```sh
mpremote connect list
mpremote connect YOUR_PORT resume fs cp tb6600.py :tb6600.py
mpremote connect YOUR_PORT resume fs cp linear_stage_inputs.py :linear_stage_inputs.py
```

`package.json`可供后续mip分发使用，相对源引用正确；私有仓库不保证匿名mip安装；网络mip安装未验证，推荐授权克隆后通过mpremote复制。板级文件和示例不自动安装，不覆盖main.py。不需要传感器接口时只复制tb6600.py。

## 使用范围

单次最多6400脉冲、实例累计最多12800，预算显式填写；50–3200Hz，32脉冲以内有限RMT批次，Python调度会产生批间间隙。软件停止取消后续批次，允许当前批次结束，维持ENA低电平锁轴；不是急停或减速停车。deinit会释放保持力。回零、毫米定位、加减速、限位联锁、编码器闭环和失步检测未实现。3200Hz已完成每方向6400脉冲的板端发送；现场反馈尚未提供，不能宣称物理精度通过。

## 维护

本仓库为唯一维护源。套装仓库以Git子模块drivers/micropython/linear_stage固定本库提交；使用git clone --recurse-submodules或git submodule update --init --recursive取得源码，不依赖同级本机目录。驱动在本库维护，先提交并推送，再更新套装子模块指针。套装tools/sync_linear_stage.py只同步板级配置/示例/传感器说明并记录版本及散列，不再复制驱动实现。robot_arm单文件分发和导入保持原状。源文件沿用原MIT许可；不得把实际传感器未接入写成已验收。
