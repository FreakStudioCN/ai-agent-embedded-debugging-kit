"""Explicit REPL factory. Importing this file does not configure GPIO or move."""


ENABLE_LEVEL = 0


def create(*, pulse_budget, enable_level=ENABLE_LEVEL):
    """Only call after wiring, ENA polarity, clearance and pulse budget are checked."""
    from machine import Pin
    from esp32 import RMT
    from time import sleep_us
    from tb6600 import TB6600

    if type(enable_level) is not int or enable_level != ENABLE_LEVEL:
        raise ValueError('this board requires active-low ENA (enable_level=0)')
    if type(pulse_budget) is not int or not 1 <= pulse_budget <= TB6600.MAX_SESSION_PULSES:
        raise ValueError('pulse_budget must be 1..12800')
    ena = Pin(1, Pin.OUT, value=1 - enable_level)
    direction = Pin(2, Pin.OUT, value=0)
    pulse = Pin(3, Pin.OUT, value=0)
    rmt = RMT(0, pin=pulse, clock_div=80, idle_level=0)
    try:
        return TB6600(ena, direction, pulse, rmt, sleep_us,
                      enable_level=enable_level, pulse_budget=pulse_budget)
    except BaseException:
        rmt.deinit()
        ena.value(1 - enable_level)
        raise
