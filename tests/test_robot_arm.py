"""Host-side protocol tests; no hardware or third-party packages required."""
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from robot_arm import RobotArm, ArmError, ArmTimeout


class FakeUART:
    def __init__(self, response=(b"ok\r\n",), write_limit=999):
        self.response = response
        self.chunks = []
        self.tx = bytearray()
        self.packet = bytearray()
        self.write_limit = write_limit
        self.fail_write = False
        self.fail_read = False

    def any(self):
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, count):
        if self.fail_read:
            raise OSError("read failed")
        if not self.chunks:
            return None
        result = self.chunks[0][:count]
        self.chunks[0] = self.chunks[0][count:]
        if not self.chunks[0]:
            self.chunks.pop(0)
        return result

    def write(self, data):
        if self.fail_write:
            raise OSError("disconnected")
        data = bytes(data[:self.write_limit])
        self.tx.extend(data)
        self.packet.extend(data)
        if data.endswith(b"\n"):
            self.chunks.extend(self.response)
            self.packet.clear()
        return len(data)


class ProtocolTests(unittest.TestCase):
    def test_construction_sends_nothing(self):
        uart = FakeUART()
        RobotArm(uart)
        self.assertEqual(uart.tx, b"")

    def test_move_wire_format(self):
        uart = FakeUART()
        arm = RobotArm(uart)
        self.assertEqual(arm.move(x=-10.25, y=20, z=0, speed=5, i=90, j=45.5), "ok")
        self.assertEqual(uart.tx, b"G1 X-10.25 Y20 Z0 F5 I90 J45.5\n")
        arm.move(x=1, rapid=True)
        self.assertTrue(uart.tx.endswith(b"G0 X1\n"))

    def test_command_mapping(self):
        uart = FakeUART()
        arm = RobotArm(uart)
        for call, expected in (
            (lambda: arm.home(), b"G28\n"),
            (lambda: arm.dwell(0.25), b"G4 S0.25\n"),
            (lambda: arm.enable_motors(), b"M17\n"),
            (lambda: arm.disable_motors(), b"M18\n"),
            (lambda: arm.close_gripper(), b"M3\n"),
            (lambda: arm.open_gripper(), b"M5\n"),
            (lambda: arm.set_io(1, True), b"M1\n"),
            (lambda: arm.set_io(1, False), b"M2\n"),
            (lambda: arm.set_io(2, True), b"M6\n"),
            (lambda: arm.set_io(2, False), b"M7\n"),
            (lambda: arm.set_output_12v("a"), b"M121\n"),
            (lambda: arm.set_output_12v("B"), b"M122\n"),
            (lambda: arm.set_output_12v("OFF"), b"M123\n"),
            (lambda: arm.set_gripper_angles(j=45), b"G1 J45\n"),
        ):
            with self.subTest(expected=expected):
                uart.tx.clear()
                self.assertEqual(call(), "ok")
                self.assertEqual(uart.tx, expected)

    def test_fragmented_and_bare_reply(self):
        for reply in ((b"o", b"k\r", b"\n"), (b"ok",),
                      (b"boot\r\n", b"\r", b"OK\n"), (b"o", b"k")):
            with self.subTest(reply=reply):
                self.assertEqual(RobotArm(FakeUART(reply)).home(), "ok")

    def test_partial_writes(self):
        uart = FakeUART(write_limit=1)
        RobotArm(uart).move(x=12)
        self.assertEqual(uart.tx, b"G1 X12\n")

    def test_stale_ok_does_not_complete_new_command(self):
        uart = FakeUART(response=())
        uart.chunks = [b"ok\n"]
        arm = RobotArm(uart, timeout_ms=3)
        with self.assertRaises(ArmTimeout):
            arm.home()
        self.assertEqual(arm.pending, "G28")

    def test_timeout_then_late_reply_no_resend(self):
        uart = FakeUART(response=())
        arm = RobotArm(uart, timeout_ms=3)
        with self.assertRaises(ArmTimeout):
            arm.home()
        with self.assertRaises(ArmError):
            arm.home()
        self.assertEqual(uart.tx, b"G28\n")
        uart.chunks = [b"ok\n"]
        self.assertEqual(arm.wait_done(), "ok")
        self.assertIsNone(arm.pending)
        self.assertIsNone(arm.wait_done())

    def test_error_and_explicit_recovery(self):
        uart = FakeUART(response=(b"error: limit\n", b"ok\n"))
        arm = RobotArm(uart)
        with self.assertRaises(ArmError):
            arm.home()
        with self.assertRaises(ArmError):
            arm.wait_done()
        with self.assertRaises(ValueError):
            arm.recover()
        arm.recover(controller_idle=True)
        uart.response = (b"ok\n",)
        self.assertEqual(arm.home(), "ok")

    def test_write_failure_locks_driver(self):
        uart = FakeUART()
        uart.fail_write = True
        arm = RobotArm(uart)
        with self.assertRaises(ArmError):
            arm.home()
        with self.assertRaises(ArmError):
            arm.wait_done()

    def test_write_timeout_requires_recovery(self):
        arm = RobotArm(FakeUART(write_limit=0), timeout_ms=3)
        with self.assertRaises(ArmTimeout):
            arm.home()
        with self.assertRaises(ArmError):
            arm.wait_done()

    def test_read_failure(self):
        uart = FakeUART()
        uart.fail_read = True
        arm = RobotArm(uart)
        with self.assertRaisesRegex(ArmError, "UART read failed"):
            arm.home()

    def test_unterminated_noise_is_bounded(self):
        arm = RobotArm(FakeUART(response=(b"x" * 1100,)))
        with self.assertRaisesRegex(ArmError, "1024"):
            arm.home()

    def test_invalid_arguments_never_send(self):
        uart = FakeUART()
        arm = RobotArm(uart)
        for call in (
            lambda: arm.move(), lambda: arm.move(speed=4.99),
            lambda: arm.move(x=float("nan")), lambda: arm.move(x=float("inf")),
            lambda: arm.move(x=True), lambda: arm.move(x="1"),
            lambda: arm.dwell(-1), lambda: arm.set_io(3, True),
            lambda: arm.set_io(1, 1), lambda: arm.set_output_12v("C"),
            lambda: arm.set_gripper_angles(), lambda: arm.home(timeout_ms=0),
            lambda: arm.command("G28\nM18"), lambda: arm.command("G28\r"),
            lambda: arm.command("G28\x00"), lambda: arm.command("G"),
            lambda: arm.command("Gé"), lambda: arm.command(b"G28"),
        ):
            with self.subTest(call=call):
                with self.assertRaises((ValueError, TypeError)):
                    call()
                self.assertEqual(uart.tx, b"")

    def test_fixed_point(self):
        uart = FakeUART()
        RobotArm(uart).move(x=0.000001, y=-0.0)
        self.assertEqual(uart.tx, b"G1 X0.000001 Y0\n")

    def test_dwell_timeout_includes_delay(self):
        arm = RobotArm(FakeUART(), timeout_ms=30000)
        with patch.object(arm, "command", return_value="ok") as send:
            arm.dwell(40)
            send.assert_called_once_with("G4 S40", 70000)

    def test_ticks_wraparound(self):
        arm = RobotArm(FakeUART(response=()))
        arm._pending = "G28"
        with patch("robot_arm.ticks_ms", side_effect=[254, 255, 0, 1, 2]), \
             patch("robot_arm.ticks_diff", side_effect=lambda a, b: ((a - b + 128) % 256) - 128), \
             patch("robot_arm.sleep_ms"):
            with self.assertRaises(ArmTimeout):
                arm.wait_done(timeout_ms=4)


if __name__ == "__main__":
    unittest.main()
