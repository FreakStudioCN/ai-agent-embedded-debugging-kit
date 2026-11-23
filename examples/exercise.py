"""Manual bounded exercise. Importing performs no hardware operation."""
import asyncio
import time


async def exercise(stage, pulses, direction_level, *, stop_after_ms=None):
    if stop_after_ms is not None:
        if type(stop_after_ms) is not int or not 0 <= stop_after_ms <= 1000:
            raise ValueError('stop_after_ms must be 0..1000 or None')
    started = time.ticks_ms()
    stage.start(pulses, direction_level, 100)
    try:
        while True:
            if stop_after_ms is not None and time.ticks_diff(time.ticks_ms(), started) >= stop_after_ms:
                stage.stop()
            status = stage.update()
            if status['state'] in ('completed', 'stopped'):
                return status
            if time.ticks_diff(time.ticks_ms(), started) > pulses * 30 + 2000:
                raise RuntimeError('pulse completion timeout; physical result unknown')
            await asyncio.sleep_ms(1)
    finally:
        stage.stop()
        # 停止后等待当前单脉冲结束，不禁用保持力，不自动重试。
        for _ in range(100):
            if not stage.update()['pending_pulse']:
                break
            await asyncio.sleep_ms(1)
