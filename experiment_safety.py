"""Additional restrictions for the v1 embodied experiment; no hardware I/O.

This is an admission layer above the existing drivers, not an emergency stop.
Paths are restricted to documented segments inside the existing convex envelope.
Hardware faults retain their original driver policy; recoverable host faults
freeze admission and leave the last PWM setpoint in place, never home/release.
"""
import math
import time

REFERENCE = {1: (307, 287, 297), 2: (307, 307, 307)}
WINDOWS = {1: ((307, 327), (287, 307), (297, 317)),
           2: ((297, 357), (297, 337), (297, 337))}
VIEWS = {'A': (0, 164, 120), 'B-small': (-5, 164, 120),
         'C-small': (0, 164, 125), 'B-wide': (-10, 164, 120),
         'C-wide': (0, 164, 130)}
# Bootstrap only: nominal post-G28 reference in pinned upstream config.h.
# Home -> A was executed and visually verified in the 2026-11-17 UART/event logs.
VIEWS['HOME'] = (0, 174, 120)
# Exact previously executed consecutive segments, reversible along the same line.
EDGES = (('A', 'B-small'), ('B-small', 'C-small'), ('C-small', 'A'),
         ('A', 'B-wide'), ('B-wide', 'C-wide'), ('C-wide', 'A'),
         ('B-wide', 'C-small'), ('HOME', 'A'))


class SafetyError(RuntimeError):
    pass


def vector(value, length=3, integral=False):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise SafetyError('Wrong coordinate dimension')
    if any(type(x) not in ((int,) if integral else (int, float)) or
           not math.isfinite(x) for x in value):
        raise SafetyError('Coordinates must be finite numbers of the required type')
    return tuple(value)


def finite_speed(speed, low, high):
    if type(speed) not in (int, float) or not math.isfinite(speed) or not low <= speed <= high:
        raise SafetyError('Speed outside the existing restricted range')


class ExperimentGate:
    """Per-connection permit, latched pause, bounded single-joint steps and budget.

    5 counts is the smaller repeatedly documented joint increment. Observer
    subsegments are at most 5 mm, F5, within documented lines only. No changes
    to driver/PCA limits. Each action needs separate physical-settle evidence.
    """
    def __init__(self, connection_id, clock=time.monotonic):
        self.connection_id = connection_id
        self.clock = clock
        self.authorized = False
        self.paused = False
        self.pending = None
        self.completed = 0
        self.started = None
        self.last_completed = None
        self.max_actions = 240
        self.max_seconds = 1800
        self.min_interval_s = 2.0
        self.max_counts_step = 5
        self.max_observer_mm = 5.0
        self.recovery_guard = None

    def authorize(self, connection_id, operator_confirmation):
        if self.paused or connection_id != self.connection_id or not operator_confirmation:
            raise SafetyError('New connection or paused session needs explicit renewed authorization')
        self.authorized = True
        self.started = self.clock()

    def pause(self, reason):
        self.paused = True
        self.authorized = False
        self.pause_reason = str(reason)
        # Keep pending for diagnosis. Never send release or an automatic return.

    def admit(self,kind='generic',origin=None,target=None):
        if not self.authorized or self.paused or self.pending is not None:
            raise SafetyError('Motion gate closed or previous physical completion unresolved')
        if self.completed >= self.max_actions or self.clock()-self.started >= self.max_seconds:
            self.pause('Experiment budget exhausted')
            raise SafetyError(self.pause_reason)
        if self.last_completed is not None and self.clock()-self.last_completed < self.min_interval_s:
            raise SafetyError('Minimum physical-settle-to-next-command interval not met')
        if self.recovery_guard is not None:
            self.recovery_guard.require_motion_allowed(kind,origin,target)

    def green_path(self, origins, targets, joint=2, speed=2):
        self.admit()
        finite_speed(speed, 2, 6)
        if type(joint) is not int or joint not in (1, 2):
            raise SafetyError('Only green_2 shoulder or elbow may move')
        for arm in (1, 2):
            start = vector(origins[arm], integral=True)
            end = vector(targets[arm], integral=True)
            for j, ((low, high), a, b) in enumerate(zip(WINDOWS[arm], start, end)):
                if not low <= a <= high or not low <= b <= high:
                    raise SafetyError('Origin or target outside immutable PWM window')
                if (arm, j) != (2, joint) and (a != REFERENCE[arm][j] or b != a):
                    raise SafetyError('Nonexperimental joint must stay at its verified reference')
                if abs(b-a) > self.max_counts_step:
                    raise SafetyError('Single PWM increment exceeds 5 counts')
                # Monotone smoothstep interpolates in [a,b]; check that whole interval.
                if min(a,b) < low or max(a,b) > high:
                    raise SafetyError('PWM path leaves the immutable interval')
        return True

    def observer_path(self, origin, target, edge, speed=5):
        self.admit(kind='observer',origin=origin,target=target)
        finite_speed(speed, 5, 5)
        a, b = vector(origin), vector(target)
        if math.dist(a, b) > self.max_observer_mm+1e-9:
            raise SafetyError('Observer subsegment exceeds 5 mm')
        if edge not in EDGES and edge[::-1] not in EDGES:
            raise SafetyError('Unverified camera-view edge')
        start, end = VIEWS[edge[0]], VIEWS[edge[1]]
        delta = tuple(y-x for x,y in zip(start,end))
        denom = sum(x*x for x in delta)
        for point in (a,b):
            fraction = sum((x-y)*d for x,y,d in zip(point,start,delta))/denom
            projected = tuple(x+fraction*d for x,d in zip(start,delta))
            if not -1e-9 <= fraction <= 1+1e-9 or math.dist(point,projected)>1e-7:
                raise SafetyError('Point is not on the documented path segment')
        # The workspace is a convex box: valid endpoints prove the entire line
        # lies inside it. This does not prove absence of physical obstacles.
        for point in (a,b):
            if not (-10<=point[0]<=0 and 164<=point[1]<=174 and 120<=point[2]<=130):
                raise SafetyError('Path leaves the original observer envelope')
        return True

    def begin(self, motion_id,kind='generic',origin=None,target=None):
        self.admit(kind,origin,target)
        self.pending = motion_id

    def finish(self, motion_id, fresh_evidence):
        if self.pending != motion_id or not fresh_evidence or self.paused:
            raise SafetyError('Cannot mark physical completion without fresh evidence')
        self.pending = None
        self.completed += 1
        self.last_completed = self.clock()


class SafeExecutor:
    """Wrap existing RPC/observer operations without changing their safety limits.

    Requires fresh prepared state and hardware identity checks before creation.
    `measure` returns a protocol-compliant stationary window or raises. Holding
    on a host fault means preserving the last emitted PWM target, NOT guessing
    a return-to-reference trajectory. Loss of communication cannot ensure that
    an already-started on-board segment stops immediately.
    """
    def __init__(self, gate, rpc, emit, counts, joint=2):
        self.gate, self.rpc, self.emit = gate, rpc, emit
        self.counts = {arm:tuple(counts[arm]) for arm in (1,2)}
        self.joint = joint

    @staticmethod
    def check_hardware(uid, pca, state):
        if uid != '70af092aeee8' or pca['address'] != 0x4F:
            raise SafetyError('Controller/PCA identity mismatch')
        if pca['prescale'] != 121 or pca['mode1'] & 0x30 != 0x20:
            raise SafetyError('PCA must already be configured awake at prescale 121; no automatic correction')
        if pca['i2c'] != 'I2C(0, scl=9, sda=10, freq=400000, timeout=50000)':
            raise SafetyError('I2C configuration differs from the verified board')
        registers = dict(pca['pwm'])
        if set(registers) != set(range(16)):
            raise SafetyError('Incomplete PCA readback')
        if any(registers[ch] != [0,0,0,16] for ch in (*range(9),15)):
            raise SafetyError('Chassis/gripper outputs must already be FULL OFF')
        if not state['enabled'] or state['scheduled_busy']:
            raise SafetyError('Prepared enabled, idle DualArm required')
        counts=state['command_counts']
        for arm,channels in ((1,(12,13,14)),(2,(11,10,9))):
            values=counts.get(arm,counts.get(str(arm)))
            if tuple(values) != REFERENCE[arm]:
                raise SafetyError('Fresh verified reference command required')
            for value,ch in zip(values,channels):
                if registers[ch] != [0,0,value&255,value>>8]:
                    raise SafetyError('PCA registers disagree with command state')
        return True

    def _fault(self, error, motion_id):
        self.gate.pause(error)
        self.emit('safety_pause', motion_id=motion_id, reason=str(error),
                  response='hold_last_output_no_new_commands',
                  automatic_return=False, release_requested=False,
                  physical_stop_guaranteed=False)

    def green(self, targets, motion_id, measure, speed=2):
        details=dict(motion_id=motion_id,device='COM8',joint=('shoulder' if self.joint==1 else 'elbow'),
                     channel=10 if self.joint==1 else 9,start_counts=self.counts,
                     target_counts=targets,speed_deg_s=speed,parameter_version='safety-v1')
        self.emit('move_requested',**details)
        try:
            self.gate.green_path(self.counts,targets,self.joint,speed)
            self.emit('move_accepted',**details)
            self.gate.begin(motion_id)
            self.emit('move_started',**details)
            state=self.rpc('d.run_segment(%r,%r,speed=%r)'%(tuple(targets[1]),tuple(targets[2]),speed))
            if state['scheduled_busy'] or not state['enabled']:
                raise SafetyError('Board did not confirm enabled/idle trajectory completion')
            actual=state['command_counts']
            if any(tuple(actual.get(arm,actual.get(str(arm)))) != tuple(targets[arm]) for arm in (1,2)):
                raise SafetyError('Board returned unexpected command counts')
            evidence=measure(motion_id)
            if not isinstance(evidence,dict) or not evidence.get('stationary') or not evidence.get('evidence_path'):
                raise SafetyError('No valid fresh stationary measurement')
            self.rpc('d.confirm_settled(%r)'%evidence['evidence_path'])
            self.gate.finish(motion_id,evidence)
            self.counts={arm:tuple(targets[arm]) for arm in (1,2)}
            self.emit('move_completed',**details,evidence=evidence)
            return evidence
        except BaseException as error:
            if self.gate.pending is None:
                self.emit('move_rejected',**details,reason=str(error))
            if isinstance(error,TimeoutError):
                self.emit('move_timeout',**details,reason=str(error))
            self._fault(error,motion_id)
            raise

    def observer(self, origin, target, edge, motion_id, existing_move, speed=5):
        """existing_move must retain the original driver + settling checks."""
        details=dict(motion_id=motion_id,device='COM3',origin=origin,target=target,edge=edge,speed_mm_s=speed)
        self.emit('move_requested',**details)
        try:
            self.gate.observer_path(origin,target,edge,speed)
            self.emit('move_accepted',**details)
            self.gate.begin(motion_id)
            self.emit('camera_move_started',**details)
            evidence=existing_move(target,motion_id,speed)
            if not isinstance(evidence,dict) or not evidence.get('stationary') or not evidence.get('evidence_path'):
                raise SafetyError('Observer physical settling evidence missing')
            self.gate.finish(motion_id,evidence)
            self.emit('camera_move_completed',**details,evidence=evidence)
            return evidence
        except BaseException as error:
            self._fault(error,motion_id)
            raise
