"""Write tests/fixtures/frame_reference.json from the renderer as it is now.

Run once, before a change that must not alter any pixel:
    python tools/pin_frame_reference.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from test_frame_reference import FIXTURE, FRAMES, digest, environment  # noqa: E402

FIXTURE.parent.mkdir(parents=True, exist_ok=True)
FIXTURE.write_text(
    json.dumps(
        {
            "environment": environment(),
            "frames": {n: digest(f()) for n, f in sorted(FRAMES.items())},
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(f"wrote {FIXTURE}")
