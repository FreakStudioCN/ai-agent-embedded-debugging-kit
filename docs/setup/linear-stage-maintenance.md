# 线轨：套装内直接维护与部署

线轨是本套装组成部分，自2026-11-24起取消Git子模块和独立发布同步。唯一当前维护源在本套装，原仓库仅保留历史，不删除旧提交。

## 文件归属

|内容|维护位置|
|---|---|
|MicroPython驱动与传感器适配|drivers/micropython/linear_stage/tb6600.py、linear_stage_inputs.py|
|板级接线、RMT创建及受控实验|firmware/linear_stage/|
|套装使用示例|examples/linear_stage/|
|参数审计/单位换算|host_control/linear_stage.py|
|单元测试|tests/test_tb6600.py、test_linear_stage_inputs.py、test_linear_stage.py、test_linear_stage_source.py、test_linear_stage_rpm_profile.py|
|硬件与电平/接线|hardware/linear_stage/|
|机械/CAD状态|mechanical/linear_stage/README.md|
|许可和历史来源|驱动目录LICENSE、hardware/linear_stage/provenance.json、docs/archive/linear_stage_source/|

## 获取与开发

```sh
git clone https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit.git
cd ai-agent-embedded-debugging-kit
# 已有套装：先保留未提交工作，再正常拉取
git pull --ff-only
```

无需--recurse-submodules、git submodule update或独立库访问权限；不再更新gitlink/source-lock，也不运行已退役tools/sync_linear_stage.py。原source-lock和同步脚本只以历史文本保存在archive，现provenance记录来源，不锁定将来的维护修改。

如果旧工作区曾初始化子模块，普通pull可能因原目录残留而受阻：先确认该目录是否有未提交代码并备份，将旧子模块工作目录移出工作树，再拉取；不要强制覆盖本地改动。新克隆不需要此迁移步骤。

直接编辑本仓库对应层级。旧drivers/micropython/tb6600.py和linear_stage_inputs.py仅为PC导入兼容，不在其中复制或维护另一套业务逻辑。

```sh
python -B -m unittest discover -s tests -v
node simulator/check_math.mjs
node simulator/check_gripper.mjs
git diff --check
# 检查差异后，仅暂存本次相关文件、提交和推送
```

更新接线和实例参数时同步hardware/linear_stage/inventory.json、组件说明与相关测试。provenance中的原提交/原散列是历史证据，不能改写成新源码的伪来源。

## 板端复制

按现场身份确认端口、供电及安全条件；以下文件复制不等于授权运动，工具可能复位设备：

```sh
mpremote connect YOUR_PORT fs cp drivers/micropython/linear_stage/tb6600.py :tb6600.py
mpremote connect YOUR_PORT fs cp drivers/micropython/linear_stage/linear_stage_inputs.py :linear_stage_inputs.py
mpremote connect YOUR_PORT fs cp firmware/linear_stage/bringup.py :bringup.py
mpremote connect YOUR_PORT fs cp examples/linear_stage/exercise.py :stage_exercise.py
```

不要复制父目录的PC兼容转发文件；不写main.py自动启动。传感器未配置时返回未知，不能据软件预留推定已经完成电平转换、限位联锁、回零或编码器闭环。现有robot_arm导入名与根package.json单文件分发不变。

## 来源与历史

原仓库：https://github.com/FreakStudioCN/micropython-linear-stage ，来源8b184a4。套装通过非压缩合并保留原提交关系，原文件可git show 8b184a4:path查看。旧README/同步约定归档且明确失效，不作为第二维护源。原MIT许可保留。
