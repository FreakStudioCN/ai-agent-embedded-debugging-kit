# 每帧独立的刚性连杆轮廓主轴检测

模块：`cv_pipeline/contour_axis_2d.py`。当前候选版本 `contour-axis-2d-v3`，模式固定为 `contour_axis_2d`。这是离线候选，尚未切换主 CV，实机继续 PAUSED。

## 实现

1. **绿色证据**：沿用 fused_pose 的绿色分割思路，使用 HSV 宽阈值与更严格的种子阈值，并用 Lab 的 a/b 通道排除低饱和/非绿色背景。形态学开运算削弱细线，轻度闭运算填小缝隙。阈值和参数哈希写入每条记录。
2. **连通域及身份**：连通域仅生成候选，不直接把整个连通域当连杆。底座位置、底座/中段宽度关系、可见夹爪分叉和固定安装区共同判断身份。左臂丢失时，右臂仍是 green_2。两个底座可分离时才允许分解跨区连通域；目标 ROI 触及未验证切分边界时拒绝。
3. **当前帧轮廓分支分离**：横截面只保留与该帧可见底座/上部位置相容的分支。位置证据用于选分支，不用于生成角度。PCB/线缆不能仅凭颜色或面积进入测量。
4. **局部刚性段候选**：搜索宽度稳定的横截面区间，以及 LSD/Hough 提出的局部近似平行边缘对。重新从当前图像采样边缘，检查绿色内部支持、连续可见比例、最大缺口、宽度变化、边缘方向及所在结构区间。v2 合并同一帧同一边缘的重复线段，并为上/下区域保留候选，避免长边淹没短连杆。
5. **实体与主轴拒绝**：v3先要求ROI内实际绿色前景沿所声明主轴延展（投影长宽比≥1.2、前景PCA特征值比≥1.8、与拟合轴差≤5°）。这用于拒绝短宽台阶，不能替代连杆身份验证。被截短的真连杆也可能拒绝，禁止用放宽门控掩盖漏检。对候选横截面中心点云作 PCA，并用 `cv2.fitLine(..., DIST_HUBER)` 拟合。检查两者差异、子段方向差异、双边几何、残差与遮挡。多个合格候选给出冲突方向时拒绝，不能通过“PCA 与 fitLine 一致”证明目标正确。
6. **统计**：输出当前图像的轴角和窗口有效率/标准差/趋势。轴角以图像 +x 为零方向，图像 +y 向下，轴朝上定向，按 180° 周期处理；变化量使用同版本基线的轴角差。它是指定可见刚性段的图像方向，不是真实关节绝对角。

没有 LK 位姿累计、PnP、固定肩点、连杆长度反解、PWM 输入或时间滤波。无效帧输出 `axis_angle_deg=null`、`delta_angle_deg=null`、`measurement_valid=false`；不会保留上一帧角度。拟合出的当前原始候选可保留为诊断字段，但不得作有效测量使用。

`distal_candidate`/`proximal_candidate` 是可见结构顺序的候选名称，不代表已证实与 CH9/CH10 对应。对应关系必须通过独立 PWM 变化及静止对照验证。

OpenCV 计算接口依据：[连通域与 fitLine 官方文档](https://docs.opencv.org/4.13.0/d3/dc0/group__imgproc__shape.html)、[PCA 官方接口](https://docs.opencv.org/4.13.0/d2/d75/namespacecv.html)。Huber 线拟合是鲁棒几何估计，不提供物理连杆身份保证。

## JSONL 与版本边界

关键字段：

| 字段 | 含义 |
|---|---|
| measurement_mode | 固定 contour_axis_2d |
| cv_version / parameter_version | 算法版本及配置哈希 |
| camera_pose_id / calibration_version | 机位与参考版本；离线数据标记 analysis-only |
| detection_quality | 当前帧颜色、安装位置和形状支持分数，非概率 |
| geometry_quality | 当前帧候选边缘/截面/主轴几何分数，非概率 |
| object_detected / identity_valid | 物体及安装身份是否可辨，与角度有效性分开 |
| measurement_valid | 当前测量最终是否可用；消费者必须检查此字段 |
| axis_angle_deg / delta_angle_deg | 有效当前轴角及合格基线下变化量；无效为 null |
| raw_axis_angle_deg | 当前候选诊断值，不能当作有效值 |
| roi_candidates / invalid_reason | 接受/拒绝候选、身份、边缘及拒绝原因 |
| pnp_rms_px | null，明确不适用；不得当作零误差 |
| target_joint_response_verified | 当前离线候选尚未通过实机对应性验收 |

录像时间由 `source_pts_s`、`time_domain=source_video_pts` 明确表示；处理时刻另有 UTC/单调时钟。不能假设旧录像容器 FPS 等于原采集速度，缺少采集时钟的片段不用于真实时间漂移或精确命令对齐。

`assert_axis_comparable` 拒绝混合模式、参数、参考版本或机位。旧 FK/PnP 肘角和新连杆图像轴角是不同观测量；旧/新噪声比较只属于诊断，禁止混算 E0/E1、H0/H1 或宣称精度改善。

## 验证要求与目前结论

必须同时检查：静止噪声、长时漂移、运动响应、对照臂响应、有效/丢失率、遮挡、身份、ROI 是否对应目标实体，以及真实重复测量。只有静止 sigma 小不能通过。

本轮包含 v1 全帧回放、v2及v3 抽样复核、真实 CH9 307→302 录像、早期 CH9/CH10 快照与对应场景、理想几何旋转及遮挡/绿色干扰测试。历史 300ms 短脉冲后释放的素材不能当成保持力一致的受控回差试验。旧照片/录像若缺少精确时间对齐，会保留不确定性。

v3在最近静止与CH9录像的193个抽样帧中两臂均无合格角度。此前v2出现短宽台阶的误接受；修正后的门控更保守。目前真实录像中有效率不足，存在方向冲突和 ROI 语义不稳定，CH9 响应尚未通过，CH10 也未验证。因此不切换主 CV。真实错误跟踪率与真实角度精度缺少逐帧独立真值，报告为不可确定；合成图的已知角度误差和误接受率单独统计。

## 复现与可视化

```powershell
python -B -m unittest discover -s tests -v
node simulator/check_math.mjs
node simulator/check_gripper.mjs
python -B -m cv_pipeline.tools.evaluate_contour_axis --workers 2
# 快速检查：明确每5个解码帧分析一个，不能伪称全帧结果
python -B -m cv_pipeline.tools.evaluate_contour_axis --workers 2 --quick
# 在新建的输出目录上补充合成真值、CH9/CH10历史场景与快照
python -B -m cv_pipeline.tools.validate_contour_entities --output .runtime/<new_run_id>
```

每个分析帧都输出两臂 JSONL，并写入 `roi_overlay.mp4`：绿框为接受的当前 ROI，红色为拒绝及原因，黄色为备选；缺失帧显示 angle=null。视频叠加保留源 PTS。源录像不覆盖，旧算法不破坏。任何未来实机切换仍需通过 S0/S1 与 Phase R，当前模块没有运动接口。
