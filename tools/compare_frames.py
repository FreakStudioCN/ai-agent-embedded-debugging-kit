"""Report local image displacement as evidence for camera-guided observation.

Select a static-background region. Values describe pixels in the original,
possibly inverted camera image. This tool does not certify physical stopping.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def compare(before, after, region, search=16):
    if before.size != after.size:
        raise ValueError("frame sizes must match")
    x0, y0, x1, y1 = region
    if not (0 <= x0 < x1 <= before.width and 0 <= y0 < y1 <= before.height):
        raise ValueError("region must lie inside the image")
    if not 1 <= search <= 64:
        raise ValueError("search must be in 1..64 pixels")
    a = np.asarray(before.convert("L"), dtype=np.float32)
    b = np.asarray(after.convert("L"), dtype=np.float32)
    radius = 12
    margin = radius + search
    if x1 - x0 < 2 * margin + 1 or y1 - y0 < 2 * margin + 1:
        raise ValueError("region is too small for the patch/search size")
    matches = []
    for cy in np.linspace(y0 + margin, y1 - margin - 1, 3).astype(int):
        for cx in np.linspace(x0 + margin, x1 - margin - 1, 3).astype(int):
            template = a[cy-radius:cy+radius+1, cx-radius:cx+radius+1]
            if template.std() < 8:
                continue
            template = template - template.mean()
            best = (float("inf"), 0, 0)
            for dy in range(-search, search + 1):
                for dx in range(-search, search + 1):
                    patch = b[cy+dy-radius:cy+dy+radius+1, cx+dx-radius:cx+dx+radius+1]
                    score = float(np.mean((template - (patch - patch.mean())) ** 2))
                    if score < best[0]:
                        best = (score, dx, dy)
            matches.append({"x": int(cx), "y": int(cy), "dx": best[1], "dy": best[2], "mse": round(best[0], 3)})
    if len(matches) < 3:
        raise ValueError("insufficient textured patches; choose a different region")
    shifts = np.array([[item["dx"], item["dy"]] for item in matches])
    shift = np.median(shifts, axis=0)
    spread = np.median(np.linalg.norm(shifts - shift, axis=1))
    return {"region": list(region), "median_dx_pixels": float(shift[0]),
            "median_dy_pixels": float(shift[1]), "median_deviation_pixels": round(float(spread), 3),
            "patches": matches, "physical_completion": "unverified"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--region", type=int, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    parser.add_argument("--search", type=int, default=16)
    args = parser.parse_args()
    with Image.open(args.before) as before, Image.open(args.after) as after:
        print(json.dumps(compare(before, after, args.region, args.search), ensure_ascii=False))


if __name__ == "__main__":
    main()
