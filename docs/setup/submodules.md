# 独立驱动子模块维护

线轨库远端：https://github.com/FreakStudioCN/micropython-linear-stage
套装接入位置：`drivers/micropython/linear_stage/`。

独立库保存驱动源码和自己的Git历史；套装以Git子模块记录一个精确提交。独立库main有新提交后，套装不会自动升级。通常不需要修改仓库URL或`.gitmodules`，需要更新的是套装中的子模块提交指针。

## 第一次取得源码

两个仓库均为私有仓库，Git身份需要同时具备访问权限。

```sh
git clone --recurse-submodules https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit.git
```

已经克隆套装时，在套装根目录执行：

```sh
git submodule update --init --recursive
git submodule status
```

## 维护者：让套装采用独立库的新版本

1. 在独立开发库`micropython-linear-stage`修改驱动、测试、提交并推送。必须先推送，不能让套装引用仅存在于本机的提交。不在套装旧兼容转发文件中维护第二份驱动。
2. 在套装根目录检查工作区及子模块状态，保留未提交工作。初始化子模块后，获取远端并选择明确审阅过的完整commit；不要把同级本机绝对路径写入`.gitmodules`。

```sh
git status --short
git submodule update --init --recursive
git -C drivers/micropython/linear_stage status --short
git -C drivers/micropython/linear_stage fetch origin
git -C drivers/micropython/linear_stage log --oneline HEAD..origin/main
# 将下方占位符替换为已审阅、已推送的完整提交号
git -C drivers/micropython/linear_stage checkout --detach REPLACE_WITH_REVIEWED_COMMIT
python -B tools/sync_linear_stage.py
```

同步工具只从干净子模块同步三项套装资产：板级bringup、exercise示例、传感器说明；驱动源码不复制。它同时更新`hardware/linear_stage/source-lock.json`中的提交和散列。同步前检查这些套装资产是否存在独立修改，避免覆盖尚未处理的工作。

3. 暂存指针与关联资产后运行回归。来源测试会核对**暂存的子模块指针**与来源锁，所以这一处git add放在测试之前；测试失败时不要提交或推送。

```sh
git add drivers/micropython/linear_stage hardware/linear_stage/source-lock.json firmware/linear_stage/bringup.py examples/linear_stage/exercise.py hardware/linear_stage/sensor-inputs.md
git diff --cached --submodule=log
python -B -m unittest discover -s tests -v
node simulator/check_math.mjs
node simulator/check_gripper.mjs
```

4. 检查结果并更新需要变化的使用说明，再提交和推送套装：

```sh
git commit -m "Update pinned linear-stage driver"
git push origin main
```

以上按当前main工作流举例；有分支/PR流程时提交到对应分支。不要把无关修改混入升级提交。套装只在这个提交推送后，才向其他使用者提供新版本指针。

## 使用者：取得套装已经固定的新版本

在没有未处理本地修改的套装根目录执行：

```sh
git pull --ff-only
git submodule update --init --recursive
git submodule status
```

这会检出套装记录的提交，不是独立库任意最新main。子模块处于detached HEAD是正常的固定版本状态。不要用`git submodule update --remote`替代审核升级流程。

更新本地子模块不会自动更新开发板。需要部署时，按实际端口和现场条件，从子模块内复制真正的`tb6600.py`及按需`linear_stage_inputs.py`；不要复制旧PC兼容转发文件。更新源码与离线检查不代表已完成新一轮硬件验收。

## 只有远端地址变更时

维护者修改并提交`.gitmodules`中的URL；使用者拉取套装后，再执行：

```sh
git submodule sync --recursive
git submodule update --init --recursive
```

若新提交不适用，按同一审核、同步和测试流程固定回已验证的旧commit，再提交套装指针；不要靠复制旧驱动文件回退。
