"""Explicit bounded 300rpm-request experiment; no motion on import.

Not a new TB6600 library speed guarantee. Call run only with checked clearance.
Finite 32-pulse batches keep interruption bounded to the current batch.
"""


def make_profile(pulses=3200):
    """800..32000 pulses, 400-pulse ramps, 10us HIGH, peak period 63us."""
    if type(pulses) is not int or not 800 <= pulses <= 32000:
        raise ValueError('pulses must be an integer in 800..32000')
    ramp = tuple(625 - (562 * i // 399) for i in range(400))
    periods = ramp + (63,) * (pulses - 800) + tuple(ramp[i] for i in range(399, -1, -1))
    return tuple(duration for period in periods for duration in (10, period - 10))


def run(direction_level=0, pulses=3200):
    """Run once, retain ENA low on exit; completed count is RMT evidence only."""
    if type(direction_level) is not int or direction_level not in (0, 1):
        raise ValueError('direction_level must be 0 or 1')
    import time
    import gc
    from machine import Pin
    from esp32 import RMT
    waveform = make_profile(pulses)
    batches = tuple(waveform[i:i + 64] for i in range(0, len(waveform), 64))
    gc.collect()
    pulse = Pin(3, Pin.OUT, value=0)
    ena = Pin(1, Pin.OUT, value=0)
    direction = Pin(2, Pin.OUT, value=direction_level)
    rmt = RMT(0, pin=pulse, clock_div=80, idle_level=0)
    submitted = completed = 0
    pending = False
    print('REQUEST_300_RPM', 'direction', direction_level, 'pulses', pulses,
          'peak_period_us', 63, 'programmed_us', sum(waveform))
    began = time.ticks_ms()
    try:
        time.sleep_us(1000)
        for batch in batches:
            # 发生发送异常时保留在途状态，不假定没有产生脉冲。
            pending = True
            submitted += len(batch) // 2
            rmt.write_pulses(batch, 1)
            wait_start = time.ticks_ms()
            while not rmt.wait_done(timeout=0):
                if time.ticks_diff(time.ticks_ms(), wait_start) > 100:
                    raise RuntimeError('batch timeout; no retry')
                time.sleep_us(20)
            pending = False
            completed += len(batch) // 2
        print('TRAIN_DONE', 'submitted', submitted, 'rmt_completed', completed,
              'elapsed_ms', time.ticks_diff(time.ticks_ms(), began))
    finally:
        # 无后续提交；最多等待当前有限批次。异常状态不能当作机械停稳。
        idle = rmt.wait_done(timeout=50)
        if idle:
            rmt.deinit()
            pulse.init(Pin.OUT, value=0)
        ena.value(0)
        print('FINAL', 'rmt_idle', idle, 'ENA', ena.value(),
              'submitted', submitted, 'completed_confirmed', completed,
              'physical_position', 'unknown')


if __name__ == '__main__':
    run(0)
