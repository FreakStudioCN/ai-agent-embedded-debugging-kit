"""Run the MicroPython-compatible arm library on a PC using pyserial.

Default action: G4 S0 communication check. No MicroPython emulator required.
"""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import argparse
import sys
from time import sleep

import serial

from robot_arm import RobotArm, ArmError


class PCUART:
    """Minimal machine.UART-compatible adapter; does not own arm state."""

    def __init__(self, port="COM23", startup_delay=2.0):
        if not isinstance(startup_delay, (int, float)) or not 0 <= startup_delay <= 60:
            raise ValueError("startup_delay must be in 0..60 seconds")
        self.serial = serial.Serial(port=None, baudrate=115200, bytesize=8,
                                    parity="N", stopbits=1, timeout=0,
                                    write_timeout=1, xonxoff=False,
                                    rtscts=False, dsrdtr=False)
        # Set before opening to avoid deliberately asserting reset lines.
        # USB drivers may still transiently toggle these on open.
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        # The tested controller needs a settling interval after opening USB.
        # This only waits; no reset, motion or configuration command is sent.
        try:
            sleep(startup_delay)
        except BaseException:
            self.serial.close()
            raise

    def any(self):
        return self.serial.in_waiting

    def read(self, count):
        return self.serial.read(count)

    def write(self, data):
        return self.serial.write(data)

    def deinit(self):
        self.serial.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM23")
    parser.add_argument("--timeout", type=int, default=30000, help="Execution timeout in ms")
    parser.add_argument("--startup-delay", type=float, default=2.0, help="Wait after opening, in seconds")
    parser.add_argument("--command", help="One G/M command; can cause physical movement")
    args = parser.parse_args()
    uart = None
    try:
        uart = PCUART(args.port, startup_delay=args.startup_delay)
        arm = RobotArm(uart, timeout_ms=args.timeout, debug=True)
        print("Connected: %s, 115200 8N1" % args.port)
        if args.command is None:
            print("Communication check: G4 S0 (no motion requested)")
            arm.dwell(0, timeout_ms=args.timeout)
        else:
            arm.command(args.command, timeout_ms=args.timeout)
        print("PASS: controller replied ok; verify physical settling separately")
        return 0
    except (ArmError, serial.SerialException, ValueError) as exc:
        print("FAIL:", exc, file=sys.stderr)
        print("No automatic retry was performed.", file=sys.stderr)
        return 1
    finally:
        if uart is not None:
            uart.deinit()


if __name__ == "__main__":
    sys.exit(main())
