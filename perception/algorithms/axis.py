"""Image-plane axis fitting, extracted from the historical contour experiment.

Coordinates are pixels; output angles are image-plane degrees, not servo angles.
"""
import math
import numpy as np
import cv2

def axial_difference(a,b):return (float(a)-float(b)+90)%180-90

def axis_angle(vector):
    v=np.asarray(vector,float).ravel()[:2]
    if v[1]>0 or (v[1]==0 and v[0]<0):v=-v
    return math.degrees(math.atan2(v[1],v[0]))

def fit_axis(points):
    points=np.asarray(points,np.float32).reshape(-1,2)
    if len(points)<8:raise ValueError('too_few_axis_points')
    mean,eigenvectors,eigenvalues=cv2.PCACompute2(points,mean=None)
    vx,vy,x,y=cv2.fitLine(points,cv2.DIST_HUBER,0,.01,.01).ravel()
    pca=axis_angle(eigenvectors[0]);angle=axis_angle((vx,vy));direction=np.array([vx,vy],float)
    if direction[1]>0:direction=-direction
    center=np.array([x,y],float);delta=points-center
    residual=np.abs(delta[:,0]*direction[1]-delta[:,1]*direction[0])
    coordinate=delta@direction
    endpoints=np.array([center+direction*coordinate.min(),center+direction*coordinate.max()])
    return dict(angle_deg=angle,pca_angle_deg=pca,pca_fitline_disagreement_deg=abs(axial_difference(angle,pca)),
        eigenvalue_ratio=float(eigenvalues[0,0]/max(1e-9,eigenvalues[1,0])),
        residual_median_px=float(np.median(residual)),residual_p95_px=float(np.percentile(residual,95)),
        endpoints_px=endpoints.tolist(),span_px=float(np.ptp(coordinate)))
