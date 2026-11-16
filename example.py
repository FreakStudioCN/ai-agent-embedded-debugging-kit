"""MicroPython ESP32 UART example. Set pins for YOUR board before running.

Importing this file sends nothing. Run main() explicitly to move the arm.
"""
from machine import UART, Pin
from robot_arm import RobotArm, ArmTimeout


def main():
    # Example pins only; change to match board wiring.
    uart = UART(1, baudrate=115200, bits=8, parity=None, stop=1,
                tx=Pin(17), rx=Pin(16), timeout=0, timeout_char=2)
    arm = RobotArm(uart, timeout_ms=60000, debug=True)
    try:
        arm.enable_motors()
        arm.home(timeout_ms=120000)
        # Enable only after choosing reachable coordinates / suitable angles:
        # arm.move(x=10, y=20, z=30, speed=10)
        # arm.set_gripper_angles(i=90, j=90)
        # arm.close_gripper()
        # arm.dwell(1)
        # arm.open_gripper()
        # arm.set_io(1, True)
        # arm.set_output_12v("A")
        # arm.set_output_12v("OFF")
    except ArmTimeout as exc:
        print("Unknown execution state:", exc)
        # Do not resend. Can call arm.wait_done(timeout_ms=120000) to wait
        # for this same command. Check controller state if it still times out.
        raise
    # No automatic M18: disabling motors can release a supported load.
