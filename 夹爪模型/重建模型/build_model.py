"""Parametric B-rep reconstruction of the user's photographed ZCJD gripper.

Uses the isolated cadquery-ocp-novtk package in ../建模工具.
Output lengths are millimetres. Photo estimates are recorded in parameters.json.
"""
from pathlib import Path
import json
import math
import shutil
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "建模工具"))

from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_Transform
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.IFSelect import IFSelect_RetDone
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Reader
from OCP.StlAPI import StlAPI_Writer
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Compound
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.XCAFDoc import XCAFDoc_ColorGen, XCAFDoc_DocumentTool


def box(x, y, z, dx, dy, dz):
    return BRepPrimAPI_MakeBox(gp_Pnt(x, y, z), dx, dy, dz).Shape()


def cylinder(x, y, z, radius, length, direction=(0, 0, 1)):
    axis = gp_Ax2(gp_Pnt(x, y, z), gp_Dir(*direction))
    return BRepPrimAPI_MakeCylinder(axis, radius, length).Shape()


def extrude(points, z, height):
    wire = BRepBuilderAPI_MakePolygon()
    for x, y in points:
        wire.Add(gp_Pnt(x, y, z))
    wire.Close()
    face = BRepBuilderAPI_MakeFace(wire.Wire()).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, height)).Shape()


def boolean(kind, first, second):
    operation = kind(first, second)
    operation.Build()
    if not operation.IsDone():
        raise RuntimeError("CAD boolean operation failed")
    return operation.Shape()


def fuse(first, second):
    return boolean(BRepAlgoAPI_Fuse, first, second)


def cut(first, second):
    return boolean(BRepAlgoAPI_Cut, first, second)


def capsule(x1, y1, x2, y2, radius, z, height):
    angle = math.atan2(y2 - y1, x2 - x1)
    points = []
    for index in range(17):
        a = angle + math.pi / 2 + index / 16 * math.pi
        points.append((x1 + radius * math.cos(a), y1 + radius * math.sin(a)))
    for index in range(17):
        a = angle - math.pi / 2 + index / 16 * math.pi
        points.append((x2 + radius * math.cos(a), y2 + radius * math.sin(a)))
    return extrude(points, z, height)


def transform(shape, position=(0, 0, 0), degrees=0):
    rotation = gp_Trsf()
    rotation.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), math.radians(degrees))
    rotation.SetTranslationPart(gp_Vec(*position))
    return BRepBuilderAPI_Transform(shape, rotation, True).Shape()


def volume(shape):
    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    return properties.Mass()


def solid_count(shape):
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    return count


def main_body(p):
    half = p["base_width"] / 2
    length = p["base_length"]
    bevel = 1.5
    outline = [(-half + bevel, 0), (half - bevel, 0), (half, bevel),
               (half, length - bevel), (half - bevel, length),
               (-half + bevel, length), (-half, length - bevel), (-half, bevel)]
    body = extrude(outline, 0, p["base_thickness"])
    body = fuse(body, box(-half, 0, p["base_thickness"] - p["mount_height"],
                          p["base_width"], p["mount_thickness"], p["mount_height"]))
    z_hole = p["base_thickness"] - p["mount_hole_from_top"]
    for x in [-p["mount_hole_pitch"] / 2, p["mount_hole_pitch"] / 2]:
        body = cut(body, cylinder(x, -1, z_hole, p["mount_hole_diameter"] / 2,
                                 p["mount_thickness"] + 2, (0, 1, 0)))
    sx = -p["pivot_spacing"] / 2
    py = p["pivot_forward"]
    # The servo case crosses the plate's long edge (local Y).
    # Its output shaft stays coaxial with the left sector gear.
    rail_start = sx - p["servo_shaft_from_end"]
    for side in [-1, 1]:
        rail_center = py + side * (p["servo_slot_width"] / 2 + p["servo_rail_width"] / 2)
        body = fuse(body, box(rail_start, rail_center - p["servo_rail_width"] / 2,
                             -p["servo_rail_height"], p["servo_slot_length"],
                             p["servo_rail_width"], p["servo_rail_height"] + 0.3))
    keyhole = fuse(cylinder(sx, py, -1, 6, p["base_thickness"] + 2),
                   box(sx, py - 3, -1, 9, 6, p["base_thickness"] + 2))
    body = cut(body, keyhole)
    for x in [p["pivot_spacing"] / 2, sx - p["parallel_offset"],
              p["pivot_spacing"] / 2 + p["parallel_offset"]]:
        body = cut(body, cylinder(x, py, -1, p["shaft_hole_diameter"] / 2,
                                 p["base_thickness"] + 2))
    for x in [rail_start - 2, rail_start + p["servo_slot_length"] + 2]:
        body = cut(body, cylinder(x, py, -1, 0.9, p["base_thickness"] + 2))
    # Stroke engraving retains the photographed mark without a font dependency.
    letters = [
        [(0, 7), (4.5, 7), (0, 0), (4.5, 0)],
        [(10.5, 6.5), (9, 7), (7.5, 6), (7, 3.5), (7.5, 1), (9, 0), (10.5, .5)],
        [(17, 7), (17, 1.5), (16, 0), (14.5, 0), (13.5, 1.5)],
        [(20, 0), (20, 7), (22, 7), (24, 5.5), (24, 1.5), (22, 0), (20, 0)],
    ]
    for stroke in letters:
        for start, end in zip(stroke, stroke[1:]):
            engraving = capsule(12 - start[0], 6 + start[1], 12 - end[0], 6 + end[1], .33, -.1, .65)
            body = cut(body, engraving)
    return body


def gear_outline(p, phase_offset=0):
    teeth = int(p["gear_teeth"])
    pitch = p["gear_module"] * teeth / 2
    base = pitch * math.cos(math.radians(p["gear_pressure_angle"]))
    root = pitch - 1.25 * p["gear_module"]
    outer = pitch + p["gear_module"]
    inv_pitch = math.tan(math.acos(base / pitch)) - math.acos(base / pitch)
    half_tooth = math.pi / (2 * teeth) - p["gear_backlash"] / (2 * pitch)
    phase = math.pi / (2 * teeth) + phase_offset
    points = []
    for tooth in range(teeth):
        center = tooth * 2 * math.pi / teeth + phase
        # Nominal involute flanks, sampled into a planar CAD wire.
        half_base = half_tooth + inv_pitch
        for radius, offset in [(root, -math.pi / teeth), (root, -half_base)]:
            points.append((radius * math.cos(center + offset), radius * math.sin(center + offset)))
        for index in range(7):
            radius = base + (outer - base) * index / 6
            alpha = math.acos(min(1, base / radius))
            involute = math.tan(alpha) - alpha
            angle = center - half_tooth - inv_pitch + involute
            points.append((radius * math.cos(angle), radius * math.sin(angle)))
        for index in range(6, -1, -1):
            radius = base + (outer - base) * index / 6
            alpha = math.acos(min(1, base / radius))
            angle = center + half_tooth + inv_pitch - (math.tan(alpha) - alpha)
            points.append((radius * math.cos(angle), radius * math.sin(angle)))
        for radius, offset in [(root, half_base), (root, math.pi / teeth)]:
            points.append((radius * math.cos(center + offset), radius * math.sin(center + offset)))
    return points


def gear_arm(p, side):
    # Half a tooth pitch offsets tooth centres against the opposite tooth gaps.
    points = gear_outline(p, math.pi / p["gear_teeth"] if side == 1 else 0)
    # Mirror creates the complementary sector on the opposite jaw.
    if side == 1:
        points = [(-x, y) for x, y in reversed(points)]
    gear = extrude(points, 0, p["gear_thickness"])
    radius = p["gear_module"] * (p["gear_teeth"] + 2) / 2 + 2
    arc = [(0, 0)]
    for i in range(81):
        angle = math.radians(-130 + i / 80 * 230)
        x = radius * math.cos(angle)
        arc.append((-x if side == 1 else x, radius * math.sin(angle)))
    gear = boolean(BRepAlgoAPI_Common, gear, extrude(arc, -1, p["gear_thickness"] + 2))
    gear = fuse(gear, capsule(0, 0, 0, p["crank_length"], p["arm_width"] / 2, 0, p["gear_thickness"]))
    gear = fuse(gear, cylinder(0, 0, 0, 5, p["gear_thickness"] + 2))
    for y in [0, p["crank_length"]]:
        gear = cut(gear, cylinder(0, y, -1, p["shaft_hole_diameter"] / 2, p["gear_thickness"] + 4))
    gear = cut(gear, cylinder(0, 0, p["gear_thickness"] - 1, 3.5, 4))
    return gear


def outer_link(p):
    link = capsule(0, 0, 0, p["crank_length"], 2.8, 0, p["outer_link_thickness"])
    for y in [0, p["crank_length"]]:
        link = cut(link, cylinder(0, y, -1, p["shaft_hole_diameter"] / 2, p["outer_link_thickness"] + 2))
    return link


def finger(p, side):
    inner = p["jaw_inner_offset"]
    outer = inner - p["jaw_root_width"]
    points = [(outer, -4), (inner, -4)]
    points.append((inner, 5))
    y = 5
    while y + p["jaw_tooth_pitch"] <= p["jaw_length"]:
        points.extend([(inner - p["jaw_tooth_depth"], y + p["jaw_tooth_pitch"] / 2),
                       (inner, y + p["jaw_tooth_pitch"])])
        y += p["jaw_tooth_pitch"]
    points.extend([(inner, p["jaw_length"]), (inner - 2, p["jaw_length"]), (outer, 8)])
    if side == 1:
        points = [(-x, y) for x, y in reversed(points)]
    cheek = p["jaw_cheek_thickness"]
    shape = extrude(points, 0, cheek)
    upper = extrude(points, p["jaw_height"] - cheek, cheek)
    # Inner contact wall joins the two cheeks, leaving a clevis at the two pins.
    bridge_x = (inner - 2.4) if side == -1 else -inner
    bridge = box(bridge_x, 5, 0, 2.4, p["jaw_length"] - 5, p["jaw_height"])
    # Use the same serrated silhouette for the wall so the tooth relief is through-depth.
    bridge = boolean(BRepAlgoAPI_Common, bridge, extrude(points, 0, p["jaw_height"]))
    shape = fuse(fuse(shape, upper), bridge)
    for x in [0, side * p["parallel_offset"]]:
        shape = cut(shape, cylinder(x, 0, -1, p["shaft_hole_diameter"] / 2, p["jaw_height"] + 2))
    return shape


def servo_case(p):
    sx = -p["pivot_spacing"] / 2
    py = p["pivot_forward"]
    x = sx - p["servo_shaft_from_end"]
    length = p["servo_slot_length"] - .5
    width = p["servo_slot_width"] - .5
    depth = p["servo_body_depth"]
    body = box(x, py - width / 2, -depth - 1, length, width, depth)
    # Two mounting ears and an output boss are part of the case envelope.
    body = fuse(body, box(x - 3, py - 2, -5, length + 6, 4, 2))
    return fuse(body, cylinder(sx, py, -1.2, 4.5, 1.2))


def bolt(length):
    shape = fuse(cylinder(0, 0, 0, 1.4, length), cylinder(0, 0, length - .1, 2.65, 1.6))
    for dx, dy in [(3.8, .7), (.7, 3.8)]:
        shape = cut(shape, box(-dx / 2, -dy / 2, length + .8, dx, dy, 1))
    return shape


def pose_for(part, fraction, p):
    spacing = p["pivot_spacing"] / 2
    closed = math.asin((p["jaw_inner_offset"] - spacing) / p["crank_length"])
    angle = closed + fraction * (math.radians(p["open_angle_degrees"]) - closed)
    side = part.get("side", 0)
    kind = part["motion"]
    if kind == "fixed":
        return part["position"], 0
    if kind in ("gear", "link"):
        x = side * (spacing + (p["parallel_offset"] if kind == "link" else 0))
        z = p["gear_bottom"] if kind == "gear" else p["outer_link_bottom"]
        return [x, p["pivot_forward"], z], -side * math.degrees(angle)
    x = side * (spacing + p["crank_length"] * math.sin(angle))
    y = p["pivot_forward"] + p["crank_length"] * math.cos(angle)
    if kind == "finger":
        return [x, y, p.get("jaw_bottom", 0)], 0
    if kind == "pin":
        x += side * part.get("outer", 0) * p["parallel_offset"]
        return [x, y, p.get("jaw_bottom", 0) - .5], 0
    raise ValueError("Unknown motion " + kind)


def export_stl(shape, path):
    BRepMesh_IncrementalMesh(shape, .06, False, .18, True).Perform()
    writer = StlAPI_Writer()
    writer.ASCIIMode = False
    if not writer.Write(shape, str(path)):
        raise RuntimeError("STL export failed: " + str(path))


def export_step(parts, shapes, path, fraction, p):
    doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    assembly = shape_tool.NewShape()
    TDataStd_Name.Set_s(assembly, TCollection_ExtendedString("ZCJD photo reconstructed gripper"))
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for part in parts:
        position, angle = pose_for(part, fraction, p)
        placed = transform(shapes[part["geometry"]], position, angle)
        builder.Add(compound, placed)
        label = shape_tool.AddShape(placed, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(part["name"]))
        color = part["color"].lstrip("#")
        rgb = [int(color[i:i + 2], 16) / 255 for i in [0, 2, 4]]
        color_tool.SetColor(label, Quantity_Color(*rgb, Quantity_TOC_RGB), XCAFDoc_ColorGen)
        shape_tool.AddComponent(assembly, label, TopLoc_Location())
    shape_tool.UpdateAssemblies()
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    if not writer.Transfer(doc, STEPControl_AsIs):
        raise RuntimeError("STEP transfer failed")
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise RuntimeError("STEP export failed")
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise RuntimeError("STEP round-trip read failed")
    reader.TransferRoots()
    if not BRepCheck_Analyzer(reader.OneShape()).IsValid() or solid_count(reader.OneShape()) != len(parts):
        raise RuntimeError("Exported STEP is invalid")
    return compound


def validate(p):
    numeric = {key: value for key, value in p.items() if isinstance(value, (int, float))}
    nonnegative = {"gear_backlash", "default_open_fraction"}
    if not all(math.isfinite(value) and (value >= 0 if key in nonnegative else value > 0)
               for key, value in numeric.items()):
        raise ValueError("Model dimensions must be positive and finite")
    if not 0 <= p["default_open_fraction"] <= 1:
        raise ValueError("Default opening must be in 0..1")
    if not 0 < p["open_angle_degrees"] < 90:
        raise ValueError("Open angle must be in 0..90 degrees")
    if abs(p["pivot_spacing"] - p["gear_module"] * p["gear_teeth"]) > .001:
        raise ValueError("Gear center spacing must equal module times tooth count")
    if p["jaw_inner_offset"] >= p["pivot_spacing"] / 2:
        raise ValueError("Jaw inner offset must be smaller than half the pivot spacing")
    if abs((p["jaw_inner_offset"] - p["pivot_spacing"] / 2) / p["crank_length"]) >= 1:
        raise ValueError("Closed pose cannot be solved for these dimensions")
    if p["jaw_height"] <= 2 * p["jaw_cheek_thickness"]:
        raise ValueError("Jaw must leave space between its two cheeks")


def main():
    p = json.loads((ROOT / "parameters.json").read_text(encoding="utf-8"))
    validate(p)
    print("Building photographed base and linkage", flush=True)
    shapes = {"base": main_body(p), "servo": servo_case(p), "gear_left": gear_arm(p, -1),
              "gear_right": gear_arm(p, 1), "link": outer_link(p),
              "finger_left": finger(p, -1), "finger_right": finger(p, 1),
              "bolt": bolt(13.5), "base_bolt": bolt(p["gear_bottom"] + 7),
              "base_bolt_outer": bolt(p["outer_link_bottom"] + 2.6)}
    parts = [{"name": "mounting_base", "geometry": "base", "motion": "fixed",
              "position": [0, 0, 0], "color": "#91959d", "label": "灰色安装座"},
             {"name": "servo_case", "geometry": "servo", "motion": "fixed",
              "position": [0, 0, 0], "color": "#302d30", "label": "横置舵机壳体"}]
    for side, suffix in [(-1, "left"), (1, "right")]:
        parts += [
            {"name": "sector_arm_" + suffix, "geometry": "gear_" + suffix, "motion": "gear", "side": side, "color": "#969ca6", "label": "扇形齿轮连杆"},
            {"name": "parallel_link_" + suffix, "geometry": "link", "motion": "link", "side": side, "color": "#c6ced7", "label": "平行连杆"},
            {"name": "finger_" + suffix, "geometry": "finger_" + suffix, "motion": "finger", "side": side, "color": "#7050aa", "label": "紫色爪指"},
        ]
        for outer in [0, 1]:
            parts.append({"name": "finger_pin_%s_%d" % (suffix, outer), "geometry": "bolt", "motion": "pin", "side": side, "outer": outer, "color": "#c9b991", "label": "爪指销轴"})
            parts.append({"name": "base_pin_%s_%d" % (suffix, outer), "geometry": "base_bolt_outer" if outer else "base_bolt", "motion": "fixed",
                          "position": [side * (p["pivot_spacing"] / 2 + outer * p["parallel_offset"]), p["pivot_forward"], -1], "color": "#c9b991", "label": "根部销轴"})
    neutral = ROOT / "parts"
    neutral.mkdir(exist_ok=True)
    checks = {}
    for name, shape in shapes.items():
        valid = BRepCheck_Analyzer(shape).IsValid()
        mass = volume(shape)
        count = solid_count(shape)
        if not valid or mass <= 0 or count != 1:
            raise RuntimeError("Invalid solid %s, volume %s" % (name, mass))
        export_stl(shape, neutral / (name + ".stl"))
        checks[name] = {"valid": valid, "solid_count": count, "volume_mm3": round(mass, 3)}
        print("Validated", name, "volume", round(mass, 1), flush=True)
    gear_checks = []
    for index in range(21):
        opening = index / 20
        left_position, left_angle = pose_for({"motion": "gear", "side": -1}, opening, p)
        right_position, right_angle = pose_for({"motion": "gear", "side": 1}, opening, p)
        interference = boolean(BRepAlgoAPI_Common,
            transform(shapes["gear_left"], left_position, left_angle),
            transform(shapes["gear_right"], right_position, right_angle))
        overlap = abs(volume(interference))
        if overlap > .001:
            raise RuntimeError("Reconstructed gears interfere at opening %s" % opening)
        gear_checks.append({"opening": opening, "overlap_mm3": round(overlap, 8)})
    assembly = export_step(parts, shapes, ROOT / "zcjd_gripper.step", p["default_open_fraction"], p)
    export_stl(assembly, ROOT / "zcjd_gripper_assembly.stl")
    export_step(parts, shapes, ROOT / "zcjd_gripper_closed.step", 0, p)
    manifest = {"name": "ZCJD 夹爪照片重建", "units": "mm", "parameters": p, "parts": parts,
                "geometry": {key: "parts/" + key + ".stl" for key in shapes},
                "validation": checks, "gear_clearance_checks": gear_checks,
                "coordinate_system": "X lateral, Y toward fingers, Z normal to base plate; rear base edge Y=0; underside Z=0",
                "precision": "Photo-scale reconstruction; nominal gear and bore dimensions require physical measurement"}
    (ROOT / "model.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # Serve the same model from the existing browser simulator.
    target = ROOT.parents[1] / "simulator" / "models" / "custom_gripper"
    target.mkdir(parents=True, exist_ok=True)
    for file in ["model.json", "parameters.json", "zcjd_gripper.step", "zcjd_gripper_closed.step", "zcjd_gripper_assembly.stl"]:
        shutil.copy2(ROOT / file, target / file)
    shutil.copytree(neutral, target / "parts", dirs_exist_ok=True)
    print("Exported STEP, assembly STL, %d neutral part STL files and model manifest" % len(shapes), flush=True)


if __name__ == "__main__":
    main()
