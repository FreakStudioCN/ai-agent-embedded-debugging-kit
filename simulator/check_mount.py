"""Check actual wrist/gripper STL intersections using trimesh and manifold3d.

Run with Python after installing these two check-only packages. The local
temporary package directory is also supported. Browser runtime is unaffected.
"""
import json
import os
from pathlib import Path
import re
import sys
import warnings

sys.path.insert(0, str(Path(os.environ.get("TEMP", "/tmp")) / "robot-mesh-check"))
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "custom_gripper"
manifest = json.loads((MODEL / "model.json").read_text(encoding="utf-8"))
p = manifest["parameters"]
config_source = (ROOT / "kinematics.mjs").read_text(encoding="utf-8")
offset = [float(re.search(r"gripperMount" + axis + r":\s*([-\d.]+)", config_source)[1])
          for axis in ["X", "Z"]]
basis_source = (ROOT / "gripper-kinematics.mjs").read_text(encoding="utf-8")
basis = re.search(r"GRIPPER_MOUNT_BASIS = Object.freeze\((\[[\s\S]*?\])\);", basis_source)[1]
basis = json.loads(re.sub(r",\s*\]", "]", basis))
mount = np.eye(4)
mount[:3, :3] = np.array(basis).T
mount[:3, 3] = [offset[0], 0, offset[1]]
wrist = trimesh.load_mesh(ROOT / "../mechanical/upstream/community_robot_arm/CAD Files/robot_belt_arm manipulator.stl")
wrist.apply_translation([-119.5386, 49, -196.3517])
assert wrist.is_volume, "Wrist STL must be a closed positive-volume mesh"
geometries = {key: trimesh.load_mesh(MODEL / path) for key, path in manifest["geometry"].items()}


def pose(part, opening):
    half = p["pivot_spacing"] / 2
    angle = np.arcsin((p["jaw_inner_offset"] - half) / p["crank_length"])
    angle += opening * (np.deg2rad(p["open_angle_degrees"]) - angle)
    side = part.get("side", 0)
    kind = part["motion"]
    rotation = 0
    if kind == "fixed":
        position = part["position"]
    elif kind in ["gear", "link"]:
        position = [side * (half + (p["parallel_offset"] if kind == "link" else 0)),
                    p["pivot_forward"], p["outer_link_bottom"] if kind == "link" else p["gear_bottom"]]
        rotation = -side * angle
    else:
        position = [side * (half + p["crank_length"] * np.sin(angle)),
                    p["pivot_forward"] + p["crank_length"] * np.cos(angle), p.get("jaw_bottom", 0)]
        if kind == "pin":
            position[0] += side * part.get("outer", 0) * p["parallel_offset"]
            position[2] -= .5
    matrix = trimesh.transformations.rotation_matrix(rotation, [0, 0, 1])
    matrix[:3, 3] = position
    return matrix


def overlap(first, second):
    # Manifold returns an empty mesh for disjoint solids.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = trimesh.boolean.intersection([first, second], engine="manifold")
        return abs(result.volume)


old_mount = mount.copy()
old_mount[:3, 3] = [28, 0, 5]
old_base = geometries["base"].copy()
old_base.apply_transform(old_mount)
old_overlap = overlap(wrist, old_base)
assert old_overlap > 1, "Regression fixture must reproduce the reported penetration"
checked = 0
for opening in np.linspace(0, 1, 21):
    for part in manifest["parts"]:
        mesh = geometries[part["geometry"]].copy()
        assert mesh.is_volume, part["name"]
        mesh.apply_transform(mount @ pose(part, opening))
        # Disjoint AABBs already prove the solids cannot intersect.
        if np.all(mesh.bounds[0] <= wrist.bounds[1]) and np.all(wrist.bounds[0] <= mesh.bounds[1]):
            volume = overlap(wrist, mesh)
            assert volume < .001, f'{part["name"]} opening={opening}: {volume:.6f} mm3'
        checked += 1
print(f"PASS wrist/gripper mesh intersections: {checked} checks, 21 opening poses")
print(f"Previous mounting overlap {old_overlap:.3f} mm3; corrected mounting overlap <0.001 mm3")
