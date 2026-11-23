"""Synchronize standalone MicroPython distribution copies."""
from pathlib import Path
from shutil import copyfile
if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    for source, targets in [("drivers/micropython/robot_arm.py", ["robot_arm.py", "code/robot_arm.py"]), ("examples/micropython/main.py", ["example.py", "code/main.py"])]:
        for target in targets: copyfile(root / source, root / target)
