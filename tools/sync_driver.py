"""Refresh standalone legacy copies from maintained code/ sources."""
from pathlib import Path
from shutil import copyfile


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    copyfile(root / "code" / "robot_arm.py", root / "robot_arm.py")
    copyfile(root / "code" / "main.py", root / "example.py")
