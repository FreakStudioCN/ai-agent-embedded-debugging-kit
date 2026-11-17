"""Bounded dual-arm choreography and observation-arm acquisition.

Uses shared camera services, the existing COM3 driver and the prepared MicroPython
DualArm instance on COM8. Start with the documented clear workspace and prepared
reference pose. Every segment is followed by fresh-image settling verification.
"""
import argparse
import ast
from datetime import datetime, timezone
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import sys
import time
from urllib.request import urlopen
import uuid

import cv2
import numpy as np
from PIL import Image
import serial
from serial.tools import list_ports

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))
from exploration_events import emit
from pc_control import PCUART
from robot_arm import RobotArm
from monitor_core import VideoReader
from cv_pipeline.monitor_pose import PoseWorker

REFERENCE = {1: [307, 287, 297], 2: [307, 307, 307]}
WINDOWS = {1: [(307,327),(287,307),(297,317)], 2: [(297,357),(297,337),(297,337)]}


def utc():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


class MicroPythonSession:
    def __init__(self, port):
        self.port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        self.port.dtr = False
        self.port.rts = False
        self.port.port = port
        self.port.open()
        name = 'device-'+port+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.jsonl'
        self.path = ROOT / '.runtime' / name
        self.log = self.path.open('a', encoding='utf-8', buffering=1)
        self.failed = False
        self.record('device_ready', port=port)

    def record(self, event, **fields):
        self.log.write(json.dumps(dict(time=utc(),event=event,**fields),ensure_ascii=False)+'\n')

    def rpc(self, expression, timeout=18):
        if self.failed:
            raise RuntimeError('Previous board operation is unresolved; inspect before reconnecting')
        marker = 'DEMO_'+uuid.uuid4().hex
        command = "print(%r, repr(%s))\r" % (marker, expression)
        self.port.write(command.encode('utf-8'))
        self.record('device_sent', payload=command)
        deadline = time.monotonic()+timeout
        buffer = bytearray()
        while time.monotonic() < deadline:
            data = self.port.read(max(1,min(self.port.in_waiting,65536)))
            if not data:
                continue
            buffer.extend(data)
            while b'\n' in buffer:
                line,_,buffer = buffer.partition(b'\n')
                text = line.decode('utf-8','replace').strip()
                self.record('device_received',text=text+'\n')
                if text.startswith(marker+' '):
                    try:
                        return ast.literal_eval(text[len(marker)+1:])
                    except (ValueError,SyntaxError):
                        self.failed = True
                        raise
                if 'Traceback (most recent call last)' in text:
                    self.failed = True
                    raise RuntimeError('Board exception. No further motion queued.')
        self.failed = True
        raise TimeoutError('Board result timed out. Physical state requires inspection.')

    def close(self):
        self.record('device_closed')
        self.port.close()
        self.log.close()


class Demo:
    def __init__(self, args):
        self.args = args
        self.folder = args.output.resolve()
        self.folder.mkdir(parents=True,exist_ok=False)
        (self.folder/'frames').mkdir()
        self.events = (self.folder/'events.jsonl').open('a',encoding='utf-8',buffering=1)
        self.small = None
        self.uart = None
        self.video = None
        self.pose = None
        self.counts = {arm:list(value) for arm,value in REFERENCE.items()}
        self.observer_target = [0,164,120]
        self.view_id = 'A'
        self.report = dict(started_utc=utc(), steps=[], identity_checks=[], cycles=[], views=[],
                           coordinates='Per-view image pixels. Cross-view metric transform unverified.',
                           command_angles_are_targets=True, physical_joint_angle_error_deg=None)

    def event(self, kind, text, english, **fields):
        record = emit(kind,text,text_en=english,**fields)
        self.events.write(json.dumps(record,ensure_ascii=False)+'\n')
        print(text,flush=True)

    def snapshot(self, label):
        result = dict(time=utc(),view_id=self.view_id,images={},camera_status={})
        for name,base in (('wrist',self.args.camera),('external',self.args.external)):
            deadline = time.monotonic()+15
            warned = False
            while True:
                status = json.loads(urlopen(base+'/api/status',timeout=4).read())
                if status['healthy'] and status['frame_age_seconds'] <= 1:
                    break
                if not warned:
                    self.event('note',name+'视频中断，保持当前姿态并等待新鲜画面。',name+' video interrupted; holding the current pose while waiting for fresh frames.')
                    warned = True
                if time.monotonic()>deadline:
                    raise RuntimeError(name+' camera stale. New motion paused.')
                time.sleep(.5)
            with urlopen(base+'/snapshot.jpg',timeout=4) as response:
                data = response.read()
                frame_id = response.headers.get('X-Frame-Id')
            path = self.folder/'frames'/(label+'-'+name+'.jpg')
            path.write_bytes(data)
            result['images'][name] = str(path)
            result['camera_status'][name] = dict(**status,snapshot_frame_id=frame_id,receipt_utc=utc())
        self.events.write(json.dumps(dict(event='camera_sample',**result),ensure_ascii=False)+'\n')
        return result

    def wait_stable(self, label):
        last = self.snapshot(label+'-a')
        for attempt in range(6):
            time.sleep(.6)
            current = self.snapshot(label+'-b%d'%attempt)
            before = cv2.imread(last['images']['wrist'])
            after = cv2.imread(current['images']['wrist'])
            mask = cv2.inRange(cv2.cvtColor(before,cv2.COLOR_BGR2HSV),(27,51,52),(78,255,255))
            mask = cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((7,7),np.uint8))
            gray = cv2.cvtColor(before,cv2.COLOR_BGR2GRAY)
            points = cv2.goodFeaturesToTrack(gray,120,.03,8,mask=mask)
            if points is None:
                raise RuntimeError('No green-arm features for settling verification')
            moved,valid,_ = cv2.calcOpticalFlowPyrLK(gray,cv2.cvtColor(after,cv2.COLOR_BGR2GRAY),points,None)
            distances = np.linalg.norm((moved-points).reshape(-1,2)[valid.ravel()==1],axis=1)
            if len(distances) < 12:
                raise RuntimeError('Insufficient settling evidence')
            p90 = float(np.percentile(distances,90))
            current['settling_p90_px'] = p90
            if p90 < .8:
                return current
            last = current
        raise RuntimeError('Images did not confirm physical settling')

    def start(self):
        ports = {port.device:port for port in list_ports.comports()}
        small_port = ports.get(self.args.small_port)
        large_port = ports.get(self.args.large_port)
        if not small_port or small_port.serial_number.lower() != '70:af:09:2a:ee:e8':
            raise RuntimeError('Small controller USB identity does not match the inspected board')
        if not large_port or (large_port.vid,large_port.pid)!=(0x1a86,0x7523):
            raise RuntimeError('Observation-arm CH340 interface does not match the inspected device')
        self.report['hardware'] = {name:dict(port=value.device,hwid=value.hwid) for name,value in (('small',small_port),('observer',large_port))}
        self.snapshot('startup')
        self.small = MicroPythonSession(self.args.small_port)
        status = self.small.rpc('d.status()')
        if not status['enabled'] or status['scheduled_busy'] or status['command_counts'] != REFERENCE:
            raise RuntimeError('Prepared DualArm reference is required. Inspect current pose before initialization.')
        uid = self.small.rpc("__import__('machine').unique_id().hex()")
        if uid != '70af092aeee8':
            raise RuntimeError('Small controller chip identity mismatch')
        self.report['hardware']['small']['chip_uid'] = uid
        checks = self.small.rpc("{'prescale':d.pca.i2c.readfrom_mem(d.pca.address,254,1)[0],'pwm':[(ch,list(d.pca.i2c.readfrom_mem(d.pca.address,6+4*ch,4))) for ch in range(16)]}")
        if checks['prescale'] != 121 or any(values != [0,0,0,16] for channel,values in checks['pwm'][:8]):
            raise RuntimeError('PWM frequency or chassis output state mismatch')
        self.report['hardware']['pca'] = checks
        self.uart = PCUART(self.args.large_port)
        original = self.uart.write
        def logged_write(data):
            written = original(data)
            if written == len(data) and data.endswith(b'\n'):
                self.event('sending',data.decode().strip(),data.decode().strip(),command=data.decode().strip())
            return written
        self.uart.write = logged_write
        self.observer = RobotArm(self.uart,timeout_ms=120000)
        self.observer.dwell(0)
        self.video = VideoReader(self.args.camera+'/stream.mjpg',180)
        self.video.thread.start()
        self.pose = PoseWorker(self.video,self.args.pose_library,self.folder/'poses.jsonl',fused=True,state_directory=ROOT/'.runtime')
        self.pose.thread.start()
        evidence = self.wait_stable('initial-reference')
        self.small.rpc('d.confirm_settled(%r)'%evidence['images']['wrist'])
        self.event('observation','供电功能、USB标识、PWM映射与双摄新鲜画面已核对。','Verified functional actuation, USB identities, PWM mapping and fresh dual-camera images.',hardware=self.report['hardware'])

    def move_small(self, first, second, label, speed=None):
        self.ensure_pose(label)
        targets = {1:list(first),2:list(second)}
        for arm in (1,2):
            for value,(low,high) in zip(targets[arm],WINDOWS[arm]):
                if not low <= value <= high:
                    raise ValueError('Target exceeds the inspected local window')
        self.snapshot(label+'-before')
        speed = speed or self.args.speed
        command = 'd.run_segment(%r,%r,speed=%r)'%(tuple(first),tuple(second),speed)
        started = utc()
        result = self.small.rpc(command)
        if result['scheduled_busy']:
            raise RuntimeError('Board trajectory still busy')
        self.event('execution',command,command,target_counts=targets,feedback=result)
        evidence = self.wait_stable(label)
        self.small.rpc('d.confirm_settled(%r)'%evidence['images']['wrist'])
        self.counts = targets
        step = dict(label=label,started_utc=started,ended_utc=utc(),target_counts=targets,
                    speed_command_deg_s=speed,controller_feedback=result,evidence=evidence)
        self.report['steps'].append(step)
        self.event('result',label+' 已通过新鲜画面确认停稳。',label+' physically settled in fresh images.',frame=evidence['images']['wrist'],step=step)
        return evidence

    def ensure_pose(self, label):
        for attempt in range(2):
            deadline = time.monotonic()+4
            while time.monotonic()<deadline:
                _,_,received,stats = self.pose.latest()
                poses = stats.get('poses',[])
                if (time.monotonic()-received<.75 and len(poses)==2 and
                        all(pose['status']=='visual_constrained' and pose.get('quality_score',0)>.3 for pose in poses)):
                    return
                if stats.get('error'):
                    raise RuntimeError('Vision worker error: '+stats['error'])
                time.sleep(.1)
            if attempt==0:
                self.event('interpretation','姿态质量不足，先移动观察臂重新捕获。','Pose quality is insufficient; moving the observation arm to reacquire before further small-arm motion.')
                self.move_observer([0,164,125],'reacquire-'+label)
        raise RuntimeError('Pose confidence remained low after reacquisition')

    def move_observer(self, target, label, speed=5):
        if not (-10 <= target[0] <= 0 and 164 <= target[1] <= 174 and 120 <= target[2] <= 130 and 5 <= speed <= 7):
            raise ValueError('Observation target exceeds the inspected cruise envelope')
        self.snapshot(label+'-before')
        self.event('next_action','检验机位变化是否改善遮挡与孔位质量，移动到 '+label+' 后停留采样。',
                   'Test whether the new viewpoint improves occlusion and plate-feature quality; move to '+label+' and sample after settling.',
                   view_target_mm=target,observer_speed_mm_s=speed,
                   criterion='Two tracked identities, at least 3 plate features and explicit per-view coordinates')
        command = 'G1 X%g Y%g Z%g F%g'%(*target,speed)
        self.observer.command(command)
        distance = math.dist(target,self.observer_target)
        time.sleep(max(3,distance/speed+2))
        evidence = self.wait_stable(label)
        self.event('motion_verified','观察臂停稳，更新当前机位。','Observation arm settled; updating the camera view.',command=command,frame=evidence['images']['wrist'])
        self.observer_target = list(target)
        self.view_id = label
        self.report['views'].append(dict(view_id=label,target_mm=target,speed_mm_s=speed,evidence=evidence,cross_view_transform_verified=False))
        time.sleep(1)
        return evidence

    def quality(self, started):
        path = self.folder/'poses.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.endswith('}')]
        rows = [row for row in rows if row['processed_utc']>=started]
        poses = [pose for row in rows for pose in row['arms']]
        model_errors = [pose['command_to_visual_plate_rms_px'] for pose in poses if pose.get('command_to_visual_plate_rms_px') is not None]
        return dict(frames=len(rows),lost=sum(pose['status']=='lost' for pose in poses),
                    predicted=sum(pose['status']=='model_predicted' for pose in poses),
                    mean_processing_ms=float(np.mean([row['processing_ms'] for row in rows])) if rows else None,
                    quality_p10=float(np.percentile([pose.get('quality_score',0) for pose in poses],10)) if poses else 0,
                    command_visual_rms_p90_px=float(np.percentile(model_errors,90)) if model_errors else None)

    def verify_mapping(self, before, after, expected_arm):
        if before['view_id'] != after['view_id']:
            raise RuntimeError('Camera view changed during identity verification; repeat from the new view')
        metrics = {}
        sys.path.insert(0,str(self.args.pose_library))
        from mr_robot_desktop.skeleton import detect_skeletons
        for camera in ('wrist','external'):
            first = cv2.imread(before['images'][camera])
            second = cv2.imread(after['images'][camera])
            if camera=='wrist':
                first = cv2.rotate(first,cv2.ROTATE_180)
                second = cv2.rotate(second,cv2.ROTATE_180)
            gray = cv2.cvtColor(first,cv2.COLOR_BGR2GRAY)
            destination = cv2.cvtColor(second,cv2.COLOR_BGR2GRAY)
            scores = []
            for arm in detect_skeletons(first):
                mask = np.zeros(gray.shape,np.uint8)
                cv2.drawContours(mask,[np.array(arm['contour'],np.int32)],-1,255,-1)
                x,y,width,height = arm['box_xywh']
                mask[y+round(height*.75):] = 0
                points = cv2.goodFeaturesToTrack(gray,80,.02,5,mask=mask)
                if points is None:
                    scores.append(None)
                    continue
                moved,valid,_ = cv2.calcOpticalFlowPyrLK(gray,destination,points,None,winSize=(31,31),maxLevel=4)
                back,reverse,_ = cv2.calcOpticalFlowPyrLK(destination,gray,moved,None,winSize=(31,31),maxLevel=4)
                keep = valid.ravel().astype(bool)&reverse.ravel().astype(bool)
                keep &= np.linalg.norm((back-points).reshape(-1,2),axis=1)<1.5
                distance = np.linalg.norm((moved-points).reshape(-1,2)[keep],axis=1)
                scores.append(float(np.percentile(distance,75)) if len(distance)>=4 else None)
            verified = False
            if len(scores)==2 and all(value is not None for value in scores):
                target,other = scores[expected_arm-1],scores[2-expected_arm]
                verified = target>.35 and target>other*2+.15
            metrics[camera] = dict(p75_motion_pixels=scores,expected_arm=expected_arm,verified=verified)
        if not metrics['wrist']['verified']:
            raise RuntimeError('Single-arm motion did not verify the requested physical identity')
        return metrics

    def dance(self, cycle, amplitude):
        started = utc()
        a = amplitude
        raised1 = [307+a,287+a,297+a]
        raised2 = [307+a,307+a,307+a]
        sequence = [(raised1,raised2,'sync'),(REFERENCE[1],[307+2*a,307+2*a,307+2*a],'phase-A'),
                    (raised1,REFERENCE[2],'phase-B'),(REFERENCE[1],raised2,'phase-A-repeat'),
                    (REFERENCE[1],REFERENCE[2],'reference')]
        for first,second,label in sequence:
            self.move_small(first,second,'cycle%d-%s'%(cycle,label))
        metrics = self.quality(started)
        self.report['cycles'].append(dict(cycle=cycle,amplitude_counts=a,metrics=metrics))
        return metrics

    def run(self):
        self.event('experiment_started','开始本次实机演示，重置监控摘要。','Starting this physical demonstration; clearing previous summaries.')
        self.start()
        if self.args.phase in ('single','full'):
            for arm in (1,2):
                for joint,name in enumerate(('base','shoulder','elbow')):
                    first,second = list(REFERENCE[1]),list(REFERENCE[2])
                    (first if arm==1 else second)[joint] += 10
                    before = self.snapshot('mapping-%d-%s-before'%(arm,name))
                    after = self.move_small(first,second,'mapping-%d-%s'%(arm,name))
                    check = dict(arm=arm,joint=name,before=before,after=after,command_interface='PCA9685',
                                 channels={1:[12,13,14],2:[11,10,9]}[arm],
                                 optical_motion=self.verify_mapping(before,after,arm))
                    self.report['identity_checks'].append(check)
                    self.move_small(REFERENCE[1],REFERENCE[2],'mapping-%d-%s-return'%(arm,name))
        if self.args.phase in ('dance','full'):
            amplitude = self.args.amplitude
            for cycle in range(1,self.args.cycles+1):
                metrics = self.dance(cycle,amplitude)
                low_quality = metrics['lost'] or metrics['quality_p10']<.45
                model_bias = metrics['command_visual_rms_p90_px'] is not None and metrics['command_visual_rms_p90_px']>8
                if low_quality or model_bias:
                    changed = max(4,round(amplitude*.6))
                    self.event('interpretation','发现视觉质量或指令投影偏差，缩小下一轮幅度并复测。','Detected visual-quality or command-projection discrepancy; reducing amplitude for the next measured cycle.',before=metrics,new_amplitude=changed)
                    if low_quality:
                        self.move_observer([0,164,125],'reacquire-%d'%cycle)
                    amplitude = changed
        if self.args.phase in ('cruise','full'):
            stages = [('B-small',[-5,164,120],5),('C-small',[0,164,125],5),('A-return',[0,164,120],5),
                                       ('B-wide',[-10,164,120],5),('C-wide',[0,164,130],5),('A-wide-return',[0,164,120],5),
                                       ('B-repeat',[-10,164,120],7),('C-repeat',[0,164,125],7),('A-final',[0,164,120],7)]
            if self.args.cruise_stage=='small':
                stages = stages[:3]
            elif self.args.cruise_stage=='wide':
                stages = stages[3:6]
            elif self.args.cruise_stage=='repeat':
                stages = stages[6:]
            for label,target,speed in stages:
                self.move_observer(target,label,speed)
                if label in ('B-wide','C-wide','B-repeat','C-repeat'):
                    started = utc()
                    for arm in (1,2):
                        first,second = list(REFERENCE[1]),list(REFERENCE[2])
                        (first if arm==1 else second)[0] += 10
                        before = self.snapshot(label+'-identity-%d'%arm)
                        after = self.move_small(first,second,label+'-identity-%d-move'%arm)
                        self.report['identity_checks'].append(dict(arm=arm,joint='base',view_id=label,
                            optical_motion=self.verify_mapping(before,after,arm)))
                        self.move_small(REFERENCE[1],REFERENCE[2],label+'-identity-%d-return'%arm)
                    self.move_small([313,293,303],[313,313,313],label+'-same-sync-action')
                    self.move_small(REFERENCE[1],REFERENCE[2],label+'-sync-return')
                    self.report['views'][-1]['same_action_metrics'] = self.quality(started)
                    self.report['views'][-1]['planned_view_id'] = label
        self.report['ended_utc'] = utc()
        self.report['final_counts'] = self.small.rpc('d.status()')
        self.report['final_observer_command_target_mm'] = self.observer_target
        save_json(self.folder/'report.json',self.report)
        self.event('result','演示完成，已保留原始采集、动作与视觉日志。','Demo complete; raw samples, commands and vision logs were retained.',report=str(self.folder/'report.json'))

    def close(self):
        if self.pose:
            self.pose.stop.set()
            self.pose.thread.join(3)
        if self.video:
            self.video.stop.set()
        if self.small:
            self.small.close()
            shutil.copy2(self.small.path,self.folder/self.small.path.name)
        if self.uart:
            self.uart.deinit()
        self.events.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=('single','dance','cruise','full'),default='full')
    parser.add_argument('--cruise-stage',choices=('small','wide','repeat','all'),default='all')
    parser.add_argument('--small-port',default='COM8')
    parser.add_argument('--large-port',default='COM3')
    parser.add_argument('--camera',default='http://127.0.0.1:8768')
    parser.add_argument('--external',default='http://127.0.0.1:8769')
    parser.add_argument('--pose-library',type=Path,default=ROOT.parent/'Mr-Robot-Arm')
    parser.add_argument('--cycles',type=int,default=2)
    parser.add_argument('--amplitude',type=int,default=10)
    parser.add_argument('--speed',type=float,default=4)
    parser.add_argument('--output',type=Path,default=ROOT/'.runtime'/'demos'/datetime.now().strftime('%Y%m%d-%H%M%S'))
    args = parser.parse_args()
    if not (1 <= args.cycles <= 5 and 4 <= args.amplitude <= 10 and 2 <= args.speed <= 6):
        parser.error('cycles 1..5, amplitude 4..10 counts, speed 2..6 deg/s')
    demo = Demo(args)
    try:
        demo.run()
    except BaseException as error:
        demo.report.update(ended_utc=utc(),error=str(error),state='paused_no_new_commands')
        save_json(demo.folder/'report.json',demo.report)
        demo.event('error','演示暂停，停止新增动作。'+str(error),'Demo paused; no new motion commands. '+str(error))
        raise
    finally:
        demo.close()


if __name__=='__main__':
    main()
