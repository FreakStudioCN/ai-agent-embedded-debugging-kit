"""Offline synthetic truth, historical snapshot and channel-scene checks."""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import argparse
import importlib.util
import json
import sys
import cv2
import numpy as np

ROOT=_WORKSPACE_ROOT
sys.path.insert(0,str(ROOT))
from cv_pipeline.contour_axis_2d import ContourAxisDetector,draw_axis_overlay,axial_difference,VERSION
from cv_pipeline.tools.evaluate_contour_axis import evaluate_clip,digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    state=ROOT/'.runtime/phase_r_state.json';state_hash=digest(state)
    folder=out/'synthetic_and_occlusion';folder.mkdir(exist_ok=False)
    spec=importlib.util.spec_from_file_location('axis_fixtures',ROOT/'tests/test_contour_axis_2d.py')
    fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
    detector=ContourAxisDetector();records=[];errors=[];false_accept=0;negative_count=0
    cases=[('static',{},[-90,-90]),('distal_plus4',dict(distal_rotation=4),[-90,-94]),
           ('distal_minus3',dict(distal_rotation=-3),[-90,-87]),('shoulder_plus3',dict(shoulder_rotation=3),[-90,-93]),
           ('missing_left',dict(hide_left=True),[None,-90]),('right_occluded',dict(occlude=True),[-90,None]),
           ('green_pcb_wire',dict(pcb=True),[-90,-90])]
    for name,options,truth in cases:
        image=fixtures.scene(**options);rows=detector.detect(image)
        for row,target in zip(rows,truth):
            error=abs(axial_difference(row['axis_angle_deg'],target)) if target is not None and row['measurement_valid'] else None
            if error is not None:errors.append(error)
            if target is None:negative_count+=1;false_accept+=int(row['measurement_valid'])
            records.append(dict(case=name,truth_axis_deg=target,error_deg=error,**row))
        cv2.imwrite(str(folder/(name+'.jpg')),draw_axis_overlay(image,rows))
    # Known failure mode: a short wide ledge must not become a vertical link.
    from cv_pipeline.contour_axis_2d import entity_axis_evidence
    yy,xx=np.mgrid[0:31,0:179]
    ledge=entity_axis_evidence(np.column_stack((xx.ravel(),yy.ravel())),-81)
    (folder/'cases.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records),encoding='utf-8')
    summary=dict(cv_version=VERSION,synthetic_accepted_angle_samples=len(errors),
        synthetic_max_angular_error_deg=max(errors) if errors else None,
        synthetic_mean_angular_error_deg=float(np.mean(errors)) if errors else None,
        synthetic_false_acceptances=false_accept,synthetic_negative_arm_cases=negative_count,
        short_wide_ledge=ledge,limitation='Ideal geometric fixtures; no physical PWM correspondence or servo repeatability claim')
    (folder/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    snaps=out/'historical_snapshots';snaps.mkdir(exist_ok=False);snap_records=[]
    for name in ('s317v3','s307v3','s297v3','s307v3-final','e317v3','e337v3','e317v3-back','e307v3','e297v3'):
        source=ROOT/'.runtime'/('cal-'+name+'-wrist.jpg')
        image=cv2.imread(str(source))
        if image is None:continue
        image=cv2.rotate(image,cv2.ROTATE_180);rows=detector.detect(image)
        snap_records.append(dict(source=str(source),source_sha256=digest(source),poses=rows,
            limitation='Historical 300ms bounded pulse followed by FULL OFF; gravity/release confounded, not controlled backlash trial'))
        cv2.imwrite(str(snaps/(name+'.jpg')),draw_axis_overlay(image,rows))
    (snaps/'results.json').write_text(json.dumps(snap_records,indent=2),encoding='utf-8')
    jobs=[dict(id='historical_CH10_scene',start=218.,end=240.),dict(id='historical_CH9_scene',start=256.,end=299.)]
    for job in jobs:job.update(source='.runtime/second-cal-wrist.mkv',source_run_id='historical-second-cal',output=str(out),rotation=180,stride=5)
    with ProcessPoolExecutor(max_workers=2) as pool:results=list(pool.map(evaluate_clip,jobs))
    for result in results:
        result.update(timing_trustworthy=False,physical_static_noise_qualified=False,
            physical_time_drift_deg_per_s=None,limitation='Image-matched channel scenes only; exact command/video clock unknown. Pulses release output; no physical response qualification.')
        (out/result['id']/'metrics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    validation=json.loads((out/'validation.json').read_text(encoding='utf-8'))
    validation.update(historical_channel_scenes=results,additional_checks_paused_state_unchanged=digest(state)==state_hash)
    (out/'validation.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')
    print(json.dumps(dict(synthetic=summary,historical_frames=sum(r['analyzed_frames'] for r in results),state_unchanged=digest(state)==state_hash)),flush=True)


if __name__=='__main__':main()
