from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from settlement_watch.engine import run_scan
from settlement_watch.gui import COLUMNS, SettlementWatchApp, parse_color
from settlement_watch.watchlist import load_watchlist, save_watchlist, write_watchlist_text

ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    def test_demo_scan_flags_high_and_writes_xlsx(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = run_scan(
                ROOT / "watchlist.example.csv",
                tmp,
                demo=True,
            )
            self.assertGreaterEqual(len(scan.results), 1)
            bands = {item.risk_band for item in scan.results}
            self.assertIn("HIGH", bands)
            self.assertTrue(scan.paths["xlsx"].exists())
            self.assertGreater(scan.paths["xlsx"].stat().st_size, 1000)
            self.assertEqual(len(scan.rows), len(scan.results))
            self.assertTrue(any(row["risk_band"] == "HIGH" for row in scan.rows))


class WatchlistWriteTests(unittest.TestCase):
    def test_round_trip_text_and_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "watch.csv"
            write_watchlist_text(path, "name,entity_type,aliases,notes\nAda,person,,note\n")
            targets = load_watchlist(path)
            self.assertEqual(targets[0].name, "Ada")
            save_watchlist(path, targets)
            again = load_watchlist(path)
            self.assertEqual(again[0].name, "Ada")


class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = SettlementWatchApp()
        cls.app.root.update_idletasks()

    @classmethod
    def tearDownClass(cls):
        cls.app.root.destroy()

    def test_spreadsheet_has_expected_columns_and_can_load_sample(self):
        self.assertEqual(list(self.app.tree["columns"]), COLUMNS)
        self.assertEqual(self.app.btn_live.cget("fg"), "#ffffff")
        self.assertEqual(self.app.btn_live.cget("bg"), "#4caf50")
        self.assertIn("rankings", self.app.pages)
        sample = ROOT / "sample-output" / "settlement_watch_leads.csv"
        if sample.exists() and not self.app.rows:
            from settlement_watch.engine import load_rows_csv

            self.app.rows = load_rows_csv(sample)
            self.app.refresh_sheet()
            self.app.root.update_idletasks()
        self.assertGreaterEqual(len(self.app.rows), 1)
        self.assertGreaterEqual(len(self.app.tree.get_children()), 1)
        self.assertGreaterEqual(len(self.app.parse_items), 1)
        self.assertEqual(parse_color(100), "#e6cc80")
        self.assertEqual(parse_color(96), "#ff8000")
        self.assertEqual(parse_color(80), "#a335ee")

    def test_loading_bar_appears(self):
        self.app._show_loading("Searching Harbor Creek Holdings LLC (1/4)…", current=1, total=4)
        self.app.root.update_idletasks()
        self.assertTrue(self.app.load_wrap.winfo_manager())
        self.assertEqual(self.app.load_pct.get(), "25%")
        self.app._hide_loading()
        self.app.root.update_idletasks()
        self.assertFalse(self.app.load_wrap.winfo_manager())

    def test_demo_scan_fills_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = run_scan(ROOT / "watchlist.example.csv", tmp, demo=True)
            self.app._on_scan_done(scan, None)
            self.app.root.update_idletasks()
            self.assertGreaterEqual(len(self.app.tree.get_children()), 1)
            self.assertGreaterEqual(len(self.app.parse_items), 1)
            self.assertTrue(any(item.risk_band == "HIGH" for item in self.app.results))
            text = self.app.narrative.get("1.0", "end")
            self.assertIn("Subject", text)


if __name__ == "__main__":
    unittest.main()
