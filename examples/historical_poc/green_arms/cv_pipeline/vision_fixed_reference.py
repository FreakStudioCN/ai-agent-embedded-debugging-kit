"""Fixed-keyframe LK with bounded reference selection, no command feedback.

Eight initial stationary frames compete on the worst-arm *original* Q; the
selected image and its four observed feature coordinates remain fixed for the
whole batch. Every new frame tracks directly from that image, forward/back
checked by the upstream gates. Never reanchors on a green-arm command or loss.
New observer view/reset requires a new validated calibration version.
"""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import hashlib
import importlib
import inspect
import types


def tracker_class():
    original=importlib.import_module('mr_robot_desktop.fused_pose');source=inspect.getsource(original)
    edits={
        'features=observed.astype(np.float32),':'features=observed.astype(np.float32), anchor_features=observed.astype(np.float32).copy(), anchor_gray=gray.copy(),',
        "points = track['features'].reshape(-1,1,2)":"points = track['anchor_features'].reshape(-1,1,2)",
        'cv2.calcOpticalFlowPyrLK(self.previous_gray,gray,points':"cv2.calcOpticalFlowPyrLK(track['anchor_gray'],gray,points",
        'cv2.calcOpticalFlowPyrLK(gray,self.previous_gray,moved':"cv2.calcOpticalFlowPyrLK(gray,track['anchor_gray'],moved",
        'observed[index] = x+ix-6,y+iy-6':'observed[index] = point',
    }
    for old,new in edits.items():
        if source.count(old)!=1:raise RuntimeError('Upstream fixed-reference edit point changed; review required: '+old)
        source=source.replace(old,new)
    module=types.ModuleType('mr_robot_desktop._fixed_reference_v11');module.__package__='mr_robot_desktop'
    exec(compile(source,original.__file__+'::fixed_reference_v11','exec'),module.__dict__)
    base=module.FusedTracker
    digest=hashlib.sha256(inspect.getsource(original).encode()).hexdigest()
    class FixedReferenceTracker:
        measurement_version='cv-fixed-reference-lk-v11'
        upstream_source_sha256=digest
        INITIAL_FRAMES=8
        def __init__(self):self.reset()
        def reset(self):self.seen=0;self.best=None;self.score=-1.;self.reference_timestamp=None
        def update(self,frame,timestamp,counts):
            poses=self.best.update(frame,timestamp,counts) if self.best else []
            if self.seen<self.INITIAL_FRAMES:
                candidate=base();candidate_poses=candidate.update(frame,timestamp,counts)
                valid=[p for p in candidate_poses if p['status']=='visual_constrained' and p['visible_plate_features']==4]
                score=min(p['quality_score'] for p in valid) if len(valid)==2 else -1.
                if score>self.score:self.best=candidate;poses=candidate_poses;self.score=score;self.reference_timestamp=timestamp
                self.seen+=1
            for p in poses:p.update(reference_timestamp=self.reference_timestamp,reference_selection_frames=self.seen,
                reference_frozen=self.seen>=self.INITIAL_FRAMES,tracking_mode='fixed-keyframe LK; no green-command reanchor')
            return poses
    return FixedReferenceTracker
