# 套装组件与交付状态

|组件|状态与边界|入口|
|---|---|---|
|观察机械臂与夹爪|已有UART、长连接、仿真与安装模型；回零/运动能力依原控制器，ok不等于停稳|[observer_arm](observer_arm.md)|
|USB相机|已有共享JPEG/MJPEG采集；双目、精确标定及新机位变换未验证|[camera](camera.md)|
|线轨/滑台|规划；由综合控制器驱动，未交付完整控制工程|[linear_stage](linear_stage.md)|
|四轴步进与夹爪综合控制板|规划；当前UART库不等于已实现该PCB/固件|[stepper_servo_controller](stepper_servo_controller.md)|
|WS2812灯光|规划；包含灯光供电开关及保护|[lighting](lighting.md)|
|USB/电池功耗与电源控制|规划；电压电流功率能量及负载断电重启待实现|[power_meter](power_meter.md)|
|USB音频|规划；成熟USB麦克风/扬声器由PC访问|[audio](audio.md)|
|MLX90640热成像|规划；温度矩阵、传感器驱动和PC热图待实现|[thermal](thermal.md)|

绿色机械臂与桌面搭子为[历史PoC](../../examples/historical_poc/README.md)，不属于必装组件。
