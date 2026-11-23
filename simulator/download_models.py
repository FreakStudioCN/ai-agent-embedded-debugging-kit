"""Download pinned upstream CAD assets and Three.js for the local simulator."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
REPOSITORY = "20sffactory/community_robot_arm"
COMMIT = "6c2f57390f0186f47bb199f06c875dedf8de268f"


def fetch(url):
    request = Request(url, headers={"User-Agent": "RobotArmLocalSimulator"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=90) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def main():
    tree = json.loads(fetch("https://api.github.com/repos/%s/git/trees/%s?recursive=1" % (REPOSITORY, COMMIT)))
    paths = [item["path"] for item in tree["tree"]
             if item["type"] == "blob" and item["path"].startswith("CAD Files/")]
    expected = {item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"}
    paths += ["README.md", "LICENSE", "arduino_firmware/robotArm_v0.81/config.h",
              "arduino_firmware/robotArm_v0.81/robotGeometry.cpp",
              "arduino_firmware/robotArm_v0.81/robotGeometry.h"]

    def download(path):
        url = "https://raw.githubusercontent.com/%s/%s/%s" % (REPOSITORY, COMMIT, quote(path))
        target = ROOT.parent / "mechanical" / "upstream" / "community_robot_arm" / path
        data = target.read_bytes() if target.exists() else b""
        def git_hash(content):
            return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if git_hash(data) != expected[path]:
            data = fetch(url)
        if git_hash(data) != expected[path]:
            raise RuntimeError("Upstream file hash mismatch: " + path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "url": url}

    with ThreadPoolExecutor(max_workers=6) as pool:
        files = list(pool.map(download, paths))
    manifest = {"repository": "https://github.com/" + REPOSITORY, "commit": COMMIT,
                "cad_license": "CC BY 4.0, per upstream README", "files": files}
    (ROOT.parent / "mechanical" / "upstream" / "community_robot_arm" / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    vendor = {"three.module.js": "build/three.module.js", "OrbitControls.js": "examples/jsm/controls/OrbitControls.js",
              "STLLoader.js": "examples/jsm/loaders/STLLoader.js", "LICENSE": "LICENSE"}
    for name, path in vendor.items():
        target = ROOT / "vendor" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fetch("https://cdn.jsdelivr.net/npm/three@0.170.0/" + path))
    print("Downloaded %d upstream files (%0.1f MB), and Three.js 0.170.0" %
          (len(files), sum(item["bytes"] for item in files) / 1000000))


if __name__ == "__main__":
    main()
