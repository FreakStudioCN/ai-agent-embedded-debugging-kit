"""Versioned, conservative image-plane evidence. No hardware interfaces.

HOG people and Haar faces are exclusion detectors, not clearance detectors.
Non-detection never grants S1. Low texture/distribution/matching fails closed.
"""
import math
import cv2
import numpy as np
from experiment_safety import SafetyError


class StaticBackground:
    def __init__(self):
        self.gray=None;self.points=None;self.metadata={};self.sigma=0.
        self.face=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
        if self.face.empty():raise SafetyError('Human/face exclusion model unavailable; no motion admission')
        self.people=cv2.HOGDescriptor();self.people.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def exclusions(self,frame,boxes=()):
        h,w=frame.shape[:2];mask=np.full((h,w),255,np.uint8);excluded=[]
        green=cv2.inRange(cv2.cvtColor(frame,cv2.COLOR_BGR2HSV),(27,51,52),(78,255,255))
        contours,_=cv2.findContours(green,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        regions=[('green',cv2.boundingRect(c)) for c in contours if cv2.contourArea(c)>=30]
        small=cv2.resize(frame,(w//2,h//2));gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        for x,y,bw,bh in self.face.detectMultiScale(gray,1.1,4,minSize=(16,16)):
            # Include likely torso, conservatively extending below each face.
            regions.append(('face_and_body',(2*x-bw,2*y-bh,4*bw,8*bh)))
        humans,_=self.people.detectMultiScale(small,winStride=(8,8),padding=(8,8),scale=1.1)
        regions += [('person',tuple(2*int(v) for v in b)) for b in humans]
        regions += [('external_person_or_motion',b) for b in boxes]
        for kind,(x,y,bw,bh) in regions:
            x0=max(0,int(x)-16);y0=max(0,int(y)-16)
            x1=min(w,int(x+bw)+16);y1=min(h,int(y+bh)+16)
            mask[y0:y1,x0:x1]=0;excluded.append(dict(kind=kind,box=[x0,y0,x1-x0,y1-y0]))
        return mask,excluded

    @staticmethod
    def distribution(points,shape):
        h,w=shape;a=np.asarray(points).reshape(-1,2)
        cells={(min(2,int(x*3/w)),min(2,int(y*3/h))) for x,y in a}
        span=np.ptp(a,axis=0)/[w,h] if len(a) else [0,0]
        area=cv2.contourArea(cv2.convexHull(a.astype(np.float32)))/(w*h) if len(a)>=3 else 0
        return dict(occupied_cells=len(cells),span_fraction=np.asarray(span).tolist(),hull_fraction=area,
                    distributed=bool(len(cells)>=3 and min(span)>=.3 and area>=.08))

    def anchor(self,frame,boxes=()):
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);mask,excluded=self.exclusions(frame,boxes)
        h,w=gray.shape;points=[]
        for row in range(3):
            for col in range(3):
                cell=np.zeros_like(mask);cell[row*h//3:(row+1)*h//3,col*w//3:(col+1)*w//3]=255
                p=cv2.goodFeaturesToTrack(gray,35,.02,10,mask=cv2.bitwise_and(cell,mask))
                if p is not None:points.extend(p.reshape(-1,2))
        p=np.array(points,np.float32).reshape(-1,1,2);distribution=self.distribution(p,gray.shape)
        if len(p)<20 or not distribution['distributed']:raise SafetyError('DRIFT_UNKNOWN: insufficient distributed static features')
        _,descriptors=cv2.ORB_create(nfeatures=500).detectAndCompute(gray,mask)
        ambiguity=None
        if descriptors is not None and len(descriptors)>=20:
            matches=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(descriptors,descriptors,k=2)
            ambiguity=sum(len(m)==2 and m[1].distance<8 for m in matches)/len(matches)
            if ambiguity>.35:raise SafetyError('DRIFT_UNKNOWN: repeated texture descriptor ambiguity')
        self.gray=gray;self.points=p
        self.metadata=dict(features=len(p),width=w,height=h,distribution=distribution,exclusions=excluded,descriptor_ambiguity_ratio=ambiguity,
            sigma_definition='sample std (ddof=1) of median Euclidean reference displacements over >=3 s fresh stationary frames',
            sigma_background_px=self.sigma,points_px=p.reshape(-1,2).tolist())
        return self.metadata

    def compare(self,frame,boxes=()):
        if self.gray is None:return dict(valid=False,reason='no_anchor')
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        if gray.shape!=self.gray.shape:return dict(valid=False,reason='image_size_changed')
        mask,excluded=self.exclusions(frame,boxes)
        moved,f,_=cv2.calcOpticalFlowPyrLK(self.gray,gray,self.points,None,winSize=(31,31),maxLevel=4)
        if moved is None:return dict(valid=False,reason='LK_failed')
        back,b,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,moved,None,winSize=(31,31),maxLevel=4)
        if back is None:return dict(valid=False,reason='reverse_LK_failed')
        keep=f.ravel().astype(bool)&b.ravel().astype(bool)&(np.linalg.norm((back-self.points).reshape(-1,2),axis=1)<1)
        q=moved.reshape(-1,2);h,w=gray.shape
        inside=(q[:,0]>=0)&(q[:,0]<w)&(q[:,1]>=0)&(q[:,1]<h)
        for i in np.flatnonzero(inside):inside[i]=mask[int(q[i,1]),int(q[i,0])]>0
        keep &= inside;a=self.points.reshape(-1,2)[keep];q=q[keep]
        if len(a)<20:return dict(valid=False,reason='too_few_unmasked_matches')
        affine,inliers=cv2.estimateAffinePartial2D(a,q,method=cv2.RANSAC,ransacReprojThreshold=2)
        if affine is None or inliers is None:return dict(valid=False,reason='RANSAC_failed')
        good=inliers.ravel().astype(bool);ratio=float(good.mean());distribution=self.distribution(a[good],gray.shape)
        if good.sum()<20 or ratio<.65 or not distribution['distributed']:
            return dict(valid=False,reason='RANSAC_or_spatial_distribution_unreliable',inlier_ratio=ratio,distribution=distribution)
        fitted=cv2.transform(a[None],affine)[0];residual=np.linalg.norm(q-fitted,axis=1)
        grid=np.float32([[w*x,h*y] for x in (.15,.5,.85) for y in (.15,.5,.85)])
        shifts=np.linalg.norm(cv2.transform(grid[None],affine)[0]-grid,axis=1)
        displacement=float(np.median(np.linalg.norm(q[good]-a[good],axis=1)))
        return dict(valid=True,drift_px=displacement,median_shift_px=displacement,
            region_displacements_px=shifts.tolist(),region_max_displacement_px=float(max(shifts)),
            model_residual_px=float(np.median(residual[good])),rotation_deg=math.degrees(math.atan2(affine[1,0],affine[0,0])),
            scale=float(math.hypot(affine[0,0],affine[1,0])),background_inliers=int(good.sum()),inliers=int(good.sum()),
            inlier_ratio=ratio,distribution=distribution,exclusions=excluded,sigma_background_px=self.sigma)
