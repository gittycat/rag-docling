"""Manual review export utilities for evaluation v2."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable


def export_review_json(rows: Iterable[dict], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(list(rows), f, indent=2)
    return output_path


def export_review_csv(rows: Iterable[dict], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows_list = list(rows)
    if not rows_list:
        output_path.write_text("")
        return output_path

    fieldnames = sorted({key for row in rows_list for key in row.keys()})
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_list)
    return output_path
