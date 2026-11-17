"""Full orchestration smoke: real shared CV streams, FAKE serial and motors.

No serial.Serial/PCUART is instantiated. Recovery state is private to this
fixture. Simulated commands are logged as simulation, never physical success.
"""
from pathlib import Path
from datetime import datetime,timezone
import json
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cv_pipeline.operator_homing import OperatorHomingRunner


def main():
    parent=Path(sys.argv[1]);out=parent/('orchestration_smoke_'+datetime.now(timezone.utc).strftime('%H%M%S'))
    out.mkdir();(out/'media').mkdir();(out/'plots').mkdir();private=out/'private';private.mkdir()
    source=json.loads((parent/'preflight.json').read_text(encoding='utf-8'));fake_commands=[];fake_rpc=[]
    class Port:
        is_open=True;in_waiting=0
    class Session:
        port=Port();failed=False
        def rpc(self,expression,**kwargs):
            fake_rpc.append(expression)
            if 'unique_id' in expression:return source['uid']
            if expression=='d.status()':return source['dual_arm']
            if expression.startswith("{'address':pca.address"):return source['pca']
            if expression.startswith('d.confirm_settled'):return None
            raise AssertionError('Unexpected fake RPC: '+expression)
    class UART:
        def __init__(self,*a,**k):self.serial=Port()
        def any(self):return 0
        def deinit(self):self.serial.is_open=False
    class Driver:
        _fault=False
        def __init__(self,*a,**k):pass
        def command(self,command):fake_commands.append(command);return 'ok'
    def event(kind,**details):
        row=dict(schema_version='1.1',run_id=out.name,mode='REAL_CV_FAKE_ALL_MOTOR_TRANSPORTS',timestamp_utc=datetime.now(timezone.utc).isoformat(),
            monotonic_ms=time.monotonic_ns()/1e6,event=kind,motion_id=details.pop('motion_id',None),details=details)
        with (out/'experiment_events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
    grant=dict(operator_confirmation='SIMULATED FIXTURE ONLY',cause_resolved='SIMULATED',clearance='SIMULATED NO REAL MOTORS',current_view_evidence='SIMULATED HOME; live camera may be another physical view')
    with patch('phase_r_runner.ROOT',private),patch('phase_r_runner.PCUART',UART),patch('phase_r_runner.RobotArm',Driver):
        runner=OperatorHomingRunner(Session(),out,event,'HOME',grant['current_view_evidence'],authorization=grant)
        runner.summary=lambda kind,zh,en,**details:event(kind,text=zh,text_en=en,simulation=True,**details)
        results={}
        try:
            results['prepare']=runner.prepare();print('PREPARE_PASS',flush=True)
            results['activate']=runner.activate_after_keyframe_review();print('ACTIVATE_PASS',flush=True)
            runner.camera_to('A');results['rebase']=runner.r.snapshot();print('LEGAL_VIEW_REBASE_PASS',flush=True)
            if results['rebase']['state']!='NORMAL':raise AssertionError('No valid final recovery state')
            results['status']='PASS'
        except BaseException as exc:
            runner.r.pause('Smoke failure: '+str(exc));results.update(status='FAIL',error=repr(exc));raise
        finally:
            runner.close();results.update(real_motor_commands=0,fake_commands=fake_commands,fake_rpc=fake_rpc,
                limitation='Camera physically never moved; simulated target arrival validates orchestration, not physical view quality')
            (out/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(out=str(out),status=results['status'],real_motor_commands=0,fake_commands=fake_commands),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
