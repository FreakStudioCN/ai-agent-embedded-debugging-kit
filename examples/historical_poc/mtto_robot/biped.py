"""Optional historical MttoRobot HTTP adapter."""
import json
import time
from urllib.request import Request, urlopen
from host_control.errors import ScanError

class Biped:
    def __init__(self, url, config_path):
        self.url = url.rstrip("/")
        token = json.loads(config_path.read_text(encoding="utf-8"))["token"]
        self.headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

    def request(self, path, action=None):
        data = None if action is None else json.dumps(action).encode("utf-8")
        with urlopen(Request(self.url + path, data=data, headers=self.headers), timeout=3) as response:
            if action is not None and response.status != 202:
                raise ScanError("Biped did not accept the demo action")
            return json.load(response)

    def check_ready(self):
        state = self.request("/status")
        if state["state"] != "idle" or not state["initialized"]:
            raise ScanError("Biped is not initialized and idle")
        return state["commanded_angles"]

    def start(self, motion):
        baseline = self.check_ready()
        self.request("/action", motion)
        return baseline

    def wait(self, action, baseline):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            state = self.request("/status")
            if state["state"] == "error" or not state["initialized"]:
                raise ScanError("Biped encountered a motion error")
            if state["action"] != action:
                raise ScanError("Biped reported a different action")
            if state["state"] == "idle":
                if state["commanded_angles"] != baseline:
                    raise ScanError("Biped did not return to its standing commands")
                return
            time.sleep(.2)
        raise ScanError("Biped action timed out: " + action)
