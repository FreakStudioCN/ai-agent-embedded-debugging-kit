# Miniconda 环境与离线复建

本说明针对现有观察机械臂/USB相机软件和离线回归检查。通过测试不代表规划组件、两套设备安装或整套实物硬件验收完成。

## 文件与支持范围

- 根目录 `environment.yml`：维护用环境配方，Python 3.12，Conda渠道只使用 `conda-forge`（`nodefaults`排除用户配置中的defaults），Conda安装Python/pip/Tk，pip安装项目Python依赖。
- 根目录 `requirements-lock.txt`：本次全新环境验证得到的pip包精确版本；不是整个Conda环境锁。
- `env/environment-verified-win-64.yml`：本次Windows x86-64完整Conda导出（含精确版本的pip部分，无本机prefix）。
- `env/conda-explicit-win-64.txt`：本次Conda包的精确构建/渠道URL；必须另外安装requirements-lock.txt中的pip包。
- `env/verification-2026-11-23.json`：实际解释器、包和外部工具版本、文件散列及测试结果。

通用配方可重新求解平台依赖；精确导出只在Windows x86-64验证，不承诺跨系统复现同一构建。已复核李子圣提供的environment.yml和requirements-lock.txt：原环境名及prefix含本机路径，渠道含多个与项目无关的镜像；原pip freeze含Conda构建机的packaging @ file://引用。正式文件改为中性环境名、单一conda-forge渠道；Conda工具包由Conda导出记录，pip锁仅记录业务依赖，不保留构建机路径。原附件散列留在验证记录，不修改原件。之前缺依赖的失败不作为已证明代码出错的依据。

## 本次验证记录

2026-11-23，Windows x86-64，Conda 26.1.1；Python 3.12.16，pyserial 3.5、Pillow 13.0.0、NumPy 2.5.5、opencv-python-headless 4.14.0.94，四项业务包与收到的附件一致。

从维护配方创建一套全新环境，再从完整导出YAML创建另一套全新环境；两套Conda/pip包清单一致，pip check均通过，各128项Python测试通过。Node.js v26.4.0下639项运动学检查和夹爪检查通过；Tk/ImageTk及四个CLI帮助检查通过，未打开设备。过程中有一次Conda包下载超时和一次pip下载中断，重试后完成，不归因于代码或配方错误。

精确构建由explicit文件记录；当前只验证YAML重建方式，explicit分步入口未再单独创建第三套环境。GUI窗口、实时音视频、串口和真实运动不在本轮验收范围。

## 最低依赖与可选功能

|用途|依赖|范围|
|---|---|---|
|板端独立robot_arm.py|MicroPython的标准模块及实际UART|不安装此PC Conda环境；烧录/复制工具另装|
|PC串口会话|Python 3.12 + pyserial（requirements-pc.txt）|最小串口控制依赖|
|JSONL读取、直接JPEG取图、静态仿真服务|Python标准库|已有HTTP相机服务是取图前提；启动本机相机另需FFmpeg|
|观察窗口/画面处理|Pillow；窗口另需Tk（requirements-monitor.txt）|Pillow也供录像/安全工具共用的观察核心使用|
|轴线拟合及历史CV算法|NumPy、Pillow、opencv-python-headless（requirements-vision.txt）|直接向Agent附图不需要整套CV；headless不提供cv2.imshow窗口|
|完整128项Python回归|以上全部|使用unittest，不额外引入pytest|
|历史双绿臂/桌面搭子|各历史PoC文档中的外部仓库、设备或预设|不纳入主线环境已复现承诺|

根environment.yml包含完整离线回归依赖，而不是声称每个模块都需要全部依赖。只需串口时可执行：

```powershell
conda create -n kit-serial --override-channels -c conda-forge python=3.12 pip --no-default-packages
conda activate kit-serial
python -m pip install -r requirements-pc.txt
```

## 创建、激活、检查和更新

在已授权克隆的仓库根目录，使用Miniconda Prompt或已经初始化Conda的PowerShell。pip业务包本次使用PyPI；如要与本次复建使用同一索引，PowerShell先执行 `$env:PIP_INDEX_URL="https://pypi.org/simple"`，这仅作用于当前终端，不修改全局配置：

```powershell
conda env create --file environment.yml --no-default-packages
conda activate embedded-debugging-kit
python --version
python -m pip check
python -c "import sys, serial, PIL, numpy, cv2, tkinter; print(sys.executable); print(tkinter.TkVersion)"
python -B -m unittest discover -s tests -v
node simulator/check_math.mjs
node simulator/check_gripper.mjs
```

无GUI显示的机器可导入Tk但不能据此证明窗口可展示；本轮未做摄像头、串口或真实运动验收。运行可用组件的命令见根README与各组件说明。

更新维护环境：

```powershell
conda env update --name embedded-debugging-kit --file environment.yml --prune
conda activate embedded-debugging-kit
python -m pip check
```

`--prune`不保证卸载全部多余pip包；配方允许范围内的pip包也不一定升级。要获得可核对的干净结果，使用新环境名重建再测试，不将长期混用的base环境导出作为项目依赖。不要在同一环境混装opencv-python与opencv-python-headless。

## 按本次精确记录复建

完整导出方式（本次已实际从另一全新环境复建）：

```powershell
conda env create --name kit-rebuilt --file env/environment-verified-win-64.yml --no-default-packages
conda activate kit-rebuilt
python -m pip check
python -B -m unittest discover -s tests -v
node simulator/check_math.mjs
node simulator/check_gripper.mjs
```

需要锁定Conda构建时，可改用以下等价分步入口；此时不能漏掉pip锁文件：

```powershell
conda create --name kit-exact --file env/conda-explicit-win-64.txt --no-default-packages
conda activate kit-exact
python -m pip install -r requirements-lock.txt
```

导出方式（PowerShell；先激活已验证环境）：

```powershell
conda env export --no-builds | Where-Object { $_ -notmatch '^prefix:' } | Set-Content -Encoding utf8 env/environment-verified-win-64.yml
conda list --explicit | Set-Content -Encoding utf8 env/conda-explicit-win-64.txt
$export = conda env export --json | ConvertFrom-Json
$pipPackages = ($export.dependencies | Where-Object { $_ -isnot [string] }).pip
$pipPackages | Set-Content -Encoding utf8 requirements-lock.txt
```

本仓库的Python业务依赖统一由pip安装，因此此处从Conda导出的pip字段提取的业务包可用于pip重装；不要直接把包含Conda构建机file://路径的全量pip freeze作为可复建锁文件；Conda运行时用YAML/explicit记录。导出后检查无本机prefix、用户路径、本地文件引用和认证令牌，再在新环境验证。

## 非Python工具

- Node.js：用于两项JavaScript离线检查；不需要npm install，Three.js已经随仓库提供。实际验证版本见env/verification-2026-11-23.json。
- FFmpeg/ffprobe：相机枚举/采集与录像用途，Windows相机入口依赖DirectShow；独立安装并加入PATH。离线模拟测试通过不意味着已打开真实相机或完成编码验收。
- Tk：由Conda的tk包提供，供Pillow的ImageTk和观察窗口使用；不是pip包。
- mpremote：只有向MicroPython板复制/运行文件时才需额外安装，不是本轮离线128项测试的依赖。
- SOLIDWORKS及CAD工具：原生模型复核工具，不纳入Python运行环境；不因Conda检查通过声称原生CAD重新校验。

## 官方参考

- Conda创建与环境管理：https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html
- Conda环境导出：https://docs.conda.io/projects/conda/en/stable/commands/env/export.html
