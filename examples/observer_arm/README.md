# Observer arm examples

Start with `python -m host_control.session --help`. For an actual connected arm use `python -m host_control.session --port YOUR_PORT`; `G4 S0` is the communication check. `:snapshot` captures a frame. Motion, homing and gripper commands require the task authorization and physical-state checks in the [Skill](../../.agents/skills/robot-arm-control/SKILL.md). No example is automatically run at import.
