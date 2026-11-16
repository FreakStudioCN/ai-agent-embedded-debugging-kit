"""MicroPython UART robot arm driver. Source: 串口通信指令.docx.

One command in flight; 'ok' acknowledges the command at the protocol level.
Live observation found motion continuing after 'ok'. Verify physical settling
separately before planning the next movement.
Constructing this object never sends commands or moves the arm.
"""

try:
    from time import ticks_ms, ticks_diff, sleep_ms
except ImportError:  # Allow protocol tests on CPython.
    from time import monotonic, sleep

    def ticks_ms():
        return int(monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

    def sleep_ms(ms):
        sleep(ms / 1000)


class ArmError(Exception):
    """Controller error, malformed response, or UART failure."""


class ArmTimeout(ArmError):
    """Execution state is unknown; do not blindly retry motion commands."""


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer")
    if value <= 0 or value > 100000000:
        raise ValueError(name + " must be in 1..100000000 ms")
    return value


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(name + " must be a number")
    if value != value or value == float("inf") or value == -float("inf"):
        raise ValueError(name + " must be finite")
    # Fixed point avoids scientific notation unsupported by the document.
    result = str(value) if isinstance(value, int) else ("%.6f" % value).rstrip("0").rstrip(".")
    return "0" if result == "-0" else result


class RobotArm:
    """Use an externally configured 115200/8N1 UART with read/write/any.

    UART should have timeout=0 and a small timeout_char to keep reads bounded.
    Not thread safe: one owner must use the UART and this instance.
    timeout_ms covers a command's transmission AND execution, not just receipt.
    """

    def __init__(self, uart, timeout_ms=30000, debug=False):
        for name in ("write", "read", "any"):
            if not callable(getattr(uart, name, None)):
                raise TypeError("uart must provide " + name + "()")
        self.timeout_ms = _positive_int(timeout_ms, "timeout_ms")
        self.uart = uart
        self.debug = debug
        self._rx = bytearray()
        self._pending = None
        self._fault = False
        self.last_response = None

    @property
    def pending(self):
        """Command awaiting acknowledgement, or None."""
        return self._pending

    def _log(self, direction, data):
        if self.debug:
            print("[ARM %s] %s" % (direction, data))

    def _read_line(self):
        # Firmware specifies 'ok' but does not specify a response terminator.
        # Accept exact bare 'ok' as well as CR, LF and CRLF terminated lines.
        for index, value in enumerate(self._rx):
            if value in (10, 13):
                line = bytes(self._rx[:index]).strip()
                del self._rx[:index + 1]
                return line
        if bytes(self._rx).strip().lower() == b"ok":
            line = bytes(self._rx).strip()
            self._rx = bytearray()
            return line
        return None

    def _receive(self):
        count = self.uart.any()
        if count:
            chunk = self.uart.read(min(count, 128))
            if chunk:
                self._rx.extend(chunk)
                if len(self._rx) > 1024:
                    raise ArmError("Response exceeds 1024 bytes; stream is unsynchronized")

    def _discard_available(self):
        """Discard only already available bytes, with a bounded drain."""
        self._rx = bytearray()
        for _ in range(32):
            count = self.uart.any()
            if not count:
                return
            if not self.uart.read(min(count, 128)):
                return
        raise ArmError("UART input remains busy; check controller output")

    def command(self, text, timeout_ms=None):
        """Send one ASCII G/M command and wait for acknowledgement; return 'ok'.

        No automatic retries. After a timeout, wait_done() can continue waiting
        for the SAME command. Never use a second instance to bypass this guard.
        """
        timeout = self.timeout_ms if timeout_ms is None else _positive_int(timeout_ms, "timeout_ms")
        if self._pending is not None or self._fault:
            raise ArmError("Previous command unresolved; use wait_done() or recover()")
        if not isinstance(text, str):
            raise TypeError("command must be a string")
        text = text.strip(" ").upper()
        if not text or len(text) > 256 or text[0] not in "GM":
            raise ValueError("Expected a single G/M command, at most 256 characters")
        if len(text) < 2 or text[1] not in "0123456789":
            raise ValueError("Command must begin with G/M followed by a number")
        if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .+-" for ch in text):
            raise ValueError("Only ASCII command characters allowed; no CR/LF injection")
        packet = (text + "\n").encode("ascii")
        try:
            self._discard_available()  # Startup logs / stale acknowledgements.
            self._pending = text
            self._log("TX", text)
            start = ticks_ms()
            offset = 0
            while offset < len(packet):
                if ticks_diff(ticks_ms(), start) >= timeout:
                    # Partial command may remain in the controller input buffer.
                    self._fault = True
                    raise ArmTimeout("UART write timed out; controller input may be partial")
                count = self.uart.write(packet[offset:])
                if count is not None and (not isinstance(count, int) or count < 0 or count > len(packet) - offset):
                    raise ArmError("Invalid UART write count")
                if count:
                    offset += count
                else:
                    sleep_ms(1)
            remaining = timeout - ticks_diff(ticks_ms(), start)
            if remaining <= 0:
                raise ArmTimeout("Command sent but execution deadline expired")
            return self.wait_done(remaining)
        except OSError as exc:
            self._fault = True
            raise ArmError("UART communication failed: %s" % exc)
        except ArmTimeout:
            raise
        except ArmError:
            self._fault = True
            raise

    def wait_done(self, timeout_ms=None):
        """Wait for acknowledgement; timeout leaves it pending, without resend."""
        timeout = self.timeout_ms if timeout_ms is None else _positive_int(timeout_ms, "timeout_ms")
        if self._fault:
            raise ArmError("UART/protocol fault; recover after checking controller state")
        if self._pending is None:
            return None
        start = ticks_ms()
        try:
            while ticks_diff(ticks_ms(), start) < timeout:
                self._receive()
                line = self._read_line()
                while line is not None:
                    if line:
                        self._log("RX", line)
                        self.last_response = line
                        if line.lower() == b"ok":
                            self._pending = None
                            return "ok"
                        # Error syntax is not specified. Recognize common forms
                        # defensively, but leave other controller logs alone.
                        if line.lower().startswith((b"error", b"err", b"alarm")):
                            raise ArmError("Controller response: %r" % line)
                    line = self._read_line()
                sleep_ms(1)
        except OSError as exc:
            self._fault = True
            raise ArmError("UART read failed: %s" % exc)
        except ArmError:
            self._fault = True
            raise
        raise ArmTimeout("No ok for %s; command may still execute; do not resend" % self._pending)

    def recover(self, controller_idle=False):
        """Clear local fault/pending state ONLY after external idle confirmation.

        Does not stop motion, reset hardware, or prove the controller is idle.
        After a partial write, reset/clear controller input externally first.
        Delayed old 'ok' cannot be correlated: protocol has no command IDs.
        """
        if controller_idle is not True:
            raise ValueError("Confirm controller idle and input cleared before recovery")
        try:
            self._discard_available()
        except OSError as exc:
            raise ArmError("UART recovery failed: %s" % exc)
        self._pending = None
        self._fault = False

    def move(self, x=None, y=None, z=None, speed=None, i=None, j=None,
             rapid=False, timeout_ms=None):
        """G1 (G0 if rapid): XYZ in mm, speed >=5 mm/s, I/J in degrees.

        Omitted axes are not transmitted. Travel/angle limits are firmware and
        hardware dependent; the document does not specify them. E is undefined.
        """
        fields = []
        for key, value in (("X", x), ("Y", y), ("Z", z), ("F", speed), ("I", i), ("J", j)):
            if value is not None:
                encoded = _number(value, key)
                if key == "F" and value < 5:
                    raise ValueError("speed must be at least 5 mm/s")
                fields.append(key + encoded)
        if not fields:
            raise ValueError("Specify at least one movement parameter")
        return self.command(("G0 " if rapid else "G1 ") + " ".join(fields), timeout_ms)

    def home(self, timeout_ms=None):
        return self.command("G28", timeout_ms)

    def dwell(self, seconds, timeout_ms=None):
        value = _number(seconds, "seconds")
        if seconds < 0:
            raise ValueError("seconds must be nonnegative")
        # Include device dwell time plus the normal communication margin.
        if timeout_ms is None:
            timeout_ms = _positive_int(int(seconds * 1000) + self.timeout_ms, "timeout_ms")
        return self.command("G4 S" + value, timeout_ms)

    def set_gripper_angles(self, i=None, j=None, timeout_ms=None):
        """I/J take effect immediately, even when combined with XYZ movement."""
        if i is None and j is None:
            raise ValueError("Specify i and/or j")
        return self.move(i=i, j=j, timeout_ms=timeout_ms)

    def close_gripper(self, timeout_ms=None):
        return self.command("M3", timeout_ms)

    def open_gripper(self, timeout_ms=None):
        return self.command("M5", timeout_ms)

    def enable_motors(self, timeout_ms=None):
        return self.command("M17", timeout_ms)

    def disable_motors(self, timeout_ms=None):
        return self.command("M18", timeout_ms)

    def set_io(self, channel, high, timeout_ms=None):
        if isinstance(channel, bool) or channel not in (1, 2):
            raise ValueError("IO channel must be 1 or 2")
        if high is not True and high is not False:
            raise TypeError("high must be bool")
        code = ("M1" if high else "M2") if channel == 1 else ("M6" if high else "M7")
        return self.command(code, timeout_ms)

    def set_output_12v(self, mode, timeout_ms=None):
        """Mode A/B/OFF: electrical meaning of A/B is unspecified."""
        if not isinstance(mode, str) or mode.upper() not in ("A", "B", "OFF"):
            raise ValueError("12V mode must be A, B or OFF")
        code = {"A": "M121", "B": "M122", "OFF": "M123"}[mode.upper()]
        return self.command(code, timeout_ms)
