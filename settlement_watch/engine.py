from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from settlement_watch.courtlistener import (
    CourtListenerClient,
    demo_search,
    load_demo_dockets,
)
from settlement_watch.export import export_all, rows_from_results
from settlement_watch.models import ScoredCase, WatchTarget
from settlement_watch.scoring import apply_repeat_litigant, score_docket
from settlement_watch.watchlist import load_watchlist

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "fixtures" / "demo_dockets.json"
DEFAULT_WATCHLIST = ROOT / "watchlist.example.csv"

Progress = Callable[..., None]


def emit_progress(
    progress: Progress | None,
    message: str,
    current: int | None = None,
    total: int | None = None,
) -> None:
    if progress is None:
        return
    try:
        progress(message, current, total)
    except TypeError:
        progress(message)


@dataclass
class ScanResult:
    mode: str
    results: list[ScoredCase]
    rows: list[dict[str, str]]
    paths: dict[str, Path]


def score_targets(
    targets: list[WatchTarget],
    fetch,
    progress: Progress | None = None,
) -> list[ScoredCase]:
    results: list[ScoredCase] = []
    seen: set[tuple[str, str]] = set()
    total = max(len(targets), 1)
    for index, target in enumerate(targets):
        emit_progress(
            progress,
            f"Searching {target.name} ({index + 1}/{len(targets)})…",
            current=index,
            total=total,
        )
        dockets = fetch(target)
        emit_progress(
            progress,
            f"{target.name}: {len(dockets)} docket(s)",
            current=index + 1,
            total=total,
        )
        for docket in dockets:
            key = (target.name.lower(), docket.docket_id or docket.docket_number)
            if key in seen:
                continue
            seen.add(key)
            results.append(score_docket(target, docket))
    return results


def run_scan(
    watchlist_path: str | Path,
    out_dir: str | Path,
    *,
    demo: bool = True,
    token: str = "",
    max_per_name: int = 25,
    fixture: str | Path | None = None,
    progress: Progress | None = None,
) -> ScanResult:
    targets = load_watchlist(watchlist_path)
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    total_names = max(len(targets), 1)

    if demo:
        mode = "demo/offline"
        fixture_path = Path(fixture) if fixture else DEFAULT_FIXTURE
        fixture_dockets = load_demo_dockets(fixture_path)
        emit_progress(
            progress,
            f"Demo mode: {len(fixture_dockets)} sample dockets, {len(targets)} names.",
            current=0,
            total=total_names,
        )
        results = score_targets(
            targets,
            lambda target: demo_search(target, fixture_dockets),
            progress=progress,
        )
    else:
        mode = "courtlistener-live"
        client = CourtListenerClient(token=token or None)
        emit_progress(
            progress,
            f"Live search: {len(targets)} names via CourtListener "
            f"(max {max_per_name} dockets each).",
            current=0,
            total=total_names,
        )
        results = score_targets(
            targets,
            lambda target: client.search_dockets(target, max_per_name=max_per_name),
            progress=progress,
        )

    results = apply_repeat_litigant(results)
    results.sort(key=lambda item: (-item.risk_score, item.watch_name, item.docket.case_name))
    emit_progress(progress, "Writing spreadsheet…", current=total_names, total=total_names)
    paths = export_all(dest, results, mode=mode)
    rows = rows_from_results(results, datetime.now(timezone.utc).replace(microsecond=0))
    return ScanResult(mode=mode, results=results, rows=rows, paths=paths)


def load_rows_csv(path: str | Path) -> list[dict[str, str]]:
    file_path = Path(path)
    with file_path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))
