"""Read-only industrial input adapters; no GPIO allocation, IRQ or motion control.

Inputs must already be isolated/level converted to MCU-compatible logic.
No pin assignment or decoder throughput is assumed by this module.
"""

__version__ = '0.1.0'
__license__ = 'MIT'


def _reader(value, name):
    if value is not None and not callable(value):
        raise ValueError(name + ' must be callable or None')


class SwitchInputs:
    """Three SN04-P channels after input conditioning, sampled on read().

    Missing channels report None, never inactive. Callback returns 0/1.
    active_levels is mandatory: isolation/conditioning may invert polarity.
    PNP NO cannot by itself distinguish an inactive switch from a broken wire.
    This adapter does not debounce or interlock a motor; not ISR-safe.
    """

    def __init__(self, *, active_levels, center=None, minimum=None, maximum=None):
        if not isinstance(active_levels, (tuple, list)) or len(active_levels) != 3:
            raise ValueError('active_levels must contain center/minimum/maximum levels')
        for level in active_levels:
            if type(level) is not int or level not in (0, 1):
                raise ValueError('active levels must be integer 0 or 1')
        for value in (center, minimum, maximum):
            _reader(value, 'switch reader')
        self._readers = (center, minimum, maximum)
        self._levels = tuple(active_levels)

    def read(self):
        result = {}
        for name, reader, level in zip(('center', 'minimum', 'maximum'), self._readers, self._levels):
            if reader is None:
                result[name] = None
            else:
                value = reader()
                if type(value) not in (int, bool) or value not in (0, 1):
                    raise ValueError('switch reader must return a logic level')
                result[name] = value == level
        return result


class IncrementalEncoder:
    """HN3806-AB-600F adapter for an externally validated AB decoder.

    read_count returns an atomic signed integer count snapshot. decoding must
    explicitly be 1/2/4 edges per A-channel cycle, giving 600/1200/2400 counts
    per encoder revolution. No IRQ implementation or throughput guarantee.
    Counts are incremental and can have arbitrary startup origin. Encoder
    shaft rotation is not measured stage millimetres. Not ISR-safe.
    """

    def __init__(self, *, read_count=None, decoding=None, sign=1):
        _reader(read_count, 'read_count')
        if decoding is not None and (type(decoding) is not int or decoding not in (1, 2, 4)):
            raise ValueError('decoding must be 1, 2, 4 or None')
        if read_count is not None and decoding is None:
            raise ValueError('a connected decoder requires explicit decoding')
        if type(sign) is not int or sign not in (-1, 1):
            raise ValueError('sign must be -1 or 1')
        self._read_count = read_count
        self._decoding = decoding
        self._sign = sign

    def read(self):
        count = None
        if self._read_count is not None:
            count = self._read_count()
            if type(count) is not int:
                raise ValueError('decoder snapshot must be an integer')
            count *= self._sign
        cpr = 600 * self._decoding if self._decoding is not None else None
        return {'count': count, 'counts_per_rev': cpr,
                'shaft_turns_from_counter_origin': count / cpr if count is not None else None,
                'position_mm': None, 'absolute_position_known': False,
                'source': 'external_ab_decoder' if count is not None else 'unconfigured'}
