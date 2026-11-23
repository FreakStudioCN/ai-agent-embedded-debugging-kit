# RobotArm UART · MicroPython 机械臂串口驱动

通过115200/8N1串口控制使用G/M指令协议的机械臂。协议依据项目提供的《串口通信指令.docx》，适用于该协议兼容控制器。

驱动使用调用者传入的UART对象，每次发送一条指令并等待协议回复 `ok`。提供XYZ移动、回零、夹爪控制、电机使能、IO和12V输出接口。版本为0.1.0，采用MIT许可证。

## 目录

```text
micropython-robot-arm/
├── code/
│   ├── robot_arm.py       # MicroPython串口驱动
│   ├── main.py            # ESP32示例，显式调用main()执行
│   └── pc_control.py      # CPython / pyserial适配和命令行入口
├── tests/
│   └── test_robot_arm.py  # 模拟UART协议测试
├── package.json          # mip包清单，仅安装robot_arm.py
├── requirements-pc.txt   # 电脑端可选依赖
├── .gitignore
├── LICENSE
└── README.md
```

## 安装到MicroPython

将 `code/robot_arm.py` 复制到开发板根目录或 `/lib/robot_arm.py`，随后使用 `from robot_arm import RobotArm` 导入。驱动本身使用MicroPython内置模块。

板卡TX接控制器RX，RX接控制器TX，GND共地。UART使用115200 baud、8数据位、无校验、1停止位。GPIO17/16为以下ESP32示例引脚，可按实际板卡调整。控制器接口电平需与板卡或电平转换器匹配，原协议文档未说明TTL、RS232、RS485及电压。

```python
from machine import UART, Pin
from robot_arm import RobotArm

uart = UART(1, baudrate=115200, bits=8, parity=None, stop=1,
            tx=Pin(17), rx=Pin(16), timeout=0, timeout_char=2)
arm = RobotArm(uart, timeout_ms=60000, debug=True)
arm.dwell(0)  # 通信检查

# 明确准备执行机械动作时调用
# arm.enable_motors()
# arm.home(timeout_ms=120000)
# arm.move(x=5, y=174, z=120, speed=5)
# arm.open_gripper()
```

`code/main.py` 保留可运行的ESP32示例。导入后调用 `main.main()` 会执行电机使能和回零。XYZ示例坐标来自本项目实机测试，使用时应匹配自己的机械臂坐标与运动范围。

`package.json` 使用mip的相对源路径格式。上传到支持mip的仓库后，清单仅安装驱动模块，电脑端适配和运行示例通过文件方式使用。

## 电脑端控制

在仓库根目录运行以下命令安装电脑端依赖并检查通信。

```powershell
python -m pip install -r requirements-pc.txt
python -B code/pc_control.py --port COM23 --timeout 5000
```

默认发送 `G4 S0`。指定 `--command` 可执行单条指令，例如回零。

```powershell
python -B code/pc_control.py --port COM23 --timeout 120000 --command "G28"
```

电脑端默认在打开串口后等待2秒，使用 `--startup-delay` 可调整。UART适配器会预先将DTR/RTS设置为False，USB驱动仍可能在打开时切换信号。多条动作应保持同一个连接与驱动实例，按顺序等待回复，并结合动作时间和视觉检查等待实际停稳。

## API

```python
arm = RobotArm(uart, timeout_ms=30000, debug=False)
```

控制方法支持 `timeout_ms` 参数，收到完成回复后返回 `"ok"`。

| 方法 | 指令 | 功能 |
| --- | --- | --- |
| `move(x=None, y=None, z=None, speed=None, i=None, j=None, rapid=False)` | G1 / G0 | XYZ直线移动及I/J角度目标 |
| `home()` | G28 | 回零 |
| `dwell(seconds)` | G4 S | 控制器延时 |
| `set_gripper_angles(i=None, j=None)` | G1 I/J | 夹爪舵机角度 |
| `close_gripper()` / `open_gripper()` | M3 / M5 | 闭合 / 张开 |
| `enable_motors()` / `disable_motors()` | M17 / M18 | 使能 / 禁用步进电机 |
| `set_io(1, high)` | M1 / M2 | IO1高低电平 |
| `set_io(2, high)` | M6 / M7 | IO2高低电平 |
| `set_output_12v("A" / "B" / "OFF")` | M121 / M122 / M123 | 12V输出模式 |
| `command(text)` | 原始单条G/M指令 | 发送并等待完成 |
| `wait_done()` | 接收待确认命令回复 | 无待确认命令时返回None |
| `recover(controller_idle=True)` | 清理本地通信状态 | 调用前确认控制器空闲且输入已清理 |

XYZ单位为mm，`speed` 单位为mm/s，最小值5。I/J为角度目标，与XYZ同条发送时即时生效。G0/G1在原协议中的逻辑相同。高层接口省略未提供参数，浮点参数输出为最多6位小数。

原始指令接口会校验单行ASCII格式及G/M前缀。工作空间、角度范围和12V模式A/B含义由实际控制器与硬件决定。原文出现E参数但缺少语义定义，可在确认含义后通过原始指令接口使用。

## 超时与连接管理

驱动兼容CR、LF、CRLF结束的回复和裸 `ok`，支持分段读取、部分写入和计时回绕。控制器最多缓存15条命令，本库保持一条待确认命令。每个UART由同一个调用者串行使用。

`ArmTimeout` 表示命令执行状态尚未确定。使用同一个实例的 `wait_done()` 继续等待该命令的回复，避免重复发送动作。`ArmError` 表示串口或控制器异常。故障恢复前需确认控制器已空闲、旧回复已结束、残留输入已清理。

```python
from robot_arm import ArmError, ArmTimeout

try:
    arm.home(timeout_ms=120000)
except ArmTimeout:
    print("待确认指令", arm.pending)
    arm.wait_done(timeout_ms=120000)
except ArmError as exc:
    print("控制器异常", exc)
```

UART生命周期由调用者管理，结束通信时调用 `uart.deinit()`。原协议未提供位置查询、运动状态查询或急停命令。`M18` 会释放步进电机保持力。电脑端命令完成回复表明控制器确认，实际坐标精度需要外部量测。

## 验证

在仓库根目录运行现有协议测试。

```powershell
python -B -m unittest discover -s tests -v
```

测试覆盖指令映射、数值格式、分段回复、部分写入、超时锁定、迟到回复、异常恢复及计时回绕。2026-11-16已在Windows通过COM23的CH340控制器验证串口完成回复，并执行回零、往返移动、夹爪开合与多轮运动。MicroPython开发板UART端仍需部署验证。


## 实机回复语义更新

2026-11-16 观察到控制器回复 `ok` 后机械臂仍继续移动。现有接口返回值仅表明收到协议回复。运动目标需要等待并通过新鲜画面核对，驱动不提供位置和物理到位反馈。长连接操作入口为 `code/pc_session.py`，操作规则见 `.agents/skills/robot-arm-control/SKILL.md`。
