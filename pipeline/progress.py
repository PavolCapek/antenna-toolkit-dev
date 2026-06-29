from __future__ import annotations

import json


def emit_progress(stage: str, current: int, total: int, label: str) -> None:
    print(
        f"AT_PROGRESS {json.dumps({'stage': stage, 'current': int(current), 'total': int(total), 'label': label})}",
        flush=True,
    )
