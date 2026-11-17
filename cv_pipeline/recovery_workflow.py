"""Explicit, operator-authorized recovery steps on a single live COM8 session."""
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import time
from urllib.request import urlopen

from PIL import Image
import cv2
import numpy as np
from experiment_safety import REFERENCE, SafeExecutor, SafetyError

ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT.parent/'Mr-Robot-Arm'
STATE={}


def save(out,name,data):
    (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def registers(session):
    return session.rpc("{'address':pca.address,'i2c':repr(pca.i2c),'mode1':pca.i2c.readfrom_mem(0x4f,0,1)[0],'prescale':pca.i2c.readfrom_mem(0x4f,254,1)[0],'pwm':[(ch,list(pca.i2c.readfrom_mem(0x4f,6+4*ch,4))) for ch in range(16)]}")


def snapshots(out,label,event):
    result={}
    for cid,port,rotation in [('wrist_8768',8768,180),('global_8769',8769,0)]:
        base='http://127.0.0.1:'+str(port)
        with urlopen(base+'/api/status',timeout=3) as r:status=json.load(r)
        if not status['healthy'] or status['frame_age_seconds'] is None or status['frame_age_seconds']>1:
            raise SafetyError('Camera unavailable: '+cid)
        with urlopen(base+'/snapshot.jpg',timeout=3) as r:
            data=r.read();frame=r.headers.get('X-Frame-Id')
        image=Image.open(BytesIO(data)).convert('RGB')
        if image.size!=(1280,720):raise SafetyError('Camera dimensions changed')
        path=out/'media'/(label+'-'+cid+'.jpg')
        if rotation:image=image.transpose(Image.Transpose.ROTATE_180)
        image.save(path,quality=95)
        result[cid]=dict(path=str(path),frame_id=frame,status=status,rotation=rotation,received_monotonic=time.monotonic())
    save(out,label+'-camera.json',result)
    event('preflight',sample=label,cameras=result)
    return result


def board_exec(session,source,result='True'):
    return session.rpc('(exec(%r), %s)[1]'%(source,result))


def session_action(session,out,event,args):
    action=args['operation']
    if action=='inspect':
        uid=session.rpc("__import__('machine').unique_id().hex()")
        if uid!='70af092aeee8':raise SafetyError('Chip UID mismatch')
        # Use existing board object or read-only creation with reset=False only.
        have=session.rpc("'pca' in globals()")
        if not have:raise SafetyError('Expected prior PCA object absent; inspect before creating hardware objects')
        sources={}
        for name in ['main.py','lib/mr_robot/dual_arm.py','lib/mr_robot/dual_wiring.py','lib/mr_robot/servo_controller.py','lib/mr_robot/pca9685.py','lib/pca9685.py']:
            source=session.rpc('open(%r).read()'%('/'+name))
            dest=out/'board_backup'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(source.encode('utf-8'))
            compare=LIB/Path(name).relative_to('lib') if name.startswith('lib/mr_robot/') else None
            sources[name]=dict(sha256=hashlib.sha256(source.encode()).hexdigest(),path=str(dest),
                matches_local=(source.replace('\r\n','\n').strip()==compare.read_text(encoding='utf-8').replace('\r\n','\n').strip()) if compare else None)
        readback=registers(session)
        photos=snapshots(out,'pre-recovery',event)
        STATE.update(uid=uid,sources=sources,initial=readback,before=photos)
        save(out,'recovery_preflight.json',dict(uid=uid,sources=sources,pca=readback))
        event('preflight',uid=uid,source_versions=sources,pca=readback)
        return dict(uid=uid,pca=readback,sources=sources,frames=photos)
    if action=='backup_boot':
        if not STATE.get('uid'):raise SafetyError('Preflight not performed')
        # Compare hashes of the exact board readback, not host newline-normalized
        # text. If a previous attempt finished writing, verify without rewriting.
        original_sha='16faa88415a754cc831ec6feb5c33e7bcdf19d51e2fb2997daaf383681c71348'
        exists=session.rpc("'main_chassis_bak.py' in __import__('os').listdir('/')")
        if not exists:
            original=session.rpc("open('/main.py').read()")
            if hashlib.sha256(original.encode()).hexdigest()!=original_sha:
                raise SafetyError('Original startup changed; refusing to replace')
            board_exec(session,"__import__('os').rename('/main.py','/main_chassis_bak.py')")
        proposed=(ROOT/'.runtime/embodied_20261117T072704_5fc9caaf/proposed_board_main.py').read_text(encoding='utf-8')
        if not exists:
            board_exec(session,"with open('/main.py','w') as _boot:\n _boot.write(%r)"%proposed)
        restored=session.rpc("{'backup':open('/main_chassis_bak.py').read(),'main':open('/main.py').read()}")
        if hashlib.sha256(restored['backup'].encode()).hexdigest()!=original_sha or restored['main']!=proposed:
            raise SafetyError('Board backup/startup readback mismatch')
        STATE['boot_replaced']=True
        save(out,'boot_replacement.json',dict(backup='/main_chassis_bak.py',verified=True,original_sha256=original_sha,new_sha256=hashlib.sha256(proposed.encode()).hexdigest()))
        event('parameter_applied',scope='operator_authorized_boot_recovery',backup='/main_chassis_bak.py',verified=True,reset_executed=False)
        return dict(backup_verified=True,passive_boot_verified=True,reset_executed=False)
    if action=='frequency':
        if not STATE.get('boot_replaced'):raise SafetyError('Boot backup/replacement required first')
        event('move_requested',device='COM8/PCA',recovery='all_channels_FULL_OFF_then_50Hz',operator_explicitly_authorized_all16=True)
        # User explicitly authorized disabling all16 prior to changing frequency.
        board_exec(session,'for _ch in range(16):\n pca.pwm(_ch,0,4096)')
        off=registers(session)
        if any(values!=[0,0,0,16] for ch,values in off['pwm']):
            raise SafetyError('All16 FULL OFF check failed; frequency unchanged')
        event('preflight',all16_FULL_OFF_verified=True,registers=off)
        session.rpc('pca.freq(50)')
        after=registers(session)
        if after['prescale']!=121 or any(v!=[0,0,0,16] for ch,v in after['pwm']):
            raise SafetyError('Frequency restore/readback failed')
        STATE['frequency_restored']=True
        photos=snapshots(out,'all-off-50Hz',event)
        STATE['all_off_frames']=photos
        save(out,'frequency_recovery.json',dict(before=STATE['initial'],all_off_before_frequency=off,after=after,frames=photos))
        event('parameter_applied',scope='operator_authorized_frequency_recovery',old_prescale=off['prescale'],new_prescale=121,all16_remain_FULL_OFF=True)
        return dict(prescale=121,all16_FULL_OFF=True,frames=photos)
    if action=='cv_probe':
        if not STATE.get('frequency_restored'):raise SafetyError('Frequency must be restored first')
        from cv_pipeline.experiment_cv import CVStream
        cv=CVStream(out,event);STATE['cv']=cv
        start=time.monotonic();cv.start()
        # Read-only startup diagnostic: no permission to move based on these
        # samples until actual reference acquisition has independently succeeded.
        end=start+12
        while time.monotonic()<end:time.sleep(.1)
        stats=cv.stats(start)
        result=dict(purpose='all-off pre-enable visual feasibility, NOT reference baseline',statistics=stats,
                    fault=cv.failure,duration_s=time.monotonic()-start,reference_pose_verified=False)
        save(out,'all_off_cv_probe.json',result)
        if cv.failure:
            STATE['vision_paused']=True
            event('safety_pause',reason=cv.failure,no_new_motion=True,stage='pre-enable read-only CV probe')
        cv.close()
        return result
    raise ValueError('Unknown recovery operation')
