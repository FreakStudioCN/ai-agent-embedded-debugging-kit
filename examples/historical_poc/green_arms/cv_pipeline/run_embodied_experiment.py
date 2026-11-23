"""Persistent, staged entry point for the explicitly authorized bench experiment.

Input JSON accepts a fixed list of phase operations, never arbitrary board code.
No automatic retry/reconnection or motion resume after a fault.
"""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time
import uuid
import argparse
from serial.tools import list_ports
from cv_pipeline.embodied_demo import MicroPythonSession
from cv_pipeline import experiment_phases
from cv_pipeline.operator_homing import OperatorHomingRunner
from experiment_safety import VIEWS

ROOT=_WORKSPACE_ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-run')
    parser.add_argument('--manual-view',choices=tuple(VIEWS))
    parser.add_argument('--manual-evidence',help='Exact current operator position confirmation; not inferred from images or motion authorization')
    parser.add_argument('--s1-confirmation',required=True,help='Exact NEW current-session human S0->S1 grant, supplied after preflight')
    parser.add_argument('--cause-resolved',required=True,help='Exact operator confirmation that the persisted fault cause is resolved')
    parser.add_argument('--clearance',required=True,help='Current people/cable/path clearance and physical power switch confirmation')
    parser.add_argument('--home-confirmation',help='Exact current operator request to execute normal homing; never automatic recovery')
    args=parser.parse_args()
    ports={p.device:p for p in list_ports.comports()}
    if 'COM8' not in ports or ports['COM8'].serial_number.lower()!='70:af:09:2a:ee:e8':
        raise RuntimeError('COM8 USB identity mismatch')
    run='experiment_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]
    out=ROOT/'.runtime'/run;out.mkdir();(out/'media').mkdir();(out/'plots').mkdir()
    def event(kind,**details):
        row=dict(schema_version='1.1',run_id=run,timestamp_utc=datetime.now(timezone.utc).isoformat(),
            parent_run_id=args.parent_run,monotonic_ms=time.monotonic_ns()/1e6,event=kind,motion_id=details.pop('motion_id',None),details=details)
        with (out/'experiment_events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
    session=MicroPythonSession('COM8')
    experiment_phases.RUN=OperatorHomingRunner(session,out,event,args.manual_view,args.manual_evidence,home_confirmation=args.home_confirmation,
        authorization=dict(operator_confirmation=args.s1_confirmation,cause_resolved=args.cause_resolved,
                           clearance=args.clearance,current_view_evidence=args.manual_evidence))
    (out/'continuation.json').write_text(json.dumps(dict(schema_version='1.0',run_id=run,parent_run_id=args.parent_run,
        ancestor_run_id='experiment_20261117T075459_750e71b2',phase_r_enabled=True,manual_view=args.manual_view,manual_evidence=args.manual_evidence),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    event('preflight',connection='COM8',transport=str(session.path),protocol='1.1',current_authorization=args.s1_confirmation)
    print(json.dumps(dict(ready=True,run_id=run,folder=str(out))),flush=True)
    try:
        for line in sys.stdin:
            a=json.loads(line);op=a.get('operation')
            if op not in ('prepare','activate','prepare_homing','home','activate_homed','views','phase1','phase2','phase3','close'):
                raise ValueError('Unsupported phase operation')
            if op in ('prepare_homing','home','activate_homed'):
                method={'prepare_homing':'prepare_homing','home':'operator_home','activate_homed':'activate_homed'}[op]
                result=getattr(experiment_phases.RUN,method)()
            else:result=experiment_phases.session_action(session,out,event,a)
            print(json.dumps(dict(operation=op,result=result),ensure_ascii=False,allow_nan=False),flush=True)
            if op=='close':break
    except BaseException as exc:
        experiment_phases.RUN.r.pause(str(exc),'main:'+str(exc))
        experiment_phases.RUN.gate.pause(exc)
        event('safety_pause',reason=repr(exc),new_commands_prohibited=True,release_requested=False)
        print(json.dumps(dict(error=repr(exc))),flush=True)
    finally:
        if experiment_phases.RUN:experiment_phases.RUN.close()
        session.close();(out/'com8_transport.jsonl').write_bytes(session.path.read_bytes())
        event('preflight',connection_closed=True,no_automatic_reconnect=True)


if __name__=='__main__':main()
