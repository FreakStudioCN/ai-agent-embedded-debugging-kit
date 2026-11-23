# Two observation paths

1. Structured: existing algorithm results / JSONL → `python -m observation.structured FILE.jsonl` → Agent. Original record fields and versions are retained.
2. Direct multimodal: `python -m observation.multimodal --output .runtime/frame.jpg` → actual JPEG plus metadata. The Agent host must open/attach the image bytes; a pathname alone does not provide visual input.

Both paths can associate records with frame IDs. Snapshot timestamp currently means host receipt, not calibrated exposure time. A complete streaming contract, provider integration and automated policy remain future work. Neither path controls motors.
