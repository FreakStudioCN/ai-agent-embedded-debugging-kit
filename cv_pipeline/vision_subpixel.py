"""Small isolated CV fork: retain upstream geometry/gates, refine blob centers.

Only integer blob-peak localization is replaced by a bounded3-point parabolic
subpixel estimate. Original upstream module and controller safety are unchanged.
Each compiled copy is source-hashed and fails if its expected edit point moves.
"""
import hashlib
import importlib
import inspect
import types
import numpy as np


def subpixel_peak(response,x,y):
    x=int(x);y=int(y)
    if not (1<=x<response.shape[1]-1 and 1<=y<response.shape[0]-1):return float(x),float(y)
    center=float(response[y,x])
    def offset(a,b):
        denominator=float(a)-2*center+float(b)
        if denominator>=-1e-5:return 0.
        value=.5*(float(a)-float(b))/denominator
        return value if abs(value)<=.75 else 0.
    return x+offset(response[y,x-1],response[y,x+1]),y+offset(response[y-1,x],response[y+1,x])


def tracker_class():
    original=importlib.import_module('mr_robot_desktop.fused_pose')
    source=inspect.getsource(original)
    needle='observed[index] = x+ix-6,y+iy-6'
    if source.count(needle)!=1:raise RuntimeError('Upstream CV recenter edit point changed; review required')
    edited=source.replace(needle,'observed[index] = _subpixel_peak(response,x+ix-6,y+iy-6)')
    module=types.ModuleType('mr_robot_desktop._fused_pose_subpixel_v11')
    module.__package__='mr_robot_desktop';module.__dict__['_subpixel_peak']=subpixel_peak
    exec(compile(edited,original.__file__+'::subpixel_v11','exec'),module.__dict__)
    detector=module.blob_candidates
    def candidates(frame,arm):
        points,strengths,mask=detector(frame,arm)
        gray=module.cv2.cvtColor(frame,module.cv2.COLOR_BGR2GRAY).astype(np.float32)
        response=module.cv2.GaussianBlur(gray,(0,0),4)-module.cv2.GaussianBlur(gray,(0,0),1)
        refined=np.array([subpixel_peak(response,*p) for p in points],float).reshape(-1,2)
        return refined,strengths,mask
    module.blob_candidates=candidates
    module.FusedTracker.upstream_source_sha256=hashlib.sha256(source.encode()).hexdigest()
    module.FusedTracker.measurement_version='cv-subpixel-v11'
    return module.FusedTracker
