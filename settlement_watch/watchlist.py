from __future__ import annotations

import csv
from pathlib import Path

from settlement_watch.models import WatchTarget


def load_watchlist(path: str | Path) -> list[WatchTarget]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Watchlist not found: {file_path}")

    with file_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Watchlist CSV has no header row.")
        fields = {name.strip().lower(): name for name in reader.fieldnames if name}
        if "name" not in fields:
            raise ValueError("Watchlist CSV must include a 'name' column.")

        targets: list[WatchTarget] = []
        for row in reader:
            name = (row.get(fields["name"]) or "").strip()
            if not name or name.startswith("#"):
                continue
            entity_type = (
                row.get(fields.get("entity_type", ""), "") or "unknown"
            ).strip().lower() or "unknown"
            aliases_raw = (row.get(fields.get("aliases", ""), "") or "").strip()
            aliases = tuple(
                part.strip()
                for part in aliases_raw.replace("|", ";").split(";")
                if part.strip()
            )
            notes = (row.get(fields.get("notes", ""), "") or "").strip()
            targets.append(
                WatchTarget(
                    name=name,
                    entity_type=entity_type,
                    aliases=aliases,
                    notes=notes,
                )
            )
    if not targets:
        raise ValueError("Watchlist CSV did not contain any names.")
    return targets


def write_watchlist_text(path: str | Path, text: str) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    body = text if text.endswith("\n") else text + "\n"
    file_path.write_text(body, encoding="utf-8")


def save_watchlist(path: str | Path, targets: list[WatchTarget]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "entity_type", "aliases", "notes"])
        writer.writeheader()
        for target in targets:
            writer.writerow(
                {
                    "name": target.name,
                    "entity_type": target.entity_type,
                    "aliases": "; ".join(target.aliases),
                    "notes": target.notes,
                }
            )
