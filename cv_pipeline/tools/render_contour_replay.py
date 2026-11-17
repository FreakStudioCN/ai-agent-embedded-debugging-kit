"""Render stored current-frame JSONL decisions, without re-detecting or holding angles."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cv_pipeline.contour_axis_2d import draw_axis_overlay


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();records=[]
    for file in sorted(out.glob('*/pose_stream.jsonl')):
        rows=[json.loads(line) for line in file.read_text(encoding='utf-8').splitlines()]
        if not rows:continue
        groups={}
        for row in rows:groups.setdefault(round(row['source_pts_s'],5),[]).append(row)
        folder=file.parent;metrics=json.loads((folder/'metrics.json').read_text(encoding='utf-8'))
        cap=cv2.VideoCapture(metrics['source']);cap.set(cv2.CAP_PROP_POS_MSEC,metrics['source_start_s']*1000)
        writer=None;rendered=0
        try:
            while True:
                ok,image=cap.read()
                if not ok:break
                pts=cap.get(cv2.CAP_PROP_POS_MSEC)/1000
                if pts>metrics['source_end_s']:break
                current=groups.get(round(pts,5))
                if current is None:continue
                if metrics['rotation']:image=cv2.rotate(image,cv2.ROTATE_180)
                overlay=draw_axis_overlay(image,current,pts)
                if writer is None:
                    writer=cv2.VideoWriter(str(folder/'roi_overlay.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),metrics['source_fps']/metrics['frame_stride'],(image.shape[1],image.shape[0]))
                    if not writer.isOpened():raise RuntimeError('overlay writer unavailable')
                writer.write(overlay);rendered+=1
                if rendered in (1,50,150):cv2.imwrite(str(folder/('overlay_frame_%05d.jpg'%rendered)),overlay)
        finally:
            cap.release()
            if writer:writer.release()
        if rendered!=len(groups):raise RuntimeError(f'frame mismatch {folder}: {rendered}/{len(groups)}')
        records.append(dict(clip=folder.name,rendered_frames=rendered,decisions_changed=False))
    record=dict(renderer_source_sha256=hashlib.sha256((ROOT/'cv_pipeline/contour_axis_2d.py').read_bytes()).hexdigest(),
        reason='Added per-candidate link identity, axes and rejection reasons; stored detection decisions remain unchanged',clips=records)
    (out/'overlay_render_manifest.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record),flush=True)


if __name__=='__main__':main()
