"""Offline stage calibration checks. No transport, discovery or motion commands."""
import argparse
import json
import math
from dataclasses import dataclass


def _number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name + ' must be a finite number')
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(name + ' must be finite' + (' and positive' if positive else ''))
    return value


@dataclass(frozen=True)
class AxisCalibration:
    """Explicit measured/configured inputs; motor revolutions per output revolution.

    mm_per_output_rev includes the screw lead or belt travel. Direction relates
    increasing pulse counts to the chosen positive coordinate. No encoder implied.
    """
    full_steps_per_motor_rev: int
    microsteps: int
    motor_revs_per_output_rev: float
    mm_per_output_rev: float
    direction: int
    minimum_mm: float
    maximum_mm: float

    def __post_init__(self):
        for name in ('full_steps_per_motor_rev', 'microsteps'):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(name + ' must be a positive integer')
        for name in ('motor_revs_per_output_rev', 'mm_per_output_rev'):
            _number(getattr(self, name), name, positive=True)
        if type(self.direction) is not int or self.direction not in (-1, 1):
            raise ValueError('direction must be -1 or 1')
        _number(self.minimum_mm, 'minimum_mm')
        _number(self.maximum_mm, 'maximum_mm')
        if self.minimum_mm >= self.maximum_mm:
            raise ValueError('minimum_mm must be below maximum_mm')
        _number(self.steps_per_mm, 'derived steps_per_mm', positive=True)

    @property
    def steps_per_mm(self):
        return (self.full_steps_per_motor_rev * self.microsteps *
                self.motor_revs_per_output_rev / self.mm_per_output_rev)

    def displacement_to_steps(self, mm):
        """Nearest pulse, ties away from zero. Displacement only, no origin claim."""
        count = _number(mm, 'displacement_mm') * self.steps_per_mm * self.direction
        _number(count, 'derived pulse count')
        return int(math.copysign(math.floor(abs(count) + 0.5), count))

    def steps_to_displacement(self, steps):
        if type(steps) is not int:
            raise ValueError('steps must be an integer')
        return steps * self.direction / self.steps_per_mm

    def check_target(self, target_mm):
        """Check both requested target and its quantized position against limits."""
        _number(target_mm, 'target_mm')
        if not self.minimum_mm <= target_mm <= self.maximum_mm:
            raise ValueError('target outside configured soft limits')
        quantized = self.steps_to_displacement(self.displacement_to_steps(target_mm))
        if not self.minimum_mm <= quantized <= self.maximum_mm:
            raise ValueError('quantized target outside configured soft limits')
        return quantized


def audit_profile(profile):
    """Report missing facts. A complete calibration is not authorization to move."""
    if not isinstance(profile, dict):
        raise ValueError('profile must be a JSON object')
    required = ('stage_model', 'motor_model', 'driver_model', 'controller_model',
                'connection', 'protocol_reference', 'wiring_reference',
                'transmission', 'positive_direction_definition',
                'limit_switches', 'encoder', 'controller_topology')
    missing = [key for key in required if profile.get(key) in (None, '', 'unknown')]
    calibration = profile.get('calibration')
    errors = []
    parsed = None
    if not isinstance(calibration, dict):
        missing.append('calibration')
    else:
        missing.extend('calibration.' + key for key in AxisCalibration.__dataclass_fields__
                       if calibration.get(key) is None)
        if not any(key.startswith('calibration.') for key in missing):
            try:
                parsed = AxisCalibration(**calibration)
            except (ValueError, TypeError, OverflowError) as exc:
                errors.append(str(exc))
    return {'missing': missing, 'errors': errors,
            'steps_per_mm': parsed.steps_per_mm if parsed else None,
            'hardware_verified': False, 'motion_available': False,
            'position_source': 'none'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', help='JSON hardware inventory; never opens a port')
    args = parser.parse_args(argv)
    try:
        with open(args.profile, encoding='utf-8') as stream:
            report = audit_profile(json.load(stream))
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report['missing'] or report['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
