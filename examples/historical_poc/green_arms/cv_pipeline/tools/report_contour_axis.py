"""Assemble offline evidence and main-CV decision; never accesses hardware."""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import cv2
import numpy as np
ROOT=_WORKSPACE_ROOT;sys.path.insert(0,str(ROOT))
from cv_pipeline.contour_axis_2d import VERSION,AxisConfig


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def verify(path):
    result=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],capture_output=True,text=True)
    return dict(file=str(path),decode_ok=result.returncode==0,return_code=result.returncode,errors=result.stderr.strip())


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--current',type=Path,required=True);parser.add_argument('--full',type=Path,required=True);args=parser.parse_args()
    out=args.current.resolve();full=args.full.resolve();current=read(out/'validation.json');previous=read(full/'validation.json')
    videos=sorted(out.glob('*/roi_overlay.mp4'))+sorted(full.glob('*/roi_overlay.mp4'))
    with ThreadPoolExecutor(max_workers=3) as pool:verification=list(pool.map(verify,videos))
    (out/'video_verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    state=ROOT/'.runtime/phase_r_state.json';state_hash=hashlib.sha256(state.read_bytes()).hexdigest()
    manifest=read(out/'dataset_manifest.json');state_unchanged=state_hash==manifest['current_state_sha256']
    B=read(out/'B_CH9_actual/metrics.json');long=read(out/'long_static/metrics.json');synth=read(out/'synthetic_and_occlusion/summary.json')
    # Compare revisions only on the SAME sampled source frames, not unequal sets.
    matched={}
    for clip in ('long_static','B_CH9_actual'):
        a=[json.loads(x) for x in (full/clip/'pose_stream.jsonl').read_text(encoding='utf-8').splitlines()]
        b=[json.loads(x) for x in (out/clip/'pose_stream.jsonl').read_text(encoding='utf-8').splitlines()]
        index={(round(r['source_pts_s'],3),r['arm_id']):r for r in a};pairs=[(index[(round(r['source_pts_s'],3),r['arm_id'])],r) for r in b if (round(r['source_pts_s'],3),r['arm_id']) in index]
        matched[clip]={}
        for arm in ('green_1','green_2'):
            subset=[pair for pair in pairs if pair[1]['arm_id']==arm]
            matched[clip][arm]=dict(matched_frames=len(subset),v1_valid=sum(p[0]['measurement_valid'] for p in subset),current_valid=sum(p[1]['measurement_valid'] for p in subset))
    (out/'matched_iteration_comparison.json').write_text(json.dumps(matched,indent=2),encoding='utf-8')
    decision=dict(main_cv_eligible=False,main_cv_switched=False,mode='OFFLINE_EVALUATION_ONLY',cv_version=VERSION,
        parameter_version=AxisConfig().parameter_version,root_state=read(state)['state'],root_state_unchanged=state_unchanged,
        motion_commands_this_task=0,hardware_safety_limits_modified=False,
        reasons=['Actual ROI acceptance is far below0.85','CH9 response lacks qualified before/after windows',
                 'No reliable control-versus-target causal contrast','CH10 historical pulse data do not establish controlled response',
                 'No qualified independent servo-return repeatability or real per-frame angular truth'],
        real_CH9_response_qualified=False,real_CH10_response_qualified=False,true_wrong_tracking_rate=None,
        synthetic=synth,video_verification_passed=all(v['decode_ok'] for v in verification),
        mixed_old_new_E0_E1_comparisons=0,E0=None,E1=None,physical_backlash_improvement=None)
    (out/'main_cv_decision.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    new=B['summaries']['contour_axis_2d'];legacy=B['summaries']['legacy_fused_pose'];table=[]
    for alg,arms in [('旧 fused_pose 回放',legacy),('新 contour v3 抽样',new)]:
        for arm,s in arms.items():
            before=s.get('before_motion',{});after=s.get('after_motion',{})
            def f(value):return '—' if value is None else f'{value:.4f}'
            table.append(f"| {alg} | {arm} | {s['valid_frames']}/{s['frames']} | {f(before.get('axis_std_deg'))} | {f(after.get('axis_std_deg'))} | {f(s.get('diagnostic_motion_delta_deg'))} |")
    control=new['green_1'].get('diagnostic_motion_delta_deg');target=new['green_2'].get('diagnostic_motion_delta_deg')
    total_full=sum(r['analyzed_frames'] for r in previous['results']);total_current=sum(r['analyzed_frames'] for r in current['results']);historical=current.get('historical_channel_scenes',[])
    report=f'''# 轮廓主轴识别离线验证：尚不切换主 CV

实现了纯 OpenCV 的每帧独立检测，实机保持 **PAUSED**。本任务运动指令 **0**，根恢复状态文件哈希未改变：{state_unchanged}。未解除 S0/S1，没有调用 COM3/COM8，也没有改变硬件安全边界。

## 方法与版本

HSV/Lab 分割 → 连通域及可见底座/分叉身份 → 当前帧轮廓分支 → 宽度稳定及近似平行的局部边缘对 → 连杆位置/截面/遮挡筛选 → 中心线 PCA 与 Huber fitLine → 图像轴角。PCA/fitLine 一致性仅是几何指标；多个候选方向冲突会拒绝。v2叠加图暴露短宽台阶误接受，v3新增实际前景像素长宽比、特征值比及前景PCA轴检查；短宽台阶即使中心线竖直也拒绝。实体检查可能保守拒绝被截短的真连杆，这种漏检如实保留。

没有 LK 累计、PnP、固定肩点、连杆长度或 PWM 反推。失效角度为 null，不保留上一帧。distal/proximal 是可见结构候选，不等于已验证的 CH9/CH10 物理轴。

v1 在两段素材上全帧分析 **{total_full} 帧**；v3 合并重复边缘，并要求真实前景像素沿所声明主轴延展，在同样素材中每5帧取1帧，共 **{total_current} 帧**。matched_iteration_comparison.json 给出相同源帧上的版本对照，避免把不同采样率当成改善。

## 真实 CH9 录像结果

源 run_id：experiment_20261117T092542_cd2ffd8d，真实 CH9 307→302，其他关节保持原 counts，观察臂固定 B-small。以下变化量仅为诊断，前后窗口均未形成新方法的合格测量；不是 E0/E1。

| 算法 | 机械臂 | 合格帧/总帧 | 运动前 sigma° | 运动后 sigma° | 前后中位数差° |
|---|---|---:|---:|---:|---:|
'''+'\n'.join(table)+f'''

新方法目标臂诊断变化 **{f(target)}°**，对照臂变化 **{f(control)}°**（—表示不可计算）。本版没有合格的运动前后角度窗口，不能判定 CH9 响应。两臂总体合格率为 {new['green_1']['valid_ratio']:.1%}/{new['green_2']['valid_ratio']:.1%}，远低于0.85。不能只选少数低 sigma 帧宣布成功。

旧方案输出 FK/PnP 约束下的近似肘角；新方案输出可见刚性段轴角，二者观测量不同。表中仅比较各自质量与响应诊断，禁止据此混算 E0/E1 或宣称真实角度精度提高。

## 长时漂移、重复性与错误率

长静止片段来自 experiment_20261117T075459_750e71b2，使用命令日志中的静止区间。v3 两臂均没有合格角度，sigma/漂移必须为 null，不能写0。其他统计见 long_static/metrics.json；少量合格帧的趋势不代表连续可靠跟踪。

2秒不重叠窗口中位数散布仅是时间稳定性，不是独立舵机回位重复性。新方法尚无合格的受控重复配对。历史 s307/e317 等重复快照有300ms脉冲后FULL OFF的混杂条件，不能用来证明本次保持力一致的回差结果。

真实录像没有逐帧连杆/角度独立真值，所以**真实错误跟踪率、真实角度精度不可确定**。不把零ID区间越界或算法自身质量门槛当成真实零错误率。合成真值集单独报告：{synth['synthetic_accepted_angle_samples']}个合格角度样本最大误差{synth['synthetic_max_angular_error_deg']:.4f}°，负例误接受{synth['synthetic_false_acceptances']}/{synth['synthetic_negative_arm_cases']}；这些理想图结果不替代实物验证。

## CH10 与更多历史素材

补充读取了 calibration-samples.jsonl、带时间的旧快照和 second-cal-wrist.mkv，并按图像匹配校对场景。额外分析 **{sum(r['analyzed_frames'] for r in historical)} 个抽样帧**。旧录像时间轴与串口时钟缺少精确映射，历史短脉冲后会释放输出，因此这些仅用于场景/遮挡/身份诊断，**CH10 受控响应仍未验证**。

## 输出

- contour_axis_2d.py：独立检测、质量、统计、版本拒绝、叠加绘制。
- 各素材目录 pose_stream.jsonl：当前角度、measurement_valid、detection_quality、geometry_quality、候选ROI与拒绝原因。
- 各目录 roi_overlay.mp4：每个被分析帧均有当前接受/拒绝ROI、身份、拟合轴及原因。v1是全帧，v3和早期通道场景是明确抽样；源录像未覆盖。
- synthetic_and_occlusion/：理想旋转、遮挡、缺臂、PCB/线缆及真实帧图像注入；不是物理故障试验。
- source_analysis_snapshot/：与分析时 source_sha256 完全一致的检测源码；source_snapshot/保存最终源码。overlay_render_manifest.json记录仅增强候选标注的重绘，JSONL决定未改变。
- dataset_manifest.json、video_verification.json：配置、源文件与解码验证。

## 切换决定

**CANDIDATE_NOT_QUALIFIED：不切换为主 CV，不用于 PWM 闭环。** 需要先使同一物理刚性段的可见轮廓足够唯一，并补足 CH9/CH10、对照臂及真实重复运动的验证。当前不请求也不执行实机运动；新旧数据继续隔离，E0/E1与回差改善均未产生。
'''
    (out/'summary.md').write_text(report,encoding='utf-8')
    # Scientific plots use only stored per-frame outputs and explicit source time.
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows=[json.loads(x) for x in (out/'B_CH9_actual/pose_stream.jsonl').read_text(encoding='utf-8').splitlines()]
    fig,axes=plt.subplots(2,2,figsize=(12,7))
    for col,arm in enumerate(('green_1','green_2')):
        data=[r for r in rows if r['arm_id']==arm];times=[r['source_pts_s'] for r in data];angles=[r['axis_angle_deg'] if r['measurement_valid'] else np.nan for r in data]
        axes[0,col].plot(times,angles,'.',markersize=4);axes[0,col].set_title(arm+' current accepted contour axes');axes[0,col].set_ylabel('Image axis (deg)')
        axes[1,col].step(times,[int(r['measurement_valid']) for r in data],where='mid');axes[1,col].set_ylabel('measurement_valid');axes[1,col].set_xlabel('Source video PTS (s)')
        for ax in axes[:,col]:ax.axvspan(143,146,color='orange',alpha=.25);ax.grid(alpha=.2)
    fig.suptitle('Real CH9 command interval shaded; gaps remain invalid, no held angle');fig.tight_layout();(out/'plots').mkdir(exist_ok=True);fig.savefig(out/'plots/actual_CH9_response_and_validity.png',dpi=160);plt.close(fig)
    images=[]
    for clip in ('long_static','B_CH9_actual'):
        for path in sorted((out/clip).glob('overlay_frame_*.jpg'))[:2]:
            image=cv2.imread(str(path));image=cv2.resize(image,(640,360));cv2.putText(image,clip+' / '+path.name,(8,347),0,.45,(255,255,255),1,cv2.LINE_AA);images.append(image)
    if len(images)>=4:cv2.imwrite(str(out/'plots/accepted_rejected_contact_sheet.jpg'),np.vstack((np.hstack(images[:2]),np.hstack(images[2:4]))))
    for f in ('cv_pipeline/contour_axis_2d.py','cv_pipeline/tools/evaluate_contour_axis.py','cv_pipeline/tools/report_contour_axis.py','cv_pipeline/tools/validate_contour_entities.py','cv_pipeline/tools/render_contour_replay.py','tests/test_contour_axis_2d.py','docs/contour-axis-2d.md'):
        target=out/'source_snapshot'/f;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/f,target)
    shutil.copyfile(ROOT/'.runtime/contour_tests_v3.log',out/'test_results.log')
    print(json.dumps(dict(report=str(out/'summary.md'),main_cv_switched=False,paused_state_unchanged=state_unchanged,verified_videos=len(videos),all_video_decode_ok=all(v['decode_ok'] for v in verification)),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
