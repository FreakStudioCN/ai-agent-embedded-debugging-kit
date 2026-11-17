"""Construct the audited DualArm in the live session without enabling outputs."""
import ast
from pathlib import Path
from experiment_safety import SafetyError
from cv_pipeline.recovery_workflow import STATE,board_exec,registers,save


def session_action(session,out,event,args):
    if not STATE.get('frequency_restored'):raise SafetyError('Frequency not restored')
    if STATE.get('vision_paused'):raise SafetyError('Vision safety pause is latched')
    # A documentation-only difference is allowed; actual wiring must be identical.
    saved=(out/'board_backup/lib/mr_robot/dual_wiring.py').read_text(encoding='utf-8')
    assignments=[node for node in ast.parse(saved).body if isinstance(node,ast.Assign)]
    wiring=next(ast.literal_eval(n.value) for n in assignments if any(isinstance(t,ast.Name) and t.id=='ARM_CHANNELS' for t in n.targets))
    expected={1:dict(base=12,shoulder=13,elbow=14,gripper=15),2:dict(base=11,shoulder=10,elbow=9,gripper=8)}
    if wiring!=expected:raise SafetyError('Board wiring differs semantically')
    before=registers(session)
    if before['prescale']!=121 or any(v!=[0,0,0,16] for ch,v in before['pwm']):
        raise SafetyError('Read-only initialization requires50Hz and all16FULL OFF')
    state=board_exec(session,'from mr_robot.dual_arm import DualArm\nd=DualArm(pca)','d.status()')
    after=registers(session)
    if state['enabled'] or state['scheduled_busy'] or before!=after:
        raise SafetyError('Read-only construction unexpectedly changed hardware')
    STATE['dual_initialized']=True
    save(out,'dual_initialization.json',dict(state=state,pca_before=before,pca_after=after,outputs_changed=False,board_wiring_semantically_matches=True,
        source_difference='dual_wiring.py docstring differs; channel mapping identical',first_enable_speed_control_available=False))
    event('preflight',dual_constructed=True,enabled=False,all16_FULL_OFF=True,wiring_semantically_verified=True,awaiting_known_physical_initial_pose=True)
    return dict(state=state,all16_FULL_OFF=True,construction_wrote_pwm=False)
