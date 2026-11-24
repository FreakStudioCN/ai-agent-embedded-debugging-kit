# AI Agent 嵌入式设备自动化调试套装仓库整理方案

实施记录 v2.0，2026-11-23；v1.8已于2026-11-20获批执行，仓库更名及重组已实施。以下设计历史中的待确认措辞不再作为本轮实施前置，当前状态以第十节及实际核验报告为准。

## 一、目标与本次范围

仓库面向Codex等AI Agent，定位为AI Agent嵌入式设备自动化调试套装的统一工程入口，覆盖观察机械臂与夹爪、线轨/滑台及综合控制器、USB相机、灯光、电源控制与功耗测量、音频和热成像，以及共用算法、观察路径、记录和操作Skill。当前已有PoC与规划模块逐项标记状态；本轮仅调整工程定位、名称方案和资料组织，不新增硬件开发或验收范围。

本轮更新目录方案、逐文件迁移对应表、README结构和模型接收清单，明确通用算法库、结构化数据流与直接多模态看图两条观察路径，并将Agent操控机械臂的robot-arm-control Skill作为正式软件交付入口。当前仅修改方案文档，代码提取、接口实现和文件迁移均在后续实施。实际目录迁移、调用路径修改与新增原生CAD入库，待方案确认后实施。现有未提交的README、快速扫视说明、MttoRobot进度和视频需在实施前明确纳入哪次提交。

### 1.1 推荐名称、URL与README定位

| 项目 | 当前 | 推荐/更名后（待确认实施） |
| --- | --- | --- |
| GitHub仓库名 | micropython-robot-arm | ai-agent-embedded-debugging-kit |
| 仓库URL | https://github.com/FreakStudioCN/micropython-robot-arm | https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit |
| Git远端 | https://github.com/FreakStudioCN/micropython-robot-arm.git | https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit.git |
| README主标题 | RobotArm 驱动与 Codex 观察调试环境 | AI Agent Embedded Device Debugging Kit |

推荐在同一FreakStudioCN仓库上更名，保留提交、标签、Issue与既有历史。README定位：面向AI Agent的桌面嵌入式设备自动化调试套装，提供观察、测量、声音交互、供电控制及机械操作的统一资料与工具入口；现成机械结构、自研控制板、MicroPython固件及PC Python API是总体方向，统一API和完整套装未完成项明确标规划。

### 1.2 更名引用清单及兼容安排

| 类别 | 引用位置 | 建议及兼容检查 |
| --- | --- | --- |
| 仓库及远端 | GitHub仓库设置；本地origin | 同一仓库更名并更新origin，不重建仓库或丢失历史；审批后核对管理员权限/名称占用；当前未更名 |
| 包分发 | package.json；tools/sync_driver.py；tests/test_distribution.py；docs/driver.md；README | 更名后文档使用新仓库mip地址；安装模块名及单文件边界不变；先单独更名且保持路径；迁移源码后保留code/robot_arm.py为可独立安装的同步副本，不能换成依赖PC包的转发器；检查旧/新mip及raw下载 |
| Skill | .agents/skills/robot-arm-control/SKILL.md；agents/openai.yaml | 保留Skill名称与$robot-arm-control显式调用，描述其是套装中机械臂操作Skill；更新整体工程名、路径和链接；尚未实现模块不写成Skill可执行能力 |
| AGENTS与本地路径 | AGENTS.md；仓库根定位和.runtime | 更新整套工程定位，保留组件规则；无需同步改本地文件夹名；检查ROOT/parents[n]；不以仓库slug作为Python包名，不改串口/相机服务端口 |
| 脚本/导入 | code/*.py；根兼容入口；start_*.cmd；simulator/serve.py | 仓库改名不改Python导入；目录迁移按已审方案保留转发；核对子进程、mock.patch、mip分发副本；更名和源路径迁移分别验证 |
| 模型清单 | simulator/models/manifest.json；model-manifest.json；模型说明 | 仅更新本库当前入口及归档指向，保留原来源URL/许可证/哈希；不把上游、历史来源URL盲目替换成本库新名；原始模型不重写 |
| 示例 | examples规划入口；docs/quick-scan.md；docs/embodied-demo.md；docs/mtto-robot-progress.md | 正式组件导航覆盖整套工程；双绿臂和桌面搭子继续历史PoC；当前可用命令与拟实施命令分别标注；历史外部仓库保留来源 |
| 云文档 | 当前整理方案；总任务；试装资料；已发回复/附件索引 | 当前方案更新整套定位；确认更名后同步相关文档中的现行仓库链接；历史正式版本与固定提交证据保留，不改成虚假的历史新地址 |
| 其他分发/集成 | 已跟踪文件范围的.github、Pages和外部调用方 | 如有Pages、被其他工作流uses引用的Action，单独核对；GitHub普通网页与Git重定向不保证Pages或Action兼容；不复用旧仓库名以免破坏重定向 |

完整引用表见repository-rename-references.csv。现有package.json版本为0.1.0，源路径为相对code/robot_arm.py，未写死仓库slug；更名本身不必改清单内部路径。建议mip新入口为github:FreakStudioCN/ai-agent-embedded-debugging-kit，旧入口github:FreakStudioCN/micropython-robot-arm用于迁移兼容核对；当前没有更名，推荐地址不作为已生效入口发布。之后目录迁移时，根robot_arm.py/example.py及旧code/robot_arm.py保持独立MicroPython副本并由同步工具生成，避免旧mip清单安装到PC兼容包装器。

GitHub官方说明普通仓库网页与旧Git clone/fetch/push会重定向；更名后仍更新origin为新URL。raw内容、mip客户端、固定提交下载以及迁移后的文件路径逐项实际核对，不仅凭重定向推定可用。兼容期不复用旧仓库名；如存在Pages或作为Action被外部引用，按其特殊行为单独处理。官方依据：https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository 。

### 1.3 实施顺序与验收边界

本次先提交推荐名称、旧新URL、README定位、完整组件矩阵及引用清单供确认。确认前不执行GitHub更名、git remote set-url、目录搬移或调用路径修改。批准后先在路径不变的情况下更名并验证Git/分发/链接，再按v1.7子分类分阶段迁移，逐项验证兼容入口；更名与路径变化分别留存验证结果，便于定位问题。

模型、3MF及原生引用报告继续保留。文件加载通过不代表实物尺寸、第二套转接件安装或两套画面/运动证据已通过；这些工作按另封任务推进，不纳入本轮更名与资料整理完成项，也不重复扩大已确认的第一套试装验证范围。

## 二、模型已收资料与打印输入

| 资料 | 已取得情况 | 核对结果与后续 |
| --- | --- | --- |
| “机械臂夹爪及相机支架 (2).zip” | 14个SLDPRT、2个SLDASM、8个STEP | 用户于2026-11-20明确指定本包；本仓库当前assembly.step与其中总装STEP字节一致 |
| “机械臂夹爪及相机支架(3).zip” | 14个SLDPRT、2个SLDASM、8个STEP | 与(2)包有6个文件不同，保留为历史来源，本次基准采用用户指定的(2)包 |
| 当前已入库STEP | 2026-11-19更新，提交b02d097 | SHA256为86e7c25c54a7ed36d31249b48f3d4bfed592c4a7222a7adad6601eb257c9c5b6 |
| 打印输入 | 已有装配及分件STEP，另收到用户当前实际使用的3MF | 用户于2026-11-20补充当前打印使用的“观察机械臂夹爪固定摄像头.3mf”，已与指定(2)包共同打包；STEP仍可用于切片，额外派生记录按实际产生情况归档 |
| 观察机械臂夹爪固定摄像头.3mf | 185,442字节；用户确认是当前打印使用的3MF | 已核对原件与归档副本SHA256一致；拟放当前试装版本print/目录，随模型资料和方案附件提供 |
| 原开源机械臂 community_robot_arm | 已入库69个上游文件，共45,720,412字节；含61个STL、2个STEP、1个STP及README、LICENSE和3份参考源码 | 固定提交6c2f57390f0186f47bb199f06c875dedf8de268f；本次逐文件SHA256核对全部通过，纳入正式模型归档 |
| 试装照片与相机适配 | 5张照片已在试装云文档 | 用户已确认相机位置及相关适配验证无问题 |

(2)包STEP文件头导出时间为2026-11-19T04:49:58，(3)包为2026-11-18T11:44:45，文件头未标时区。两包差异涉及底板、右侧定制齿轮及总装的原生文件和STEP，共6个文件。用户已明确指定(2)包作为当前试装资料基准，现有STEP作为打印输入归档；本次补收用户当前打印使用的3MF，作为该试装资料基准的打印记录关联；其他新增打印参数或临时修改记录按实际产生情况登记。

两套原始压缩包及逐文件SHA256已暂存在本机忽略目录`.runtime/model-intake-20261120/`。保留来源、文件名、归档散列和内容散列。已使用SOLIDWORKS 2026对指定(2)包完成原生引用校验：14个零件、2个装配文件均可打开，加载错误为0；总装11个组件（含嵌套）及舵机子装配2个组件均正常加载，引用文件全部来自包内，缺失依赖为0。校验只读、不保存，全部24个原文件散列保持一致。

用户已确认现有STEP可用于打印。本轮同时归档自研夹爪及相机支架和原开源机械臂模型：自研部分按指定(2)包中的原生CAD及STEP组织入库，开源部分按固定上游版本保留完整已收模型文件。已收到的当前打印3MF与原生CAD、STEP一并打包归档，其余新增派生文件与打印参数按实际产生情况登记。

原开源模型来自20sffactory/community_robot_arm，基于Florin Tobler的设计。现有simulator/models/upstream/及simulator/models/manifest.json已跟踪入库；本次方案将其统一归档到mechanical/upstream/community_robot_arm/，保留完整已收快照及原始子目录。CAD与图形资料按上游README登记为CC BY 4.0，附带参考固件源码按GPL-3.0登记；PROVENANCE.md记录作者、上游链接、固定提交、许可证链接及本地修改。自研试装模型与开源原版分别标识，说明两者的安装对应关系，照片重建模型仍保留其估算来源标识。

本次3MF的SHA256为dbd21252006c6e3fd665784221bcf53f89966c205299c44227c7b9f53348875e。已完成压缩包CRC及8份模型XML可读取检查，未改写原文件。模型资料包包含用户指定的(2)原始压缩包、当前3MF及model-manifest.json；公开清单保留来源说明与散列，不包含本机绝对路径。用户已确认该3MF对应指定(2)包中的有效打印模型，此对应关系不再列为待核对项。原生引用检查报告native-reference-check.json随附件提供。

原生装配复现注意：SOLIDWORKS默认Toolbox搜索曾自动以本机标准库齿轮替代包内齿轮。本次临时关闭“将Toolbox文件夹作为默认搜索位置”后重新验证，两件齿轮均加载自包内，并在结束后恢复原设置。打开提示中有一个零件需要重建、部分文件在校验会话中已打开；未发现缺失引用。该结论覆盖文件引用和装配加载，不等同于完整特征重建或实物尺寸验证。

### 2.1 本次实际摄像头安装照片与短运动记录

本节补充2026-11-20本次新装一套观察机械臂的实际摄像头安装资料。5张照片展示连接处、正面、整机侧面和走线，实际USB摄像头已安装；不将同一套的多角度照片当作两套分别完成的证据。

相机已被电脑识别并输出实时画面；在用户现场监控下完成使能、回零及分段短运动。底座目标约±72°，前后Y140～232、Z70～144 mm，各段有等待，最后目标X0 Y174 Z120；21条指令无协议错误或超时。用户现场检查确认本次测试范围内新夹爪、摄像头支架及走线未发生干涉、碰撞或拉扯。该结论不等同于完整工作空间、精度或长期可靠性验收。

模型采用指定“机械臂夹爪及相机支架 (2).zip”，当前打印文件为“观察机械臂夹爪固定摄像头.3mf”，对应关系由用户确认；原生引用报告已附。打印材料尚未提供，不能仅凭蓝色外观推定材料。此前一套的安装资料见原试装文档；本次5张照片及运动记录归本次新装一套，两套完整逐项清单分别登记。

图1：腕部与蓝色夹爪底板、实际USB摄像头的侧面安装关系及连接处。
图2：摄像头背面、固定件螺丝及USB线引出方向；静态照片中USB插头未接电脑，不作为在线画面证据。
图3：正面安装与整机连接关系，可见实际摄像头及下方夹爪。
图4：整机侧面安装状态、夹爪及摄像头位置，线缆沿连杆固定。
图5：关节附近USB线走向与预留线段近照；运动中是否拉扯以现场检查和视频为依据。

手机运动录像及相机录像：PoC阶段证据（内部来源，链接不公开）。

## 三、建议目录

```text
ai-agent-embedded-debugging-kit/   # 已于2026-11-23更名
├── README.md
├── AGENTS.md
├── package.json
├── robot_arm.py                 # MicroPython分发副本
├── example.py                   # MicroPython分发示例
├── requirements-*.txt
├── hardware/
│   └── <组件ID>/                # 型号、接线、电源、BOM、板卡工程
├── firmware/
│   └── <控制板ID>/              # 实际设备端固件及构建/烧录说明
├── drivers/micropython/
│   └── robot_arm.py             # UART驱动维护源
├── host_control/                # PC串口、会话、事件与扫视
├── camera/                      # USB共享采集服务
├── safety/                      # 共用实验门禁与恢复状态边界
├── recording/                   # 原始录像、同步与导出工具
├── perception/                  # 仓库内通用算法库，独立于设备与Agent供应商
│   ├── algorithms/              # 按实际可复用函数提取，不整文件改名冒充通用化
│   └── README.md                # 输入输出、参数、适用范围与验证边界
├── observation/                 # 两条观察路径的编排与Agent交付适配
│   ├── contracts.py             # 帧及观察结果的拟议数据契约
│   ├── structured.py            # 算法结果转结构化数据流
│   └── multimodal.py            # 图片与采集信息交付给多模态Agent
├── cv_pipeline/                 # 原有包入口兼容转发与迁移说明
├── visual_observation/          # 保留现有画面观察包命名
├── examples/
│   ├── micropython/
│   ├── observer_arm/
│   ├── observation/             # 两条路径的最小使用示例，按已实现能力提供
│   └── historical_poc/
│       ├── green_arms/
│       │   ├── README.md        # 历史范围、版本、复现条件与证据索引
│       │   └── cv_pipeline/     # 专用适配、实验编排及未抽取的历史候选
│       └── mtto_robot/
│           ├── README.md        # 历史动态演示与外部依赖
│           ├── dynamic_demo.py
│           ├── biped.py         # 从quick_scan拆出的专用控制适配
│           ├── mtto_overlay.py  # 桌面搭子专用识别参数及叠加
│           └── mtto_demo_window.py
├── mechanical/
│   ├── observer_arm/
│   │   └── gripper_camera_mount/
│   │       ├── README.md
│   │       ├── manifest.json
│   │       └── revisions/<已确认版本>/
│   │           ├── source/     # 原生CAD及装配依赖
│   │           ├── step/       # 完整装配与分件
│   │           ├── print/      # 已收到当前打印3MF；其他打印记录按实际产生情况登记
│   │           └── evidence/   # 经选择的试装证据/云文档索引
│   ├── photo_reconstruction/   # 照片估算模型与生成脚本
│   └── upstream/
│       └── community_robot_arm/
│           ├── PROVENANCE.md   # 上游、固定提交、署名、许可及修改记录
│           ├── manifest.json   # 全部已收文件、来源URL及SHA256
│           ├── CAD Files/      # 整机STEP、外壳STEP/STP及61个STL，保留子目录
│           ├── README.md       # 保留上游原文
│           ├── LICENSE         # 保留上游固件许可证原文
│           └── arduino_firmware/ # 已收3份尺寸/运动学参考源码
├── simulator/                  # 浏览器工具及Three.js依赖
├── docs/
│   ├── setup/
│   ├── components/
│   ├── experiments/
│   ├── design/
│   └── archive/
│       └── historical_poc/
│           ├── green_arms/       # 历史双臂及视觉实验说明
│           └── mtto_robot/       # 历史桌面搭子记录与专用扫视演示
├── tests/
├── tools/
├── .agents/skills/
│   └── robot-arm-control/
│       ├── SKILL.md             # Agent操作流程、工具选择与执行反馈核查
│       └── agents/openai.yaml   # 显示名称、说明及显式调用提示
└── .runtime/                   # 运行输出、候选模型、本机依赖，忽略
```

按硬件、固件、驱动、机械、示例和文档分层，使用一致的组件ID关联各层。只为已收到的材料创建目录。规划中的组件在组件清单里列出状态，材料到位后建立对应目录。

### 3.1 共用基础与两条观察路径

相机采集、帧编号、时间戳、机位与坐标信息、原始证据和录像索引由共用层提供。perception作为本仓库内可复用Python算法库，输入图像/掩码及显式参数，输出测量或事件；observation负责编排与向Agent交付。控制命令经独立host_control/驱动及现有安全边界执行，算法库和图片交付层不直接控制设备。

| 路径 | 数据流 | 交付给Agent及适用场景 | 实现边界 |
| --- | --- | --- | --- |
| 结构化数据流 | camera → perception算法 → observation.structured → Agent | 对象、测量值、状态变化及质量字段组成JSON/JSONL流，适用于持续监测与可解释测量；该路径默认只交付数据，证据图片按需另取 | 算法处理不调用多模态模型；已有JSONL字段通过适配延续，不改写历史日志 |
| 直接多模态看图 | camera → observation.multimodal → 图片及采集信息 → 多模态Agent | 向Agent实际交付图片像素及帧信息，适用于场景理解、未知对象和执行结果核查；直接路径不以算法结果为前置 | image_ref用于追溯，不能代替模型实际收到图片；由Agent宿主支持的图片附件/工具或模型接口交付，不绑定供应商 |

两条路径均可单独使用，也可在同一实验中按需切换。算法路径的数据可带证据帧引用，Agent需要核查时再取对应图片；两条路径用同一frame_id关联，按需采集新鲜帧并记录采集与交付时间，不默认让模型逐帧看视频。

### 3.2 拟议数据契约与追溯

FramePacket：schema_version、run_id、camera_id、frame_id、captured_at、delivered_at、图像尺寸、旋转/裁剪变换、view_id、coordinate_frame及calibration_id（适用时）。图片内容通过相应交付通道传递，image_ref指向可追溯证据。跨机位变换未经验证时明确未知，不把图像像素当毫米或真实关节角。

ObservationRecord：引用FramePacket标识，并包含producer、algorithm_version、参数/配置版本、对象ID、观测类型、measurement、unit、coordinate_frame、valid、质量指标、拒绝原因和证据引用。无效测量用null并说明原因；质量分数不默认解释为概率，算法测量、模型推断、指令目标和执行反馈分别记录。旧JSONL通过显式适配提供新契约，保留原字段与版本。

直接看图路径记录图片交付成功/失败、问题上下文及必要的机位信息；如保存Agent输出，标明multimodal_agent来源及模型信息（可取得时），不伪装成算法实测值。两条路径共享超时、过期帧、错误事件及记录索引；本节字段为拟议接口，尚未实现。

### 3.3 算法、设备适配与实验的边界

按现有函数逐步提取轮廓/直线主轴拟合、特征跟踪、背景变化/图像配准及窗口统计中可独立部分，初期不新增识别能力。perception不导入串口控制、实验恢复、设备仓库或Agent API；掩码、标定和阈值由调用方显式传入。绿臂颜色与连杆几何、桌面搭子屏幕ROI和动作先验留在各自历史示例的adapters/config中，实验脚本负责组合算法、数据源、控制和评价。

现有contour_axis_2d.py混有绿色分割、green_1/green_2身份及叠加；phase_r_background.py含绿色排除和安全异常；vision_lk.py动态适配Mr-Robot-Arm。它们均不能整文件迁入通用库：原专用实现归历史PoC，通用计算函数另行提取并对照录制数据验证，旧cv_pipeline及根入口保留兼容适配。桌面搭子专用mtto_overlay.py、mtto_demo_window.py和dynamic_demo.py同样归历史示例，后者复用的通用图像处理再按函数提取。

### 3.4 Agent操控机械臂的Skill

将现有.agents/skills/robot-arm-control/SKILL.md及agents/openai.yaml作为正式软件交付保留，路径稳定，并在根README和AGENTS.md提供清晰入口。该Skill目前已覆盖长连接串口、实时摄像头、HTML仿真、移动、夹爪开合、等待与结果核查；本轮仅整理其在方案中的位置，尚未修改Skill内容或执行设备动作。

Skill负责把用户目标组织成“观察 → 判断 → 操作 → 等待 → 再观察 → 记录结果”的工具调用流程。它可选择observation的结构化数据路径，或直接获取图片交给多模态Agent；需要核查时用frame_id关联原始证据。移动/夹爪指令仍通过host_control长连接和现有驱动执行，算法库、图片交付层及仿真均不代替实机驱动。

Skill正文整理范围：适用任务与显式调用、环境和设备枚举、复用已有相机/串口服务、两种观察路径、仿真与模型入口、移动/夹爪命令、超时与恢复、完成判定及日志。保留当前授权规则和真实设备边界；控制器ok、指令目标、视觉停稳与实测反馈分别记录，不编造位置、完成反馈或急停能力。完成后报告执行范围、最后目标、图像/数据证据及未核实状态。

agents/openai.yaml仅维护显示名称、说明和默认调用提示；具体操作要求放SKILL.md，协议、安装和实验细节链接到对应文档，避免多处复制命令。AGENTS.md引导执行前读取该Skill；历史双绿臂和桌面搭子复现入口仅链接到历史示例，不成为当前机械臂Skill的默认依赖。迁移后Skill统一引用新维护入口并说明旧命令兼容方式，双路径接口实现前沿用当前可用命令并明确规划状态。

## 四、组件与各层对应

| 组件ID | 职责及现有基础 | 入口与各层对应（拟组织位置） | 实现状态与关系 |
| --- | --- | --- | --- |
| robot_arm_control_skill | Agent观察、操作、等待和结果核查 | .agents/skills/robot-arm-control/；AGENTS.md；README | 现有机械臂Skill保留，名称不因仓库更名改变；套装其他组件先在README导航，按实际实现扩展Skill能力 |
| observer_arm | 三轴观察机械臂、夹爪、UART与仿真 | hardware/observer_arm；drivers/micropython；host_control；mechanical/observer_arm；examples/observer_arm；docs/components/observer_arm.md | 现有观察/控制PoC及模型资料；原生引用通过仅证明文件加载，第二套实装与尺寸/运动验证不在本轮完成结论内 |
| linear_stage | 带编码器线轨/滑台，承载相机、补光或热成像 | hardware/linear_stage；firmware/stepper_servo_controller；examples/linear_stage；docs/components/linear_stage.md | 规划/当前仓库未确认完整交付；与机械臂共用综合控制器，后续能力按实际交付登记，不因更名启动开发 |
| stepper_servo_controller | 机械臂3轴+滑台1轴、夹爪PWM、限位/编码器及保护 | hardware/stepper_servo_controller；firmware/stepper_servo_controller；drivers中实际驱动；examples/stepper_servo_controller；docs/components/stepper_servo_controller.md | 自研综合控制板及固件属规划；当前UART驱动不等于该板或统一API已实现，STEP/DIR和实时脉冲能力按原任务验证 |
| camera | USB图像采集与机位信息，供双观察路径使用 | camera；observation；perception；visual_observation；hardware/camera；examples/observation；docs/components/camera.md | 已有USB共享采集、监控及录像；USB直接连接PC，末端双目/滑台部署按实际状态登记，不将现有USB采集视为双目能力已完成 |
| lighting | WS2812补光、颜色/亮度及灯光供电切换 | hardware/lighting；firmware/lighting；examples/lighting；docs/components/lighting.md | 控制板/接口按规划登记；与相机观察联动，现成灯板独立供电及保护依原任务执行 |
| power_meter | USB/电池电压电流功率能量采集、被测设备断电重启 | hardware/power_meter；firmware/power_meter；examples/power_meter；docs/components/power_meter.md | 规划/当前仓库未确认实现；负载供电切换属于该板及综合控制/灯光板各自职责，不新增独立继电器开发；微安测量和保护按原任务验证 |
| audio | USB麦克风录音、扬声器播放及Agent声音交互 | hardware/audio；host_control中PC音频接口（交付时建立）；examples/audio；docs/components/audio.md | 规划/当前仓库未确认实现；成熟USB音频直接接PC，不新增ESP32音频控制板或DSP研发 |
| thermal | MLX90640温度矩阵、区域统计及PC热图 | hardware/thermal；firmware/thermal；drivers中实际传感器驱动；examples/thermal；docs/components/thermal.md | 规划/当前仓库未确认实现；通过适用的MicroPython/USB接口向PC送矩阵，与相机/滑台共享观察位置，常规供电保护沿原任务 |

正式组件表列出完整套装规划与观察臂当前能力。绿色机械臂和桌面搭子均按用户确认归入历史PoC示例，从正式组件、硬件、固件及验收清单移出。两者专用演示、CV适配、实验与说明分别进入examples/historical_poc/<设备>/及docs/archive/historical_poc/<设备>/，保留视频、代码版本、日志索引及未验证边界。通用相机、观察窗口、录像与控制接口继续共用，主线安装运行无需两套历史设备的外部仓库、网络地址或板端预设。统一API中的stop、运动完成和硬件急停等能力，按实际设备支持情况填写，沿用现有明确的目标值与物理反馈区分。

## 五、旧文件迁移对应表

逐文件清单见同目录`repository-file-migration.csv`，覆盖本次清点的242个已跟踪文件，另增本次收到的1份3MF，共243条来源映射。以下列出主要迁移组。

| 当前路径 | 建议维护位置 | 兼容与影响 |
| --- | --- | --- |
| .agents/skills/robot-arm-control/SKILL.md、agents/openai.yaml | .agents/skills/robot-arm-control/原位置保留 | 正式Agent操作入口；与新驱动/会话/相机/仿真及双观察路径同步核对，现有命令与拟实现接口分别标明；README与AGENTS链接一致 |
| code/robot_arm.py | drivers/micropython/robot_arm.py | package.json的源URL、同步脚本、分发一致性测试和文档命令同步修改 |
| code/main.py | examples/micropython/main.py | 根example.py继续由同步工具生成，保留显式执行方式 |
| code/pc_control.py、code/pc_session.py、code/exploration_events.py、code/quick_scan.py | host_control/pc_uart.py、session.py、events.py、quick_scan.py | code旧入口提供兼容转发；内部导入改包路径 |
| code/dynamic_demo.py | examples/historical_poc/mtto_robot/dynamic_demo.py | 历史PoC单独列出动态演示；:dynamic仅作按需加载的兼容入口，更新子进程及专用窗口路径，主线启动不连接桌面搭子 |
| camera_server.py | camera/server.py | 根入口兼容转发，更新启动器与内部引用 |
| experiment_recorder.py | recording/recorder.py | 根入口兼容转发；quick_scan的录像子进程路径和CLI帮助同步核对 |
| experiment_safety.py | safety/experiment.py | 根导入别名映射到同一模块对象，避免出现两份锁或状态 |
| monitor_core.py | visual_observation/core.py | 原入口兼容；UI与CV共享读帧/事件逻辑，保持纯观察导入轻量 |
| cv_pipeline/**、visual_observation/** | 通用算法逐函数提取至perception/algorithms；数据编排至observation；两套设备专用实现归入各自historical_poc；共用监控保留visual_observation | 按数据契约提供适配并保留历史JSONL原文及旧入口；设备几何、阈值、标定与动作先验留设备适配，纯算法不依赖串口、历史仓库或Agent API |
| cv_pipeline/contour_axis_2d.py、phase_r_background.py、vision_lk.py等 | 专用原实现至historical_poc/green_arms；可复用函数提取至perception/algorithms | 先分离颜色、几何、阈值、安全及外部仓库适配；保留旧入口，对照历史帧验证，不将候选算法标为已验收 |
| cv_pipeline/mtto_overlay.py、visual_observation/mtto_demo_window.py | examples/historical_poc/mtto_robot/对应文件 | 专用ROI、屏幕识别与窗口归历史；主线不加载专用叠加，更新动态演示的子进程和导入 |
| code/quick_scan.py | host_control/quick_scan.py及examples/historical_poc/mtto_robot/biped.py、scan_demo.py | 共用采集/扫视与Biped及双设备编排拆分；保留旧参数兼容入口并按需加载，主线不连接历史设备 |
| 根目录CV同名脚本、tools中CV旧入口 | 保留兼容转发；新算法维护入口为perception，观察流程为observation，历史实验使用examples.historical_poc对应入口 | 不复制第二套业务逻辑，模块身份一致性纳入检查 |
| 根robot_arm.py、example.py、pc_control.py | 保留分发副本或兼容入口 | MicroPython复制安装与旧PC调用仍可用 |
| simulator/models/gripper_camera_mount/** | mechanical/observer_arm/gripper_camera_mount/revisions/2026-11-19-received/step及说明 | 版本关联用户指定的(2)包及本次实物试装，STEP及用户当前打印3MF作为打印资料，其他派生记录按实际产生情况归档；旧GitHub文件链接用固定提交追溯 |
| 观察机械臂夹爪固定摄像头.3mf（本次新增来源文件） | mechanical/observer_arm/gripper_camera_mount/revisions/2026-11-19-received/print/观察机械臂夹爪固定摄像头.3mf | 原文件原样归档，记录用户确认用途、来源与SHA256；资料包已包含，正式仓库入库仍随批准方案实施 |
| simulator/models/custom_gripper/** | mechanical/photo_reconstruction/** | 原参数、层级和生成输出保持对应；STL属于重建参考，实际采用的打印输入按来源登记 |
| simulator/models/upstream/**、manifest.json | mechanical/upstream/community_robot_arm/**、mechanical/upstream/community_robot_arm/manifest.json | 将整机及分件模型作为正式入库内容，保留上游内部目录、原README、许可与散列；补充PROVENANCE.md，迁移manifest，更新download_models.py下载目标与仿真白名单资源映射 |
| simulator/*.html、*.js、*.mjs、vendor/** | 保留simulator内 | 静态资源URL映射到受控机械资源目录，检查下载链接、相对导入与碰撞测试路径 |
| docs/driver.md | docs/components/observer_arm-driver.md | 更新根README与技能链接，旧文档入口提供迁移索引 |
| docs/monitor.md、recording.md、quick-scan.md | docs/setup/对应文件 | 更新命令、启动器和相对链接；quick-scan中通用观察臂扫视留setup，双设备动态演示拆到docs/archive/historical_poc/mtto_robot/quick-scan-demo.md |
| docs/embodied-demo.md、contour-axis-2d.md、phase-r*.md | docs/archive/historical_poc/green_arms/对应文件；共用安全说明留docs/experiments | 双绿臂及专用视觉实验说明统一归入docs/archive/historical_poc/green_arms/；共用安全说明experiment-safety.md仍放docs/experiments/，保留门禁及恢复边界 |
| FreakStudio_Codex_Embodied_Debugging_Task_v*.md | docs/archive/specifications/原文件名 | 保留历史任务版本，当前范围链接到任务云文档 |
| docs/mtto-robot-progress.md（未跟踪） | docs/archive/historical_poc/mtto_robot/mtto-robot-progress.md | 经内容核对后单独纳入，记录其来源和关联素材 |
| 根目录微信视频（未跟踪） | 经选择的.runtime素材归档与飞书视频索引 | 先登记来源和演示版本，按忽略策略归档 |

新增目录的Python包命名避免与根pc_control.py冲突。固件目录保存设备端业务及构建/烧录说明，MicroPython UART库放drivers；当前code/main.py属于示例。仓库内上游Arduino源码继续随上游参考包保留许可和来源标识。

## 六、受影响的引用与运行路径

| 影响面 | 已定位位置 | 实施时的核对方式 |
| --- | --- | --- |
| 相对根目录与默认输出 | 各模块ROOT、parents[n]、.runtime路径、任务源码快照 | 统一从仓库根解析；旧新入口输出根一致，历史日志可继续回放 |
| mip安装和单文件分发 | package.json、tools/sync_driver.py、test_distribution.py | 源路径更新后同步分发副本，核对mip仍只安装robot_arm.py |
| Python导入与补丁 | sys.path加入code、根别名、cv_pipeline与测试mock.patch路径 | 迁移后使用包导入，兼容入口映射同一模块，避免全局状态重复 |
| 子进程与命令行 | code/quick_scan.py的RECORDER、dynamic_demo的窗口命令、start_*.cmd | 从仓库根、绝对路径调用分别验证，保持参数和返回码 |
| 仿真静态资源 | gripper-model.js、gripper.html、index.html、serve.py、check_mount.py | 受控URL映射或生成清单同步变更，逐个检查资源可访问及模型尺寸 |
| 模型生成与下载 | build_model.py的建模工具路径、download_models.py的ROOT与manifest | 临时CAD依赖通过明确配置提供，保持输出与散列可复核；开源模型下载目标及manifest统一到mechanical/upstream/community_robot_arm，下载脚本用于恢复和校验，模型实体随仓库保留 |
| 外部设备依赖 | 历史PoC中的recovery_workflow.py、experiment_cv.py、monitor_pose.py及可选骨架叠加 | Mr-Robot-Arm及桌面搭子外部接口均仅为各自历史示例的可选依赖；共用监控默认关闭专用叠加并按需加载。code/quick_scan.py的Biped及双设备编排拆到历史示例，通用采集/扫视与被复用PCUART提取至共用层；检查恢复源码与子进程路径 |
| 操作说明与技能 | README、docs、AGENTS.md、.agents/skills/robot-arm-control/SKILL.md及agents/openai.yaml | Skill与迁移后的驱动、串口会话、相机、仿真及双观察路径同一提交核对；保留显式调用入口，核查现有/拟议命令、日志目录、端口枚举和恢复边界 |
| Git资源属性 | .gitattributes、.gitignore | 迁移后保留STEP/STL等二进制属性和第三方资源散列；本机候选包留忽略目录 |

仿真服务继续限定静态服务范围。机械资源通过显式白名单目录映射提供，避免将包含日志、配置和本机资料的整个仓库根目录作为静态站点根目录。

## 七、README内容方案

README主标题推荐“AI Agent Embedded Device Debugging Kit”。开篇说明这是完整调试套装的统一入口，观察机械臂是其中一个组件。提供组件状态及入口矩阵，按已实现、已有资料待归档、规划、历史PoC分别登记；USB相机与音频由PC访问，定制控制板与其他适用模块通过USB串口/MicroPython接入。详细协议和历史实验下沉到对应说明。

1. 项目定位与范围。说明完整AI Agent嵌入式设备自动化调试套装；展示机械臂、线轨/控制器、相机、灯光、电源/功耗、音频及热成像的连接关系，明确已实现与规划。
2. 正式组件状态表。逐项给出完整套装各组件的作用、状态、安装/调用起点、硬件、固件/驱动、机械模型、示例和文档链接；没有已实现接口的明确标规划。绿色机械臂与桌面搭子仍列历史PoC。
3. 从哪里开始。先给Agent操作入口：链接robot-arm-control/SKILL.md、仓库内发现方式及显式调用示例“使用 $robot-arm-control 结合当前画面完成指定的观察或运动任务”。再说明结构化数据流或直接多模态看图的选择及各自输入输出；非Skill宿主可按文档调用同一工具接口，发现与加载方式以实际Agent支持为准。
4. 安装环境。Python、FFmpeg、Node.js和按工作流选择的requirements；单列MicroPython安装方式。依赖按共用采集、算法处理、多模态图片交付、历史PoC分别列出；补充Skill所需终端长连接、图片查看和现有服务访问条件，Skill本身不重复实现驱动或算法。直接看图无需安装全部算法依赖；算法处理无需多模态模型API；两套历史设备依赖仅供历史示例选择安装。
5. 设备连接与配置。USB/串口设备识别、供电、相机路径、旋转和映射，端口为现场配置项。
6. 最小复现。验证共享相机、独立监控、观察臂串口通信、仿真和录像导出；双绿臂和桌面搭子实机复现分别列在历史PoC说明，不作为主线安装与验收前置。增加同一录制帧的双路径使用说明，区分现有入口与拟实现接口。标注命令是否可能触发实体动作。增加Skill复现顺序：只读状态/新鲜帧与仿真核对在前，实体移动及夹爪操作依据当前任务授权与设备状态执行；列明应保存的指令、回复、等待依据和结果证据。
7. 模型与打印。分别列出自研夹爪及相机支架、原开源机械臂整机及分件：给出用途、当前及拟归档路径、固定版本、原生CAD/STEP/STL入口、打印方式、版本manifest及试装资料链接。开源模型说明上游作者、许可证和本地修改记录。
8. 测试与结果。给出主线检查命令、已验证能力和未完成项；另设历史PoC示例栏目，分别链接双绿臂和桌面搭子演示、视频、代码版本、日志及专用CV结果。说明通用库提取验证、数据契约及图片交付检查，与历史实机结果分开登记。
9. 目录与维护。解释Skill操作编排、perception纯算法、observation路径编排、设备适配、实验脚本及控制层的边界；给出帧/观察结果字段、JSONL消费方式、图片实际交付方式、兼容入口及日志归档规则。
10. 来源、许可证与任务文档。模型许可逐来源登记，当前任务与历史实验均可追溯。

README命令示例先列现有可用入口，方案获批并迁移完成后才换为新入口。拟推荐`python -m host_control.session`、`python -m camera.server`、`python -m recording.recorder`、`python -m visual_observation`；现有cv_pipeline入口用于迁移兼容。perception和observation的接口及命令均标为拟实现，待代码落地后补可执行示例，避免把规划接口写成现成功能。

## 八、实施顺序、验证与预计投入

1. 本轮方案已提交审阅。双绿臂与桌面搭子历史归档、通用算法库及双观察路径方向已由用户确认；本次只更新方案，后续代码实施仍待整体目录与接口方案确认。
2. 获批后建立独立实施分支，保存迁移前文件清单与Git基线，先归档选定自研模型、固定版本开源机械臂模型及硬件资料，完成来源和许可登记，校验69个已收上游文件及manifest并确认仿真引用。
3. 再迁移共用PC模块及示例，将两套设备专用实现与说明归入历史PoC，保留兼容转发；先按函数分离算法、设备参数及实验编排，再提取perception并接入observation两条路径；共用模块独立于历史设备依赖，同步package.json、同步脚本、启动器、导入与文档。
4. 最后处理机械资源及仿真URL映射，更新README、AGENTS.md及robot-arm-control Skill正文和调用元数据，做全量引用检查与回归验证；Skill迁移与路径变更在同一实施提交完成。

更名及定位修订方案于2026-11-20本次提交；收到名称及引用方案确认后，预计1个工作日完成仓库更名、引用更新与兼容核对，原目录迁移及模型归档仍按1至2个工作日参考估算分阶段实施。通用库提取及双路径接入另估投入；本轮不增加硬件开发、第二套实装或两套画面/运动证据任务。

迁移核对增加：逐项核对Skill中引用的文件、CLI参数、服务URL、仿真与日志路径，验证显式调用元数据和只读流程；未实现双路径接口仅标规划，禁止写成已能执行的Skill命令。在未安装两套历史设备依赖、未配置桌面搭子网络接口时验证主线安装、纯观察监控、串口CLI帮助、相机与录像入口；用同一离线帧验证纯算法输入输出、字段/单位/坐标系、JSONL消费、图片实际可见性及帧编号关联；验证直接看图不加载算法、结构化路径不调用多模态模型；历史PoC按可选依赖单独回归，缺设备时只核对离线回放与命令帮助，不声称实机复验。保留历史恢复的PAUSED/LOCKOUT及人工授权条件。验收包括Python现有测试、node simulator/check_math.mjs、node simulator/check_gripper.mjs、安装分发一致性、旧新入口帮助/离线启动、静态模型资源、日志回放和相机只读订阅检查。涉及实体动作的复测另依据当时状态和授权执行，已有安全门禁与数值范围随迁移核对。

## 九、原审批事项与后续边界

- 请确认推荐仓库名ai-agent-embedded-debugging-kit、旧新URL、README整套工程定位，以及更名与目录迁移分阶段实施；v1.7子分类继续作为基础。
- 是否同意保留旧CLI转发和MicroPython根目录分发副本，迁移后以新包路径作为维护入口。
- 原生模型采用按版本目录及manifest归档，当前试装资料基准已由用户确认为(2)包；原开源机械臂模型也纳入本次归档范围，按固定提交版本保留整机、分件及来源许可。
- 已确认：双绿臂与桌面搭子均归入历史PoC；通用算法与设备适配分离，Agent可选结构化数据流或直接多模态看图；两套设备的外部依赖仅供历史复现。具体接口与提取范围按本方案审阅。robot-arm-control作为正式Agent操作入口保留，Skill与下层工具一起整理。
- 用户当前实际打印使用的3MF已收并打包；其他切片项目和打印参数按实际产生情况归档。

## 十、2026-11-23实际实施结果

仓库已原地更名为 https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit ，保留原历史并将实现提交d671081推送main。根README现为AI Agent Embedded Device Debugging Kit，组件状态与安装入口已落实，目录迁移对应表增加实际维护位置及实施状态。原代码/驱动旧入口兼容，独立MicroPython驱动副本保留，原模型、STEP及3MF已归档。两套安装及运动证据仍按对应任务登记，文件引用通过不扩大为实物验收。

Python 128项回归、运动学639项及夹爪检查通过。旧新Git地址、授权包清单及raw驱动下载已核对，结果见docs/reorganization-verification.md及docs/reorganization-download-checks.json。

仓库维持private；匿名raw和标准mip GitHub入口返回404，不能宣称裸mip.install可直接联网安装。旧新名称的授权下载均通过；README提供授权克隆后使用mpremote复制独立robot_arm.py的方法。通用库目前提取轴线拟合，更多算法提取、完整流式接口和其他硬件依然按实际状态标规划，没有新增硬件范围。

## 参考资料

- 整体任务 （内部来源，链接不公开）
- 试装资料 （内部来源，链接不公开）
- 当前仓库（尚未更名） https://github.com/FreakStudioCN/micropython-robot-arm
- 推荐新仓库（待确认实施） https://github.com/FreakStudioCN/ai-agent-embedded-debugging-kit
- 新版STEP提交 https://github.com/FreakStudioCN/micropython-robot-arm/commit/b02d097
- 迁移逐文件清单 repository-file-migration.csv

试装文档9.3节目前仍保留此前待验证表述，用户后续已确认相机位置及相关适配无问题。本方案以最新用户确认登记状态；后续更新正式记录时应同步该状态，保留历史版本。

本版参考附件ZIP包含7项：repository-organization-proposal.md、repository-file-migration.csv、用户指定的“机械臂夹爪及相机支架 (2).zip”、当前打印“观察机械臂夹爪固定摄像头.3mf”、model-manifest.json、native-reference-check.json及repository-rename-references.csv。原开源模型的69个文件继续由仓库及其固定版本manifest索引。

## 版本记录

| 版本号 | 修订日期 | 修改人 | 修改内容 |
| --- | --- | --- | --- |
| v1.0 | 2026-11-20 | 赵岩松 | 提交待确认的目录、逐文件迁移、README及模型资料清点方案。 |
| v1.1 | 2026-11-20 | 赵岩松 | 按用户确认将STEP作为打印输入，调整资料清单、目录说明及进度条件。 |
| v1.2 | 2026-11-20 | 赵岩松 | 明确自研与原开源机械臂模型共同入库，补充开源模型目录、来源许可、迁移对应及README入口。 |
| v1.3 | 2026-11-20 | 赵岩松 | 按用户确认将绿色机械臂归入历史PoC示例，同步目录、迁移表、README结构及主线可选依赖边界。 |
| v1.4 | 2026-11-20 | 赵岩松 | 桌面搭子归入历史PoC；规划设备无关算法库、结构化数据流与直接多模态图片路径，同步迁移表及README方案，仅更新文档。 |
| v1.5 | 2026-11-20 | 赵岩松 | 将robot-arm-control Skill纳入正式软件交付，补充Agent操作流程、双观察路径衔接及README/迁移核对；仅更新方案。 |
| v1.6 | 2026-11-20 | 赵岩松 | 接收并打包用户当前打印3MF，与选定原生CAD及STEP共同提供；补充来源散列、迁移映射及资料清单。 |
| v1.7 | 2026-11-20 | 赵岩松 | 完成16个原生CAD文件及装配依赖校验，记录Toolbox复现设置和只读检查结果；按用户确认关闭3MF对应关系待核对项。 |
| v1.8 | 2026-11-20 | 赵岩松 | 按总任务调整为完整调试套装定位，推荐新仓库名并补旧新URL、组件关系、引用清单及更名兼容方案；保留v1.7子分类，尚未更名迁移。 |
| v1.9 | 2026-11-20 | 赵岩松 | 补充本次新装一套实际USB摄像头、夹爪及走线的5张实拍，关联手机/相机运动录像，记录测试范围与用户现场检查结果。 |
| v2.0 | 2026-11-23 | 赵岩松 | 按已批准v1.8实施仓库更名与目录重组，补实际提交、兼容核验及私有仓库下载限制。 |
