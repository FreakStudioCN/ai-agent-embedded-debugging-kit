"""Launch camera-guided visual observation with raw images by default."""
from visual_observation.monitor import main

if __name__ == "__main__":
    main(default_skeleton=False)
