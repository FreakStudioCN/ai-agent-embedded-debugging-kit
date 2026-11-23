# 仓库更名与迁移实际核验

日期：2026-11-23（北京时间）。实施依据：11月20日批准的v1.8方案。原仓库原地更名，保留b02d097及全部祖先历史；没有新建替代仓库或重写历史。

## 已实施

- 新URL：https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit 。origin已更新，旧Git地址的ls-remote可重定向。
- 维护源分入drivers、host_control、camera、recording、safety、mechanical、examples、docs等；旧根/code/cv_pipeline命令兼容。迁移映射见repository-file-migration.csv。
- 绿色机械臂与桌面搭子专用实现及文档归历史PoC。通用轴线拟合已提取到perception；观察JSONL读取与真实JPEG交付入口已提供。完整统一SDK、更多算法提取、流式数据契约尚未完成，不在README宣称可用。
- 选定原生CAD/STEP及实际3MF已入mechanical；69份上游资料逐文件SHA256与原manifest一致。原生引用报告保留，文件加载结论不扩大为实物验收。

## 离线核验结果

- Python unittest：128项通过，包含新增迁移/模块身份、单文件分发、通用算法依赖边界、图片交付及静态路径越界检查。
- node simulator/check_math.mjs：639项运动学、边界与路径检查通过。
- node simulator/check_gripper.mjs：夹爪联动/安装/TCP及G-code时间轴通过。Node对第三方Three.js给出MODULE_TYPELESS_PACKAGE_JSON提示，不影响结果；不为此改变MicroPython包清单用途。
- 老/新串口CLI、相机、录像CLI的--help离线启动检查；未连接实体设备、未执行新运动。
- 根robot_arm.py与旧code/robot_arm.py均与drivers/micropython/robot_arm.py字节一致；package.json保留0.1.0和相对源路径，只安装robot_arm模块。

## 远端下载核验

首次推送后检查旧/新Git地址、仓库页面、raw package.json及其相对驱动源。结果将随同本次提交后的远端核验补充；不把HTTP下载核验表述为板端固件安装/实机运行测试。

## 范围与遗留

线轨/综合控制板、灯光、电源功耗、音频与热成像仍标规划或未确认交付，不新增硬件研发。两套逐项安装证据、第二套实物尺寸及运动问题按另封任务跟进。原未跟踪微信视频及.runtime日志/配置未提交；既有文档补充已保留在历史记录。
