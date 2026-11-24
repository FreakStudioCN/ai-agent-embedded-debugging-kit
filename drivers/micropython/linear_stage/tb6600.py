"""Finite-pulse TB6600 bring-up driver; injected GPIO/RMT/time dependencies.

No position feedback, homing, millimetre motion or emergency stop is implied.
Call update() frequently. RMT submissions are finite batches, at most about 20ms at high rates.
"""

__version__ = '0.3.2'
__license__ = 'MIT'


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(name + ' out of range')
    return value


class TB6600:
    """Explicit enable polarity and total pulse budget required before GPIO writes."""

    MAX_MOVE_PULSES = 6400
    MAX_SESSION_PULSES = 12800

    def __init__(self, ena, direction, pulse, rmt, sleep_us, *,
                 enable_level, pulse_budget):
        self._enable_level = _integer(enable_level, 0, 1, 'enable_level')
        self._budget = _integer(pulse_budget, 1, self.MAX_SESSION_PULSES, 'pulse_budget')
        self._ena = ena
        self._direction = direction
        self._pulse = pulse
        self._rmt = rmt
        self._sleep_us = sleep_us
        self._state = 'idle'
        self._remaining = 0
        self._submitted = 0
        self._completed = 0
        self._active = False
        self._active_pulses = 0
        self._batch_size = 1
        self._durations = None
        self._ena.value(1 - self._enable_level)
        self._pulse.value(0)

    def start(self, pulses, direction_level, frequency_hz=100):
        """Accept a bounded request; first pulse is sent only by update()."""
        if self._state not in ('idle', 'completed', 'stopped'):
            raise RuntimeError('driver is busy, faulted or closed')
        _integer(pulses, 1, min(self._budget, self.MAX_MOVE_PULSES), 'pulses')
        _integer(direction_level, 0, 1, 'direction_level')
        _integer(frequency_hz, 50, 3200, 'frequency_hz')
        if pulses + self._submitted > self._budget:
            raise ValueError('session pulse budget exhausted')
        # RMT分辨率为1us，单脉冲高电平10us，其余时间为低电平。
        self._durations = (10, (1000000 + frequency_hz // 2) // frequency_hz - 10)
        self._batch_size = 1 if frequency_hz <= 200 else min(32, frequency_hz // 50)
        try:
            self._direction.value(direction_level)
            self._ena.value(self._enable_level)
            self._sleep_us(1000)
        except BaseException:
            self._state = 'fault'
            raise
        self._remaining = pulses
        self._state = 'accepted'

    def update(self):
        """Service completion then submit one finite batch. No busy wait."""
        if self._state not in ('accepted', 'running', 'stopping'):
            return self.status()
        try:
            if self._active:
                if not self._rmt.wait_done(timeout=0):
                    return self.status()
                self._active = False
                self._completed += self._active_pulses
                self._active_pulses = 0
            if self._state == 'stopping':
                self._remaining = 0
                self._state = 'stopped'
            elif self._remaining:
                # 先预占预算；调用异常时不能假定硬件未收到脉冲。
                self._active_pulses = min(self._batch_size, self._remaining)
                self._remaining -= self._active_pulses
                self._submitted += self._active_pulses
                self._active = True
                self._rmt.write_pulses(self._durations * self._active_pulses, 1)
                self._state = 'running'
            else:
                self._state = 'completed'
        except BaseException:
            self._state = 'fault'
            self._remaining = 0
            raise
        return self.status()

    def stop(self):
        """Stop scheduling pulses; retain holding torque. Poll until stopped; current finite batch is allowed to finish."""
        if self._state in ('accepted', 'running', 'stopping'):
            self._remaining = 0
            self._state = 'stopping'
            return self.update()
        return self.status()

    def status(self):
        return {'state': self._state, 'submitted_pulses': self._submitted,
                'completed_pulses': self._completed,
                'pulse_budget': self._budget, 'position_mm': None,
                'position_source': 'unknown', 'physical_motion_complete': None,
                'pulse_completion_source': 'rmt', 'pending_pulse': self._active}

    def deinit(self):
        """Release resources only when no pulse is pending; explicitly drops torque."""
        if self._state == 'closed':
            return
        if self._active:
            raise RuntimeError('stop and wait for pulse completion before deinit')
        try:
            self._rmt.deinit()
        finally:
            self._pulse.value(0)
            self._ena.value(1 - self._enable_level)
            self._state = 'closed'
