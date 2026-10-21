from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from settlement_watch.cli import main
from settlement_watch.export import export_all, rows_from_results
from settlement_watch.models import DocketRecord, WatchTarget
from settlement_watch.scoring import score_docket
from settlement_watch.watchlist import load_watchlist

ROOT = Path(__file__).resolve().parents[1]


class WatchlistTests(unittest.TestCase):
    def test_loads_example_watchlist(self):
        targets = load_watchlist(ROOT / "watchlist.example.csv")
        names = [target.name for target in targets]
        self.assertIn("Harbor Creek Holdings LLC", names)
        harbor = next(target for target in targets if "Harbor" in target.name)
        self.assertIn("Harbor Creek Holdings", harbor.aliases)

    def test_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.csv"
            path.write_text("name,entity_type\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_watchlist(path)


class ExportAndDemoTests(unittest.TestCase):
    def test_export_writes_expected_files(self):
        target = WatchTarget("Harbor Creek Holdings LLC", "company")
        record = DocketRecord.from_api(
            {
                "docket_id": 1,
                "caseName": "Harbor Creek Holdings LLC v. Harbor Creek Partners LLC",
                "court": "S.D.N.Y.",
                "court_id": "nysd",
                "docketNumber": "1:24-cv-1",
                "dateFiled": "2024-01-02",
                "dateTerminated": "2024-01-18",
                "cause": "Contract",
                "party": ["Harbor Creek Holdings LLC", "Harbor Creek Partners LLC"],
                "docket_absolute_url": "/docket/1/example/",
                "recap_documents": [
                    {
                        "description": "Consent judgment $500,000 personal physical injury. Sealed."
                    }
                ],
            }
        )
        scored = score_docket(target, record)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = export_all(out, [scored], mode="test")
            self.assertTrue(paths["xlsx"].exists())
            self.assertGreater(paths["xlsx"].stat().st_size, 1000)
            csv_text = paths["csv"].read_text(encoding="utf-8")
            self.assertIn("subject_name", csv_text)
            self.assertIn("Harbor Creek Holdings LLC", csv_text)
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
            self.assertEqual(payload["lead_count"], 1)
            self.assertIn("disclaimer", payload)
            from datetime import datetime, timezone

            rows = rows_from_results([scored], datetime.now(timezone.utc))
            self.assertEqual(rows[0]["information_source"], "CourtListener/RECAP public docket")

    def test_demo_cli_creates_spreadsheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["check", "--demo", "--out", tmp, "--watchlist", str(ROOT / "watchlist.example.csv")])
            self.assertEqual(code, 0)
            xlsx = Path(tmp) / "settlement_watch_leads.xlsx"
            self.assertTrue(xlsx.exists())
            flagged = (Path(tmp) / "settlement_watch_flagged.csv").read_text(encoding="utf-8")
            self.assertIn("HIGH", flagged)
            self.assertIn("Keene", flagged)


if __name__ == "__main__":
    unittest.main()
