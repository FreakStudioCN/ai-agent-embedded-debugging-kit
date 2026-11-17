"""Independent-frame, image-only rigid-link axis detection.

Retains the green segmentation idea of fused_pose.py, not its pose machinery.
No LK, PnP, FK, servo counts, shoulder coordinates, or link-length assumptions.
IDs are fixed mounting zones, not a re-numbered list of surviving components.
Angles describe a visible link's image axis, not an anatomical joint angle.
"""
from dataclasses import asdict,dataclass
from itertools import combinations
import hashlib
import json
import math
import cv2
import numpy as np


VERSION='contour-axis-2d-v3'
MODE='contour_axis_2d'


@dataclass(frozen=True)
class AxisConfig:
    hsv_low:tuple=(27,45,45)
    hsv_high:tuple=(78,255,255)
    seed_hsv_low:tuple=(28,65,65)
    seed_hsv_high:tuple=(68,255,255)
    lab_a_max:int=132
    lab_b_min:int=118
    seed_lab_a_max:int=127
    seed_lab_b_min:int=130
    base_zones:tuple=((.04,.47),(.52,.97))
    min_base_y:float=.56
    min_height_fraction:float=.28
    min_area_fraction:float=.0018
    min_height_width_ratio:float=1.05
    max_width_cv:float=.14
    max_axis_disagreement_deg:float=2.
    max_subaxis_spread_deg:float=3.
    max_edge_convergence_deg:float=8.
    min_quality:float=.80
    morph_open_fraction:float=.009
    target_link:str='distal_candidate'
    color_edge_evidence:bool=False
    min_entity_aspect:float=1.2
    min_entity_eigenvalue_ratio:float=1.8
    max_entity_axis_error_deg:float=5.

    @property
    def parameter_version(self):
        digest=hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()[:12]
        return VERSION+'-'+digest


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


def entity_axis_evidence(points,claimed_angle,config=None):
    """A short wide ledge cannot become a link just by fitting row centers."""
    c=config or AxisConfig();points=np.asarray(points,np.float32).reshape(-1,2)
    if len(points)<80:return dict(valid=False,quality=0.,invalid_reason='too_few_entity_pixels')
    points=points[::max(1,len(points)//5000)]
    _,vectors,values=cv2.PCACompute2(points,mean=None)
    angle=axis_angle(vectors[0]);ratio=float(values[0,0]/max(1e-9,values[1,0]))
    direction=np.array([math.cos(math.radians(claimed_angle)),math.sin(math.radians(claimed_angle))]);normal=np.array([-direction[1],direction[0]])
    long=points@direction;wide=points@normal
    length=float(np.percentile(long,98)-np.percentile(long,2));width=float(np.percentile(wide,98)-np.percentile(wide,2))
    aspect=length/max(1,width);error=abs(axial_difference(angle,claimed_angle))
    valid=aspect>=c.min_entity_aspect and ratio>=c.min_entity_eigenvalue_ratio and error<=c.max_entity_axis_error_deg
    quality=max(0.,min(1.,aspect/c.min_entity_aspect,ratio/c.min_entity_eigenvalue_ratio,1-error/25)) if valid else 0.
    return dict(valid=valid,quality=quality,entity_aspect=aspect,entity_eigenvalue_ratio=ratio,foreground_pca_angle_deg=angle,
        foreground_vs_claimed_axis_error_deg=error,invalid_reason=None if valid else 'roi_not_an_elongated_entity_in_claimed_axis')


def observed_entity_points(green,part,x,y):
    points=[]
    for rr,left,right,_ in part:
        rr=int(rr);lo=max(0,int(math.ceil(left-x)));hi=min(green.shape[1],int(math.floor(right-x))+1)
        xx=np.flatnonzero(green[rr,lo:hi])+lo+x
        if len(xx):points.append(np.column_stack((xx,np.full(len(xx),y+rr))))
    return np.concatenate(points).astype(np.float32) if points else np.zeros((0,2),np.float32)


class ContourAxisDetector:
    """Stateless detection. Calling order cannot affect a frame's result."""
    def __init__(self,config=None):self.config=config or AxisConfig()

    def segment(self,frame):
        c=self.config;hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV);lab=cv2.cvtColor(frame,cv2.COLOR_BGR2LAB)
        broad=cv2.inRange(hsv,c.hsv_low,c.hsv_high)
        broad[(lab[:,:,1]>c.lab_a_max)|(lab[:,:,2]<c.lab_b_min)]=0
        seed=cv2.inRange(hsv,c.seed_hsv_low,c.seed_hsv_high)
        seed[(lab[:,:,1]>c.seed_lab_a_max)|(lab[:,:,2]<c.seed_lab_b_min)]=0
        kernel=max(3,round(frame.shape[0]*c.morph_open_fraction)|1)
        broad=cv2.morphologyEx(broad,cv2.MORPH_OPEN,np.ones((kernel,kernel),np.uint8))
        broad=cv2.morphologyEx(broad,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        return broad,seed

    def _components(self,mask):
        """Split a cross-zone component only if two separated base lobes exist."""
        h,w=mask.shape;c=self.config
        n,labels,stats,_=cv2.connectedComponentsWithStats(mask,8);components=[];rejected=[]
        for k in range(1,n):
            x,y,bw,bh,area=map(int,stats[k])
            if area<h*w*c.min_area_fraction or bh<h*c.min_height_fraction:continue
            local=(labels==k).astype(np.uint8)*255
            if bw>w*.52:
                bottom=local[max(y,int(y+bh*.80)):y+bh]
                profile=(bottom>0).sum(axis=0).astype(np.float32)
                profile=cv2.GaussianBlur(profile[None],(21,1),0).ravel()
                left=int(np.argmax(profile[:w//2]));right=w//2+int(np.argmax(profile[w//2:]))
                if right-left<w*.20 or min(profile[left],profile[right])<5:
                    rejected.append('merged_component_without_two_bases');continue
                cut=left+int(np.argmin(profile[left:right+1]))
                if profile[cut]>.25*min(profile[left],profile[right]):
                    rejected.append('merged_base_ambiguity');continue
                for low,high in ((0,cut),(cut+1,w)):
                    split=local.copy();split[:,:low]=0;split[:,high:]=0
                    components.extend(self._simple_components(split,split_source=True))
            else:components.append((local,False))
        return components,rejected

    @staticmethod
    def _simple_components(mask,split_source=False):
        n,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
        return [((labels==k).astype(np.uint8)*255,split_source) for k in range(1,n) if stats[k,cv2.CC_STAT_AREA]>=100]

    def _edge_candidates(self,gray,green,body,color_index,x,y,bw,bh,base_width,base_x,top_x,division,seed_fraction):
        """Pair actual local contour/shading edges, then sample them again.

        Straightness is proposal evidence only. Color between the edges,
        occlusion, base association and link order also have to agree.
        """
        c=self.config;debug=dict(lines=0,parallel_pairs=0,overlap_pairs=0,width_pairs=0,sampled_pairs=0,geometry_pairs=0,mount_pairs=0)
        segments=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
        color_index=cv2.GaussianBlur(color_index,(3,3),0)
        chroma_segments=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(color_index)[0] if c.color_edge_evidence else None
        edge=cv2.bitwise_or(cv2.Canny(gray,35,100),cv2.Canny(green,40,120))
        if c.color_edge_evidence:edge=cv2.bitwise_or(edge,cv2.Canny(color_index,15,45))
        hough=cv2.HoughLinesP(edge,1,np.pi/720,20,minLineLength=max(28,round(bh*.06)),maxLineGap=max(5,round(bh*.035)))
        arrays=[a.reshape(-1,4) for a in (segments,chroma_segments,hough) if a is not None]
        if not arrays:return [],debug
        segments=np.concatenate(arrays)
        gradient=np.maximum(np.abs(cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)),np.abs(cv2.Sobel(green,cv2.CV_32F,1,0,ksize=3))*.25)
        if c.color_edge_evidence:
            gradient=np.maximum(np.maximum(np.abs(cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3))*.6,
                np.abs(cv2.Sobel(color_index,cv2.CV_32F,1,0,ksize=3))),np.abs(cv2.Sobel(green,cv2.CV_32F,1,0,ksize=3))*.10)
        edge_vertical=cv2.dilate(edge,np.ones((3,1),np.uint8))
        green_prefix=np.pad(np.cumsum((green>0).astype(np.int32),axis=1),((0,0),(1,0)))
        lines=[]
        for line in segments.reshape(-1,4):
            a,b=line[:2],line[2:]
            if a[1]>b[1]:a,b=b,a
            dy=float(b[1]-a[1])
            if dy<max(28,bh*.055):continue
            angle=axis_angle(b-a)
            if abs(axial_difference(angle,-90))>35:continue
            mid=(a+b)/2
            if not .23*bh<mid[1]<.82*bh:continue
            expected=top_x+(base_x-top_x)*np.clip((mid[1]/bh-.2)/.7,0,1)-x
            if abs(mid[0]-expected)>bw*.32:continue
            lines.append(dict(a=a,b=b,slope=float((b[0]-a[0])/dy),angle=angle))
        # Merge only collinear, overlapping observations of the SAME current
        # edge. Hough/LSD duplicates must not crowd out short distal edges.
        groups=[]
        for line in sorted(lines,key=lambda z:z['b'][1]-z['a'][1],reverse=True):
            assigned=False
            for group in groups:
                representative=group[0];low=max(line['a'][1],representative['a'][1]);high=min(line['b'][1],representative['b'][1])
                if high-low<min(15,(line['b'][1]-line['a'][1])*.3):continue
                yy=(low+high)/2
                ax=line['a'][0]+line['slope']*(yy-line['a'][1]);bx=representative['a'][0]+representative['slope']*(yy-representative['a'][1])
                if abs(axial_difference(line['angle'],representative['angle']))<=3 and abs(ax-bx)<=2.5:
                    group.append(line);assigned=True;break
            if not assigned:groups.append([line])
        combined=[]
        for group in groups:
            points=np.array([p for line in group for p in (line['a'],line['b'])],np.float32)
            vx,vy,cx,cy=cv2.fitLine(points,cv2.DIST_HUBER,0,.01,.01).ravel()
            if abs(vy)<.5:continue
            low=float(points[:,1].min());high=float(points[:,1].max());slope=float(vx/vy)
            a=np.array([cx+slope*(low-cy),low]);b=np.array([cx+slope*(high-cy),high])
            combined.append(dict(a=a,b=b,slope=slope,angle=axis_angle(b-a),edge_observations=len(group)))
        upper=sorted([q for q in combined if (q['a'][1]+q['b'][1])/2<bh*.52],key=lambda q:q['b'][1]-q['a'][1],reverse=True)[:16]
        lower=sorted([q for q in combined if (q['a'][1]+q['b'][1])/2>=bh*.52],key=lambda q:q['b'][1]-q['a'][1],reverse=True)[:16]
        lines=upper+lower;result=[]
        debug['lines']=len(lines)
        for first,second in combinations(lines,2):
            if abs(axial_difference(first['angle'],second['angle']))>c.max_edge_convergence_deg:continue
            debug['parallel_pairs']+=1
            top=max(first['a'][1],second['a'][1],bh*.25);bottom=min(first['b'][1],second['b'][1],bh*.80)
            if bottom-top<28:continue
            debug['overlap_pairs']+=1
            def xpos(line,yy):return line['a'][0]+line['slope']*(yy-line['a'][1])
            if xpos(first,(top+bottom)/2)>xpos(second,(top+bottom)/2):first,second=second,first
            width=xpos(second,(top+bottom)/2)-xpos(first,(top+bottom)/2)
            if not base_width*.12<width<base_width*.88:continue
            debug['width_pairs']+=1
            cuts=[top]+([bh*division] if division and top<bh*division<bottom else [])+[bottom]
            for start,stop in zip(cuts,cuts[1:]):
                start=int(math.ceil(start+2));stop=int(math.floor(stop-2))
                if stop-start<28:continue
                rr=np.arange(start,stop,dtype=int);observed=[];sample_valid=np.ones(len(rr),bool)
                for line in (first,second):
                    guesses=line['a'][0]+line['slope']*(rr-line['a'][1])
                    columns=np.rint(guesses).astype(int)[:,None]+np.arange(-4,5)[None,:]
                    sample_valid &= (columns[:,0]>=0)&(columns[:,-1]<bw)
                    columns=np.clip(columns,0,bw-1)
                    weights=gradient[rr[:,None],columns].copy()
                    sample_valid &= (weights.max(axis=1)>=8)&np.any(edge_vertical[rr[:,None],columns]>0,axis=1)
                    weights-=weights.min(axis=1)[:,None]
                    if c.color_edge_evidence:weights*=np.exp(-((columns-guesses[:,None])**2)/8)
                    totals=weights.sum(axis=1)
                    sample_valid &= totals>1e-6
                    observed.append((weights*columns).sum(axis=1)/np.maximum(totals,1e-6))
                left,right=observed;sample_valid &= right>left+2
                lo=np.clip(np.ceil(left).astype(int),0,bw);hi=np.clip(np.floor(right).astype(int),0,bw)
                support=(green_prefix[rr,hi]-green_prefix[rr,lo])/np.maximum(1,hi-lo)
                sample_valid &= support>=.70
                missing_indices=np.flatnonzero(~sample_valid)
                groups=np.split(missing_indices,np.flatnonzero(np.diff(missing_indices)>1)+1) if len(missing_indices) else []
                max_missing=max((len(g) for g in groups),default=0)
                samples=np.column_stack((rr[sample_valid],x+left[sample_valid],x+right[sample_valid],support[sample_valid]))
                if len(samples)<24 or len(samples)/(stop-start)<.85 or max_missing>max(3,(stop-start)*.10):continue
                debug['sampled_pairs']+=1
                part=np.array(samples);widths=part[:,2]-part[:,1];width_cv=float(widths.std()/max(1,float(np.median(widths))))
                if width_cv>c.max_width_cv:continue
                # Robustly discard at most15% isolated bevel/hole edge samples;
                # never fill them with predicted or previous-frame positions.
                initial_left=fit_axis(np.column_stack((part[:,1],y+part[:,0])))
                initial_right=fit_axis(np.column_stack((part[:,2],y+part[:,0])))
                keep=np.ones(len(part),bool)
                for column,fit0 in ((1,initial_left),(2,initial_right)):
                    endpoints=np.array(fit0['endpoints_px']);direction=endpoints[1]-endpoints[0];direction/=max(1e-9,np.linalg.norm(direction))
                    delta=np.column_stack((part[:,column],y+part[:,0]))-endpoints[0]
                    residual=np.abs(delta[:,0]*direction[1]-delta[:,1]*direction[0])
                    keep &= residual<=1.75
                if keep.mean()<.85 or keep.sum()<24:continue
                part=part[keep]
                centers=np.column_stack(((part[:,1]+part[:,2])/2,y+part[:,0]));fit=fit_axis(centers)
                lf=fit_axis(np.column_stack((part[:,1],y+part[:,0])));rf=fit_axis(np.column_stack((part[:,2],y+part[:,0])))
                parallel=abs(axial_difference(lf['angle_deg'],rf['angle_deg']))
                sub=[fit_axis(z)['angle_deg'] for z in np.array_split(centers,3) if len(z)>=8]
                spread=max((abs(axial_difference(a,b)) for a,b in combinations(sub,2)),default=0.)
                diagnostic=dict(parallel_deg=parallel,spread_deg=spread,pca_error_deg=fit['pca_fitline_disagreement_deg'],residual_px=fit['residual_p95_px'],rows=len(part),angle_deg=fit['angle_deg'])
                diagnostic['score']=max(parallel/8,spread/3,diagnostic['pca_error_deg']/2,diagnostic['residual_px']/1.5)
                if diagnostic['score']<debug.get('best_geometry',dict(score=float('inf')))['score']:debug['best_geometry']=diagnostic
                if parallel>c.max_edge_convergence_deg or spread>c.max_subaxis_spread_deg or fit['pca_fitline_disagreement_deg']>c.max_axis_disagreement_deg or fit['residual_p95_px']>1.5:continue
                debug['geometry_pairs']+=1
                low,high=start/bh,stop/bh
                if division is not None:
                    link='distal_candidate' if high<division+.005 else 'proximal_candidate' if low>division-.005 else 'joint_crossing_candidate'
                else:link='distal_candidate' if high<.50 else 'proximal_candidate' if low>.58 else 'ambiguous_link_order'
                # Thin parallel rails inside one face are not its whole-link axis.
                cross_support=[]
                for rr,l,r,_ in samples:
                    expected=top_x+(base_x-top_x)*np.clip((rr/bh-.2)/.7,0,1)
                    cross_support.append(abs((l+r)/2-expected)/max(1,base_width))
                association=float(np.median(cross_support))
                if association>.40:continue
                debug['mount_pairs']+=1
                detection=max(0.,min(1.,seed_fraction/.8,float(np.median(part[:,3]))/.85,1-association*.4))
                geometry=max(0.,min(1.,len(part)/(stop-start),1-width_cv,1-parallel/50,1-spread/15,
                    1-fit['pca_fitline_disagreement_deg']/10,1-fit['residual_p95_px']/12))
                entity=entity_axis_evidence(observed_entity_points(green,part,x,y),fit['angle_deg'],c)
                geometry=min(geometry,entity['quality'])
                quality=min(detection,geometry);valid=entity['valid'] and quality>=c.min_quality and link in ('distal_candidate','proximal_candidate')
                result.append(dict(link_id=link,roi_box_px=[int(part[:,1].min()),y+start,int(part[:,2].max()-part[:,1].min()+1),stop-start],
                    roi_interval_relative=[low,high],axis_angle_deg=fit['angle_deg'],pca_axis_angle_deg=fit['pca_angle_deg'],fitline_axis_angle_deg=fit['angle_deg'],
                    axis_endpoints_px=fit['endpoints_px'],detection_quality=detection,geometry_quality=geometry,confidence=quality,candidate_valid=valid,
                    invalid_reason=None if valid else entity['invalid_reason'] or 'edge_pair_identity_or_quality_ambiguous',candidate_source='local_contour_edge_pair',
                    entity_evidence=entity,centerline_pca_angle_deg=fit['pca_angle_deg'],geometric_evidence=dict(width_cv=width_cv,edge_parallel_error_deg=parallel,subaxis_spread_deg=spread,pca_fitline_error_deg=fit['pca_fitline_disagreement_deg'],
                        axis_residual_p95_px=fit['residual_p95_px'],centerline_eigenvalue_ratio=fit['eigenvalue_ratio'],roi_rows=len(part),row_occupancy=len(part)/(stop-start),
                        median_green_support=float(np.median(part[:,3])),seed_color_fraction=seed_fraction,base_to_shaft_width_ratio=base_width/max(1,float(np.median(widths))),
                        mount_position_association_error=association),selection_score=float(quality+.08*min(1,(stop-start)/(bh*.18)))))
        return result,debug

    def _candidate(self,mask,seed,frame,split_source):
        h,w=mask.shape;c=self.config
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not contours:raise ValueError('no_component_contour')
        contour=max(contours,key=cv2.contourArea);x,y,bw,bh=cv2.boundingRect(contour)
        if bh<h*c.min_height_fraction or bh<max(1,bw)*c.min_height_width_ratio:raise ValueError('non_arm_component_shape')
        filled=np.zeros_like(mask);cv2.drawContours(filled,[contour],-1,255,cv2.FILLED)
        base_start=y+round(bh*.82);ys,xs=np.nonzero(filled[base_start:y+bh])
        if not len(xs):raise ValueError('missing_base')
        base_x=float(np.median(xs));base_y=float(base_start+np.median(ys))
        if base_y/h<c.min_base_y:raise ValueError('base_outside_lower_anchor_area')
        matches=[i for i,(lo,hi) in enumerate(c.base_zones,1) if lo<=base_x/w<=hi]
        if len(matches)!=1:raise ValueError('base_id_zone_ambiguous')
        arm_id=matches[0];seed_fraction=float(np.mean(seed[mask>0]>0))
        if seed_fraction<.50:raise ValueError('insufficient_lime_arm_color_support')
        local_green=mask[y:y+bh,x:x+bw]
        fork_rows=[]
        for rr in range(max(0,round(bh*.025)),round(bh*.25)):
            active=np.flatnonzero(local_green[rr]);runs=np.split(active,np.flatnonzero(np.diff(active)>1)+1) if len(active) else []
            substantial=[q for q in runs if len(q)>=bw*.04]
            if any(b[0]-a[-1]>bw*.12 for a,b in zip(substantial,substantial[1:])):fork_rows.append(rr)
        fork_valid=len(fork_rows)>=max(4,round(bh*.025))
        upper_yy,upper_xx=np.nonzero(mask[y+round(bh*.10):y+round(bh*.28)])
        top_x=float(np.median(upper_xx)) if len(upper_xx) else base_x
        closed=cv2.morphologyEx(local_green,cv2.MORPH_CLOSE,np.ones((1,max(5,round(bw*.055)|1)),np.uint8))
        body=np.zeros_like(local_green);cross=[]
        for rr in range(bh):
            active=np.flatnonzero(closed[rr]);expected=top_x+(base_x-top_x)*np.clip((rr/bh-.2)/.7,0,1)-x
            runs=np.split(active,np.flatnonzero(np.diff(active)>1)+1) if len(active) else []
            eligible=[run for run in runs if len(run)>=max(4,bw*.055) and abs((run[0]+run[-1])/2-expected)<bw*.32]
            if not eligible:continue
            run=min(eligible,key=lambda q:abs((q[0]+q[-1])/2-expected)-len(q)*.08)
            left,right=float(run[0]),float(run[-1]);body[rr,run[0]:run[-1]+1]=255
            support=float(np.mean(local_green[rr,run[0]:run[-1]+1]>0))
            cross.append((rr,x+left,x+right,support))
        cross=np.asarray(cross,float)
        if len(cross)<40:raise ValueError('insufficient_current_frame_cross_sections')
        gray=cv2.cvtColor(frame[y:y+bh,x:x+bw],cv2.COLOR_BGR2GRAY)
        contrast=cv2.morphologyEx(gray,cv2.MORPH_BLACKHAT,np.ones((max(9,round(bh*.07)|1),3),np.uint8))
        holes=((contrast>18)&(cv2.erode(body,np.ones((3,3),np.uint8))>0)).astype(np.uint8)*255
        holes=cv2.morphologyEx(holes,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        voids,_=cv2.findContours(holes,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);slots=[]
        for void in voids:
            sx,sy,sw,sh=cv2.boundingRect(void)
            if .25*bh<sy<.80*bh and sw>bw*.22 and sw>sh*2.5 and sh<bh*.08:slots.append((sy+sh/2)/bh)
        central=[v for v in slots if .40<v<.64];division=min(central,key=lambda v:abs(v-.52)) if central else None
        base_width=float(np.percentile(np.sum(body[round(bh*.82):]>0,axis=1),80))
        middle=cross[(cross[:,0]>.30*bh)&(cross[:,0]<.78*bh)]
        middle_width=float(np.median(middle[:,2]-middle[:,1]+1)) if len(middle) else 0.
        if base_width/max(1,middle_width)<1.12:raise ValueError('no_distinct_base_and_link_width_topology')
        candidates=[];reason_counts={}
        def reject(reason):reason_counts[reason]=reason_counts.get(reason,0)+1
        # Local candidates are generated before assigning a rigid-link identity.
        # No full-arm PCA, no temporal association and no inferred servo axis.
        for length_fraction in (.085,.11,.14,.18,.22,.24,.26,.28,.30,.32,.36):
            length=max(28,round(bh*length_fraction))
            for top in range(round(bh*.16),round(bh*.82)-length+1,max(5,round(bh*.022))):
                bottom=top+length;part=cross[(cross[:,0]>=top)&(cross[:,0]<bottom)]
                if len(part)<24 or len(part)/length<.92:reject('occluded_cross_sections');continue
                widths=part[:,2]-part[:,1]+1;median=float(np.median(widths));width_cv=float(widths.std()/max(1,median))
                if width_cv>c.max_width_cv:reject('unstable_link_width');continue
                if median<base_width*.12 or median>base_width*.88:reject('width_incompatible_with_rigid_link_and_base');continue
                yy=part[:,0];left=part[:,1];right=part[:,2];xx=(left+right)/2
                coefficients=np.stack([np.polyfit(yy,left,1),np.polyfit(yy,right,1),np.polyfit(yy,xx,1)])
                predicted=coefficients[:,0,None]*yy+coefficients[:,1,None]
                residual=np.maximum(abs(left-predicted[0]),abs(right-predicted[1]))
                inlier=residual<=max(1.25,median*.015)
                if inlier.mean()<.85:reject('nonstraight_or_occluded_edges');continue
                part=part[inlier];centers=np.column_stack(((part[:,1]+part[:,2])/2,y+part[:,0]))
                left_points=np.column_stack((part[:,1],y+part[:,0]));right_points=np.column_stack((part[:,2],y+part[:,0]))
                fit=fit_axis(centers);lf=fit_axis(left_points);rf=fit_axis(right_points)
                parallel=abs(axial_difference(lf['angle_deg'],rf['angle_deg']))
                subaxes=[fit_axis(z)['angle_deg'] for z in np.array_split(centers,3) if len(z)>=8]
                spread=max((abs(axial_difference(a,b)) for a,b in combinations(subaxes,2)),default=0.)
                if parallel>c.max_edge_convergence_deg or spread>c.max_subaxis_spread_deg or fit['pca_fitline_disagreement_deg']>c.max_axis_disagreement_deg:
                    reject('inconsistent_local_axis_geometry');continue
                if abs(axial_difference(fit['angle_deg'],-90))>40:reject('nonlongitudinal_rigid_link');continue
                relative_top=top/bh;relative_bottom=bottom/bh
                if division is not None:
                    link='distal_candidate' if relative_bottom<division-.005 else 'proximal_candidate' if relative_top>division+.015 else 'joint_crossing_candidate'
                else:
                    link='distal_candidate' if relative_bottom<.50 else 'proximal_candidate' if relative_top>.58 else 'ambiguous_link_order'
                support=float(np.median(part[:,3]));occupancy=len(part)/length
                detection=max(0.,min(1.,seed_fraction/.8,bh/(h*.4),support/.75,base_width/max(1,median)/1.4))
                geometry=max(0.,min(1.,occupancy,1-width_cv,1-parallel/60,1-spread/15,
                    1-fit['pca_fitline_disagreement_deg']/10,1-fit['residual_p95_px']/max(10,fit['span_px']*.25)))
                entity=entity_axis_evidence(observed_entity_points(local_green,part,x,y),fit['angle_deg'],c)
                geometry=min(geometry,entity['quality'])
                quality=min(detection,geometry);valid=entity['valid'] and quality>=c.min_quality and link in ('distal_candidate','proximal_candidate')
                reason=None if valid else entity['invalid_reason'] or 'link_identity_or_quality_ambiguous'
                roi=[int(part[:,1].min()),y+top,int(part[:,2].max()-part[:,1].min()+1),length]
                candidates.append(dict(link_id=link,roi_box_px=roi,roi_interval_relative=[relative_top,relative_bottom],
                    axis_angle_deg=fit['angle_deg'],pca_axis_angle_deg=fit['pca_angle_deg'],fitline_axis_angle_deg=fit['angle_deg'],axis_endpoints_px=fit['endpoints_px'],
                    detection_quality=detection,geometry_quality=geometry,confidence=quality,candidate_valid=valid,invalid_reason=reason,
                    entity_evidence=entity,centerline_pca_angle_deg=fit['pca_angle_deg'],geometric_evidence=dict(width_cv=width_cv,edge_parallel_error_deg=parallel,subaxis_spread_deg=spread,pca_fitline_error_deg=fit['pca_fitline_disagreement_deg'],
                        axis_residual_p95_px=fit['residual_p95_px'],centerline_eigenvalue_ratio=fit['eigenvalue_ratio'],roi_rows=len(part),row_occupancy=occupancy,
                        median_green_support=support,seed_color_fraction=seed_fraction,base_to_shaft_width_ratio=base_width/max(1,median)),
                    selection_score=float(quality+.08*min(1,length/(bh*.18)))))
        rgb=frame[y:y+bh,x:x+bw].astype(np.int16)
        color_index=np.clip(2*rgb[:,:,1]-rgb[:,:,0]-rgb[:,:,2],0,255).astype(np.uint8)
        edge_candidates,edge_debug=self._edge_candidates(gray,local_green,body,color_index,x,y,bw,bh,base_width,base_x,top_x,division,seed_fraction)
        candidates.extend(edge_candidates)
        # Nonmaximum suppression combines overlapping windows of the same visible link.
        representatives=[]
        for candidate in sorted(candidates,key=lambda z:z['selection_score'],reverse=True):
            a,b=candidate['roi_interval_relative']
            if any(candidate['link_id']==q['link_id'] and abs(axial_difference(candidate['axis_angle_deg'],q['axis_angle_deg']))<=1.
                and max(0,min(b,q['roi_interval_relative'][1])-max(a,q['roi_interval_relative'][0]))/min(b-a,q['roi_interval_relative'][1]-q['roi_interval_relative'][0])>.5 for q in representatives):continue
            representatives.append(candidate)
        intended=[q for q in representatives if q['link_id']==c.target_link]
        accepted=[q for q in intended if q['candidate_valid']]
        selected=accepted[0] if accepted else intended[0] if intended else representatives[0] if representatives else None
        if selected is None:
            result=self.invalid(arm_id,'no_width_stable_parallel_rigid_link_candidate')
            result['detection_quality']=max(0.,min(1.,seed_fraction/.8,bh/(h*.4)))
        else:
            result=dict(selected);valid=selected in accepted;reason=selected['invalid_reason'] if not valid else None
            competitors=[q for q in accepted[1:] if abs(axial_difference(q['axis_angle_deg'],selected['axis_angle_deg']))>2]
            if competitors:valid=False;reason='multiple_geometrically_valid_links_with_conflicting_axes'
            if split_source and (selected['roi_box_px'][0]<=x+3 or selected['roi_box_px'][0]+selected['roi_box_px'][2]>=x+bw-3):
                valid=False;reason='roi_touches_unverified_component_split'
            if not fork_valid:valid=False;reason='rigid_link_identity_unverified_missing_fork_topology'
            elif selected['roi_interval_relative'][0]<(max(fork_rows)/bh+.015):
                valid=False;reason='roi_overlaps_gripper_fork_not_rigid_link_body'
            result.update(arm_id='green_'+str(arm_id),measurement_valid=valid,raw_axis_angle_deg=selected['axis_angle_deg'],
                axis_angle_deg=selected['axis_angle_deg'] if valid else None,invalid_reason=reason or (None if valid else 'intended_rigid_link_not_identifiable'))
        for q in representatives:q['selected_for_measurement']=q is selected
        result.update(component_box_px=[x,y,bw,bh],base_anchor_px=[base_x,base_y],rigid_link=c.target_link,
            roi_method='local_parallel_edge_candidates_then_mount_identity_topology_and_occlusion_checks',
            transverse_slots_relative=sorted(slots),structural_division_relative=division,component_split_at_base_valley=split_source,
            roi_candidates=representatives[:10],candidate_rejections_summary=reason_counts,edge_candidate_stage_counts=edge_debug,
            topology_evidence=dict(fork_visible=fork_valid,fork_rows=len(fork_rows),base_to_midbody_width_ratio=base_width/max(1,middle_width)))
        return result

    def detect(self,frame):
        if frame is None or frame.ndim!=3 or min(frame.shape[:2])<100:raise ValueError('Invalid BGR image')
        mask,seed=self.segment(frame);components,rejected=self._components(mask);candidates={1:[],2:[]}
        for component,split_source in components:
            try:
                result=self._candidate(component,seed,frame,split_source);candidates[int(result['arm_id'][-1])].append(result)
            except ValueError as exc:rejected.append(str(exc))
        rows=[]
        for arm_id in (1,2):
            possible=sorted(candidates[arm_id],key=lambda r:r['confidence'],reverse=True)
            if len(possible)>1 and possible[1]['confidence']>=possible[0]['confidence']-.10:
                row=self.invalid(arm_id,'ambiguous_multiple_arm_candidates_in_base_zone')
            elif possible:row=possible[0]
            else:row=self.invalid(arm_id,'no_valid_rigid_link_candidate')
            row.update(measurement_mode=MODE,cv_version=VERSION,parameter_version=self.config.parameter_version,
                pnp_rms_px=None,rms_px=None,absolute_joint_angles=None,servo_counts_used=False,
                angle_definition='atan2(image dy,image dx); axis directed upward; axial modulo180deg',
                rejected_component_reasons=rejected)
            row['object_detected']=row.get('component_box_px') is not None
            row['identity_valid']=row['object_detected'] and row.get('invalid_reason')!='ambiguous_multiple_arm_candidates_in_base_zone'
            if not row['measurement_valid']:row['axis_angle_deg']=None;row['delta_angle_deg']=None
            rows.append(row)
        return rows

    @staticmethod
    def invalid(arm_id,reason):
        return dict(arm_id='green_'+str(arm_id),measurement_valid=False,axis_angle_deg=None,delta_angle_deg=None,
            detection_quality=0.,geometry_quality=0.,confidence=0.,axis_endpoints_px=None,component_box_px=None,
            base_anchor_px=None,roi_box_px=None,invalid_reason=reason)


def axis_window_stats(rows,minimum_ms=1200):
    """Only one version/view/mode is comparable; never substitute an old angle."""
    if not rows:return None
    versions={r.get('calibration_version') for r in rows};views={r.get('camera_pose_id') for r in rows};modes={r.get('measurement_mode') for r in rows}
    good=[r for r in rows if r.get('measurement_valid') and r.get('axis_angle_deg') is not None]
    span=rows[-1]['monotonic_ms']-rows[0]['monotonic_ms'];ratio=len(good)/len(rows)
    if len(good)<3:return dict(measurement_valid=False,stationary=False,valid_ratio=ratio,window_ms=span,invalid_reason='insufficient_valid_angles')
    angles=np.degrees(np.unwrap(np.radians([2*r['axis_angle_deg'] for r in good])))/2
    times=np.array([r['monotonic_ms'] for r in good])/1000;std=float(angles.std(ddof=1));trend=float(np.polyfit(times-times[0],angles,1)[0])
    valid=len(versions)==len(views)==len(modes)==1 and modes=={MODE} and None not in versions
    return dict(measurement_valid=valid,stationary=bool(valid and span>=minimum_ms and ratio>=.85 and std<=1.5 and abs(trend)<=1),
        window_ms=span,valid_ratio=ratio,axis_median_deg=float(np.median(angles)),axis_std_deg=std,axis_drift_deg_per_s=trend,
        detection_quality_median=float(np.median([r['detection_quality'] for r in good])),geometry_quality_median=float(np.median([r['geometry_quality'] for r in good])),
        calibration_version=next(iter(versions)) if valid else None,measurement_mode=MODE,invalid_reason=None if valid else 'mixed_versions_views_or_modes')


def assert_axis_comparable(*measurements):
    keys=('measurement_mode','parameter_version','calibration_version','camera_pose_id')
    for key in keys:
        values={m.get(key) for m in measurements}
        if len(values)!=1 or None in values:raise ValueError('incomparable_'+key)
    if not measurements or measurements[0]['measurement_mode']!=MODE:raise ValueError('not_contour_axis_measurements')


def draw_axis_overlay(frame,rows,source_time_s=None):
    """Only current-frame candidates are drawn; rejected angles stay invalid."""
    image=frame.copy()
    if source_time_s is not None:cv2.putText(image,f'OFFLINE contour_axis_2d | source {source_time_s:.3f}s',(16,28),0,.65,(255,255,255),2,cv2.LINE_AA)
    for row in rows:
        valid=row['measurement_valid'];color=(60,230,80) if valid else (70,70,255)
        for candidate_index,candidate in enumerate(row.get('roi_candidates',[])[:10],1):
            x,y,w,h=candidate['roi_box_px'];selected=candidate.get('selected_for_measurement',False)
            shade=color if selected else (80,170,220) if candidate['candidate_valid'] else (90,90,190)
            cv2.rectangle(image,(x,y),(x+w,y+h),shade,2 if selected else 1)
            candidate_label=f"{candidate_index} {candidate['link_id']} "+('ACCEPT' if selected and valid else 'PROPOSAL_ONLY' if candidate['candidate_valid'] else 'REJECT')
            candidate_reason=candidate.get('invalid_reason') or 'local geometry passed; final identity gate applies'
            for offset,text in enumerate((candidate_label,candidate_reason)):
                origin=(max(3,min(x,image.shape[1]-560)),max(40,y-20)+offset*14)
                cv2.putText(image,text,origin,0,.33,(0,0,0),2,cv2.LINE_AA)
                cv2.putText(image,text,origin,0,.33,shade,1,cv2.LINE_AA)
            if candidate.get('axis_endpoints_px'):
                points=np.rint(candidate['axis_endpoints_px']).astype(int);cv2.line(image,tuple(points[0]),tuple(points[1]),shade,3,cv2.LINE_AA)
        box=row.get('component_box_px')
        if box:
            x,y,w,h=box;cv2.rectangle(image,(x,y),(x+w,y+h),color,1)
            label_y=min(image.shape[0]-75,max(55,y+h+20))
        else:x=20 if row['arm_id']=='green_1' else image.shape[1]//2;label_y=70
        label=row['arm_id']+' '+row.get('rigid_link','distal_candidate')+' '+('ACCEPT' if valid else 'REJECT')
        angle=f"axis={row['axis_angle_deg']:.3f} deg" if valid else 'axis=null (no hold-last-angle)'
        reason='current observed contour' if valid else row.get('invalid_reason','unknown')
        for index,line in enumerate((label,angle,reason)):
            px=max(5,min(x,image.shape[1]-570));py=label_y+index*20
            cv2.putText(image,line,(px,py),0,.48,(0,0,0),3,cv2.LINE_AA)
            cv2.putText(image,line,(px,py),0,.48,color,1,cv2.LINE_AA)
    return image
