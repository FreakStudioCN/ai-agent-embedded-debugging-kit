"""Image registration of rigid gripper plates; no FK or servo-count geometry.

Image-only four-hole topology initializes a frozen plate ROI. Reference-to-current
features, RANSAC homography and masked ECC provide independent image evidence.
Plate orientation uses measured corners and approximate existing intrinsics;
relative rotations are local single-joint proxies, never absolute joint angles.
No temporal pose filter, incremental optical-flow chain, or command feedback.
"""
from itertools import combinations
import math
import cv2
import numpy as np


VERSION='cv-plate-homography-ecc-v1'


def camera_matrix(shape,focal=1200.):
    h,w=shape[:2]
    return np.array([[focal,0,w/2],[0,focal,h/2],[0,0,1.]],float)


def plate_poses(points,camera,object_points):
    solved=cv2.solvePnPGeneric(object_points,np.asarray(points,float),camera,None,flags=cv2.SOLVEPNP_IPPE)
    result=[]
    if not solved[0]:return result
    for rv,tv in zip(solved[1],solved[2]):
        if tv[2,0]<=0:continue
        pixels=cv2.projectPoints(object_points,rv,tv,camera,None)[0].reshape(-1,2)
        rms=float(np.sqrt(np.mean(np.sum((pixels-points)**2,axis=1))))
        result.append(dict(rotation=cv2.Rodrigues(rv)[0],translation=tv.ravel(),rms_px=rms))
    return result


def detect_plate(frame,arm,camera):
    # Reuse only the image blob detector and CAD hole pattern, never initialize_plate/FK.
    from mr_robot_desktop.fused_pose import blob_candidates
    from mr_robot_desktop.vision import PLATE_HOLES
    points,strengths,_=blob_candidates(frame,arm)
    x,y,width,height=arm['box_xywh'];pairs=[];best=None
    for i,j in combinations(range(len(points)),2):
        a,b=points[i],points[j]
        if a[0]>b[0]:i,j=j,i;a,b=b,a
        delta=b-a;distance=float(np.linalg.norm(delta))
        if width*.08<distance<width*.85 and abs(delta[1])<distance*.5:
            pairs.append((i,j,distance,(a+b)/2,math.atan2(delta[1],delta[0])))
    for top in pairs:
        if top[2]>width*.30:continue
        for bottom in pairs:
            ids=[top[0],top[1],bottom[0],bottom[1]]
            if len(set(ids))!=4:continue
            gap=bottom[3]-top[3]
            if not (1.45<bottom[2]/top[2]<2.6 and .3*top[2]<gap[1]<1.8*top[2] and abs(gap[0])<top[2]*.65):continue
            if abs(top[4]-bottom[4])>.25:continue
            observed=points[ids];poses=plate_poses(observed,camera,PLATE_HOLES)
            if not poses:continue
            pose=min(poses,key=lambda p:p['rms_px'])
            if pose['rms_px']>5:continue
            score=pose['rms_px']-.001*float(np.mean(strengths[ids]))
            if best is None or score<best['score']:best=dict(points=observed,pose=pose,score=score)
    if best is None:raise ValueError('No unambiguous four-hole topology on plate')
    return best


class PlateReference:
    MIN_FEATURES=12
    MIN_INLIER_RATIO=.85
    def __init__(self,frame,points,arm_id,camera,object_points,reference_time):
        self.arm_id=arm_id;self.camera=camera;self.object_points=object_points;self.reference_time=reference_time
        self.points_global=np.asarray(points,float);h,w=frame.shape[:2]
        low=np.floor(self.points_global.min(axis=0)-32).astype(int);high=np.ceil(self.points_global.max(axis=0)+32).astype(int)
        self.x=max(0,int(low[0]));self.y=max(0,int(low[1]));self.w=min(w,int(high[0]))-self.x;self.h=min(h,int(high[1]))-self.y
        self.offset=np.array([self.x,self.y],float);self.points=self.points_global-self.offset
        self.gray=self.crop(frame);self.mask=np.zeros_like(self.gray)
        hull=cv2.convexHull(self.points.astype(np.float32)).astype(np.int32)
        cv2.fillConvexPoly(self.mask,hull,255);self.mask=cv2.dilate(self.mask,np.ones((17,17),np.uint8))
        self.features=cv2.goodFeaturesToTrack(self.gray,160,.01,3,mask=self.mask)
        if self.features is None or len(self.features)<self.MIN_FEATURES:raise ValueError('Insufficient plate texture')
        poses=plate_poses(self.points_global,self.camera,self.object_points)
        if not poses:raise ValueError('No plate reference pose')
        self.reference_pose=min(poses,key=lambda p:p['rms_px']);self.previous_rotation=self.reference_pose['rotation']
        self.reference_axis=self.points_global[2:].mean(axis=0)-self.points_global[:2].mean(axis=0)
        self.ref_angle=math.degrees(math.atan2(self.reference_axis[1],self.reference_axis[0]))

    def crop(self,frame):
        return cv2.cvtColor(frame[self.y:self.y+self.h,self.x:self.x+self.w],cv2.COLOR_BGR2GRAY)

    @staticmethod
    def distribution(points,mask):
        p=np.asarray(points).reshape(-1,2);ys,xs=np.nonzero(mask)
        x0,x1=xs.min(),xs.max();y0,y1=ys.min(),ys.max()
        cells={(min(1,max(0,int(2*(x-x0)/max(1,x1-x0)))),min(1,max(0,int(2*(y-y0)/max(1,y1-y0))))) for x,y in p}
        hull=cv2.contourArea(cv2.convexHull(p.astype(np.float32))) if len(p)>=3 else 0.
        return len(cells),float(hull/max(1,np.count_nonzero(mask)))

    def measure(self,frame):
        current=self.crop(frame)
        moved,forward,_=cv2.calcOpticalFlowPyrLK(self.gray,current,self.features,None,winSize=(21,21),maxLevel=3)
        if moved is None:raise ValueError('Plate LK failed')
        back,backward,_=cv2.calcOpticalFlowPyrLK(current,self.gray,moved,None,winSize=(21,21),maxLevel=3)
        if back is None:raise ValueError('Plate reverse LK failed')
        errors=np.linalg.norm((back-self.features).reshape(-1,2),axis=1)
        good=forward.ravel().astype(bool)&backward.ravel().astype(bool)&(errors<.75)
        a=self.features.reshape(-1,2)[good];b=moved.reshape(-1,2)[good]
        if len(a)<self.MIN_FEATURES:raise ValueError('Too few cycle-consistent plate features')
        homography,inliers=cv2.findHomography(a,b,cv2.RANSAC,1.5,maxIters=1000,confidence=.995)
        if homography is None:raise ValueError('Plate homography failed')
        inside=inliers.ravel().astype(bool);ratio=float(inside.mean());cells,hull=self.distribution(a[inside],self.mask)
        if inside.sum()<self.MIN_FEATURES or ratio<self.MIN_INLIER_RATIO or cells<3 or hull<.15:raise ValueError('Plate correspondences lack spatial support')
        mask_current=cv2.warpPerspective(self.mask,homography,(self.w,self.h),flags=cv2.INTER_NEAREST)
        try:
            score,refined=cv2.findTransformECCWithMask(self.gray,current,self.mask,mask_current,homography.astype(np.float32),
                cv2.MOTION_HOMOGRAPHY,(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,60,1e-5),3)
        except cv2.error as exc:raise ValueError('ECC did not converge') from exc
        projected=cv2.perspectiveTransform(a[inside].reshape(-1,1,2),refined).reshape(-1,2)
        residual=float(np.median(np.linalg.norm(projected-b[inside],axis=1)))
        if residual>1.5:raise ValueError('ECC and feature homographies contradict')
        warped=cv2.warpPerspective(current,refined,(self.w,self.h),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP)
        ncc=float(cv2.computeECC(self.gray,warped,self.mask))
        coverage=cv2.warpPerspective(np.full_like(current,255),refined,(self.w,self.h),flags=cv2.INTER_NEAREST|cv2.WARP_INVERSE_MAP)
        visible=float(np.mean(coverage[self.mask>0]>0))
        quality=max(0.,min(1.,float(score),ncc,ratio,visible))
        measured=cv2.perspectiveTransform(self.points.astype(np.float32).reshape(-1,1,2),refined).reshape(-1,2)+self.offset
        poses=plate_poses(measured,self.camera,self.object_points)
        if not poses:raise ValueError('No measured plate orientation')
        # Freeze the reference branch; use previous orientation only to reject planar flips.
        def cost(p):
            delta=cv2.Rodrigues(p['rotation']@self.previous_rotation.T)[0]
            return p['rms_px']+4*float(np.linalg.norm(delta))
        pose=min(poses,key=cost)
        jump=float(np.linalg.norm(cv2.Rodrigues(pose['rotation']@self.previous_rotation.T)[0]))
        if pose['rms_px']>5 or jump>.4:raise ValueError('Plate pose ambiguous/discontinuous')
        relative=pose['rotation']@self.reference_pose['rotation'].T
        vector=np.degrees(cv2.Rodrigues(relative)[0].ravel());magnitude=float(np.linalg.norm(vector))
        axis=measured[2:].mean(axis=0)-measured[:2].mean(axis=0)
        delta=(math.degrees(math.atan2(axis[1],axis[0]))-self.ref_angle+180)%360-180
        self.previous_rotation=pose['rotation']
        return dict(arm_id=self.arm_id,track_valid=True,confidence=quality,confidence_definition='min(masked ECC, masked NCC, RANSAC inlier ratio, visible support); not a probability',
            ecc=float(score),ncc=ncc,inliers=int(inside.sum()),inlier_ratio=ratio,feature_cycle_error_px=float(np.median(errors[good])),
            feature_residual_px=residual,visible_fraction=visible,spatial_cells=cells,hull_fraction=hull,
            plate_points_px=measured.tolist(),image_axis_delta_deg=delta,relative_rotation_vector_deg=vector.tolist(),
            relative_plate_rotation_deg=magnitude,pnp_rms_px=pose['rms_px'],reference_time=self.reference_time,
            measurement_mode='plate_relative_rotation_pnp',cv_version=VERSION,intrinsics_approximate=True,
            anatomical_joint_centers_measured=False,servo_counts_used=False)


class PlanarRegistrationTracker:
    """Frozen templates until explicit view reset. Loss never silently reanchors."""
    def __init__(self):self.reset()
    def reset(self):self.references={};self.reference_time=None
    def update(self,frame,timestamp):
        if not self.references:
            from mr_robot_desktop.skeleton import detect_skeletons
            from mr_robot_desktop.vision import PLATE_HOLES
            arms=detect_skeletons(frame)
            if len(arms)!=2:return []
            camera=camera_matrix(frame.shape);references={}
            for arm_id,arm in enumerate(arms,1):
                try:
                    candidate=detect_plate(frame,arm,camera)
                    references[arm_id]=PlateReference(frame,candidate['points'],arm_id,camera,PLATE_HOLES,timestamp)
                except (ValueError,cv2.error):return []
            self.references=references;self.reference_time=timestamp
        results=[]
        for arm_id,reference in self.references.items():
            try:results.append(reference.measure(frame))
            except (ValueError,cv2.error) as exc:
                results.append(dict(arm_id=arm_id,track_valid=False,invalid_reason=str(exc),confidence=None,pnp_rms_px=None,
                    relative_plate_rotation_deg=None,relative_rotation_vector_deg=None,image_axis_delta_deg=None,
                    reference_time=self.reference_time,cv_version=VERSION))
        return results
