"""Observation identity shared by both read-only paths."""
from dataclasses import dataclass, asdict
@dataclass(frozen=True)
class FramePacket:
    frame_id: str
    camera_id: str
    captured_at: str
    image_ref: str
    coordinate_frame: str = "image_pixels"
    schema_version: str = "1.0"
    def to_dict(self): return asdict(self)
