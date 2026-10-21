from __future__ import annotations

import subprocess

import csv
import json
import os
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
import tkinter.font as tkfont

from settlement_watch import __app_name__, __version__
from settlement_watch.engine import ROOT, ScanResult, load_rows_csv, run_scan
from settlement_watch.models import ScoredCase
from settlement_watch.scoring import lead_narrative
from settlement_watch.watchlist import load_watchlist, write_watchlist_text

ICON = ROOT / "assets" / "icon.png"
SAMPLE_CSV = ROOT / "sample-output" / "settlement_watch_leads.csv"
EXAMPLE_WATCHLIST = ROOT / "watchlist.example.csv"
APP_SUPPORT = Path.home() / "Library" / "Application Support" / "Roach Detector"
DOCUMENTS = Path.home() / "Documents" / "Roach Detector"
OLD_APP_SUPPORT = Path.home() / "Library" / "Application Support" / "Settlement Watch"
OLD_DOCUMENTS = Path.home() / "Documents" / "Settlement Watch"
CONFIG_PATH = APP_SUPPORT / "config.json"

# Warcraft Logs-style report chrome. Parse bands use WoW item-quality colors.
BG = "#111111"
TOP = "#0b0b0b"
PANEL = "#1a1a1a"
RAIL = "#161616"
ROW = "#1e1e1e"
ROW_ALT = "#252525"
LINE = "#2e2e2e"
TEXT = "#f2f2f2"
MUTED = "#c8c8c8"
GREEN = "#4caf50"
GREEN_DK = "#2e7d32"
SEARCH_BG = "#2a2a2a"

LEGENDARY = "#ff8000"
EPIC = "#c57cff"
RARE = "#6ea8ff"
UNCOMMON = "#7CFF7C"
POOR = "#c0c0c0"

BAND_FG = {
    "HIGH": LEGENDARY,
    "MEDIUM": EPIC,
    "LOW": RARE,
    "INFO": POOR,
}
BAND_BG = {
    "HIGH": "#2a1608",
    "MEDIUM": "#221430",
    "LOW": "#0e1c30",
    "INFO": ROW,
}
PARSE_TRACK = "#2a2a2a"
PARSE_ROW_H = 40


def parse_color(score: int) -> str:
    if score >= 100:
        return "#e6cc80"
    if score >= 95:
        return "#ff8000"
    if score >= 75:
        return "#a335ee"
    if score >= 50:
        return "#0070dd"
    if score >= 25:
        return "#1eff00"
    return "#9d9d9d"


def parse_label_color(score: int) -> str:
    if score >= 100 or 25 <= score < 50:
        return "#111111"
    return "#ffffff"


def parse_score(row: dict[str, str]) -> int:
    try:
        return max(0, min(100, int(row.get("risk_score") or 0)))
    except ValueError:
        return 0


def format_amount(raw: str) -> str:
    text = (raw or "").replace(";", ",").strip()
    if not text:
        return "—"
    parts: list[str] = []
    for chunk in text.replace(" ", "").split(","):
        if not chunk:
            continue
        try:
            parts.append(f"${int(chunk):,}")
        except ValueError:
            parts.append(chunk)
    return ", ".join(parts) if parts else "—"

COLUMNS = [
    "risk_band",
    "risk_score",
    "subject_name",
    "case_name",
    "court",
    "docket_number",
    "date_filed",
    "date_terminated",
    "amount_parsed_usd",
    "flag_codes",
    "review_priority",
    "source_url",
]

COL_WIDTHS = {
    "risk_band": 92,
    "risk_score": 78,
    "subject_name": 190,
    "case_name": 300,
    "court": 150,
    "docket_number": 128,
    "date_filed": 108,
    "date_terminated": 118,
    "amount_parsed_usd": 128,
    "flag_codes": 240,
    "review_priority": 118,
    "source_url": 250,
}

HEADINGS = {
    "risk_band": "Band",
    "risk_score": "Score",
    "subject_name": "Subject",
    "case_name": "Case",
    "court": "Court",
    "docket_number": "Docket",
    "date_filed": "Filed",
    "date_terminated": "Terminated",
    "amount_parsed_usd": "Amount",
    "flag_codes": "Flags",
    "review_priority": "Priority",
    "source_url": "Source",
}

TABS = (
    ("rankings", "Parses"),
    ("table", "Table"),
    ("events", "Events"),
    ("watchlist", "Watchlist"),
    ("setup", "Setup"),
)

FIGHTS = (
    ("ALL", "All leads"),
    ("FLAGGED", "Flagged"),
    ("HIGH", "High"),
    ("MEDIUM", "Medium"),
    ("LOW", "Low"),
    ("INFO", "Info"),
)


def _pick_font(families: tuple[str, ...], size: int, weight: str = "normal") -> tuple:
    available = set(tkfont.families())
    for name in families:
        if name in available:
            return (name, size, weight)
    return ("Helvetica", size, weight)


class Chip(tk.Label):
    """Colored clickable control. Native macOS tk.Button ignores fg/bg."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command,
        kind: str = "secondary",
        compact: bool = False,
    ) -> None:
        self.command = command
        self.kind = kind
        self._enabled = True
        pad_x = 12 if compact else 18
        pad_y = 6 if compact else 9
        super().__init__(
            parent,
            text=text,
            cursor="hand2",
            padx=pad_x,
            pady=pad_y,
            bd=0,
            highlightthickness=0,
        )
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._paint()

    def configure(self, cnf=None, **kw):  # type: ignore[override]
        if cnf:
            kw = {**cnf, **kw}
        if "state" in kw:
            self._enabled = kw.pop("state") != "disabled"
        if "command" in kw:
            self.command = kw.pop("command")
        if "text" in kw:
            super().configure(text=kw.pop("text"))
        if "kind" in kw:
            self.kind = kw.pop("kind")
        if kw:
            super().configure(**kw)
        self._paint()
        return self

    def _palette(self) -> tuple[str, str]:
        if not self._enabled:
            return ("#3a3a3a", "#9a9a9a")
        if self.kind == "primary":
            return (GREEN, "#ffffff")
        if self.kind == "tab-on":
            return ("#243d26", "#ffffff")
        if self.kind == "tab":
            return (TOP, TEXT)
        if self.kind == "fight-on":
            return ("#1b3d1b", "#ffffff")
        if self.kind == "danger":
            return ("#8b1e1e", "#ffffff")
        return ("#2f2f2f", "#ffffff")

    def _paint(self) -> None:
        bg, fg = self._palette()
        super().configure(bg=bg, fg=fg)

    def _enter(self, _event=None) -> None:
        if not self._enabled:
            return
        bg, fg = self._palette()
        if self.kind == "primary":
            super().configure(bg="#66bb6a", fg="#ffffff")
        else:
            super().configure(bg="#3a3a3a", fg=fg)

    def _leave(self, _event=None) -> None:
        self._paint()

    def _click(self, _event=None) -> None:
        if self._enabled and self.command:
            self.command()


class SettlementWatchApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"{__app_name__}  ·  find the roaches")
        self.root.geometry("1440x900")
        self.root.minsize(1100, 740)
        self.root.configure(bg=BG)
        self._load_icon()

        sans = ("Helvetica Neue", "SF Pro Text", "Helvetica")
        self.display = _pick_font(("Helvetica Neue", "SF Pro Display", "Helvetica"), 20, "bold")
        self.ui = _pick_font(sans, 14)
        self.ui_small = _pick_font(sans, 13)
        self.ui_bold = _pick_font(sans, 14, "bold")
        self.tab_font = _pick_font(sans, 14, "bold")
        self.mono = _pick_font(("Menlo", "SF Mono", "Monaco"), 13)
        self.parse_num = _pick_font(("Helvetica Neue", "SF Pro Display", "Helvetica"), 20, "bold")

        self.rows: list[dict[str, str]] = []
        self.results: list[ScoredCase] = []
        self.paths: dict[str, Path] = {}
        self.mode = ""
        self._busy = False
        self.filter_band = tk.StringVar(value="ALL")
        self.search_var = tk.StringVar()
        self.status = tk.StringVar(value="Ready. Screening tool only — not a finding.")
        self.token_var = tk.StringVar()
        self.max_var = tk.StringVar(value="25")
        self.out_var = tk.StringVar()
        self.stat_scored = tk.StringVar(value="0")
        self.stat_flagged = tk.StringVar(value="0")
        self.stat_high = tk.StringVar(value="0")
        self.stat_medium = tk.StringVar(value="0")
        self.stat_mode = tk.StringVar(value="no scan yet")
        self.page = "rankings"
        self.watch_path = DOCUMENTS / "watchlist.csv"
        self.fight_rows: dict[str, tk.Frame] = {}
        self.tab_chips: dict[str, Chip] = {}
        self.parse_items: list[dict[str, str]] = []
        self.selected_index = -1
        self._syncing_selection = False
        self._rebuilding_parses = False
        self._load_current = 0
        self._load_total = 1
        self._load_anim = 0.0
        self.load_text = tk.StringVar(value="")
        self.load_pct = tk.StringVar(value="")

        self._ensure_user_files()
        self._build_style()
        self._build()
        self._bind()
        self._load_initial_sheet()

    def _load_icon(self) -> None:
        if not ICON.exists():
            return
        try:
            raw = tk.PhotoImage(file=str(ICON))
            self._icon = raw.subsample(2, 2) if raw.width() > 128 else raw
            self.root.iconphoto(True, self._icon)
        except tk.TclError:
            self._icon = None

    def _ensure_user_files(self) -> None:
        APP_SUPPORT.mkdir(parents=True, exist_ok=True)
        DOCUMENTS.mkdir(parents=True, exist_ok=True)
        old_config = OLD_APP_SUPPORT / "config.json"
        if not CONFIG_PATH.exists() and old_config.exists():
            CONFIG_PATH.write_text(old_config.read_text(encoding="utf-8"), encoding="utf-8")
        config = {}
        if CONFIG_PATH.exists():
            try:
                config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                config = {}
        token = config.get("token") or os.environ.get("COURT_LISTENER_TOKEN", "")
        self.token_var.set(token)
        out_dir = Path(config.get("out_dir") or (DOCUMENTS / "output"))
        self.out_var.set(str(out_dir))
        saved_watch = Path(config.get("watchlist") or self.watch_path)
        self.watch_path = saved_watch
        old_watch = OLD_DOCUMENTS / "watchlist.csv"
        if not self.watch_path.exists() and old_watch.exists():
            self.watch_path.parent.mkdir(parents=True, exist_ok=True)
            self.watch_path.write_text(old_watch.read_text(encoding="utf-8"), encoding="utf-8")
        if not self.watch_path.exists() and EXAMPLE_WATCHLIST.exists():
            self.watch_path.write_text(EXAMPLE_WATCHLIST.read_text(encoding="utf-8"), encoding="utf-8")

    def _save_config(self) -> None:
        APP_SUPPORT.mkdir(parents=True, exist_ok=True)
        payload = {
            "token": self.token_var.get().strip(),
            "out_dir": self.out_var.get().strip(),
            "watchlist": str(self.watch_path),
        }
        CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "WCL.Treeview",
            background=ROW,
            fieldbackground=ROW,
            foreground=TEXT,
            bordercolor=LINE,
            rowheight=30,
            font=self.ui,
        )
        style.configure(
            "WCL.Treeview.Heading",
            background="#0f0f0f",
            foreground="#ffffff",
            relief="flat",
            font=self.ui_bold,
        )
        style.map(
            "WCL.Treeview",
            background=[("selected", "#1b4332")],
            foreground=[("selected", "#ffffff")],
        )
        style.map(
            "WCL.Treeview.Heading",
            background=[("active", "#1a1a1a")],
            foreground=[("active", "#ffffff")],
        )
        style.configure(
            "WCL.Vertical.TScrollbar",
            background="#2a2a2a",
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=TEXT,
        )
        style.configure(
            "WCL.Horizontal.TScrollbar",
            background="#2a2a2a",
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=TEXT,
        )
        style.configure(
            "Load.Horizontal.TProgressbar",
            troughcolor="#1a1a1a",
            background=GREEN,
            bordercolor="#1a1a1a",
            lightcolor=GREEN,
            darkcolor=GREEN_DK,
            thickness=16,
        )

    def _build(self) -> None:
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True)
        self._build_topbar(shell)
        self._build_report_header(shell)

        body = tk.Frame(shell, bg=BG)
        body.pack(fill="both", expand=True)
        self._build_fight_list(body)

        main = tk.Frame(body, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self._build_tabs(main)

        self.pages: dict[str, tk.Frame] = {
            "rankings": tk.Frame(main, bg=BG),
            "table": tk.Frame(main, bg=BG),
            "events": tk.Frame(main, bg=BG),
            "watchlist": tk.Frame(main, bg=BG),
            "setup": tk.Frame(main, bg=BG),
        }
        self._build_rankings(self.pages["rankings"])
        self._build_table(self.pages["table"])
        self._build_events(self.pages["events"])
        self._build_watchlist(self.pages["watchlist"])
        self._build_setup(self.pages["setup"])
        self.show_page("rankings")

        footer = tk.Frame(shell, bg=TOP, pady=6)
        footer.pack(fill="x", side="bottom")
        tk.Label(
            footer,
            textvariable=self.status,
            bg=TOP,
            fg=MUTED,
            font=self.ui_small,
            anchor="w",
        ).pack(fill="x", padx=16)

    def _build_topbar(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=TOP, pady=8)
        bar.pack(fill="x")
        left = tk.Frame(bar, bg=TOP)
        left.pack(side="left", padx=14)
        icon = getattr(self, "_icon", None)
        if icon is not None:
            tk.Label(left, image=icon, bg=TOP).pack(side="left", padx=(0, 10))
        tk.Label(left, text=__app_name__, bg=TOP, fg="#ffffff", font=self.display).pack(side="left")
        tk.Label(
            left,
            text=f"v{__version__}",
            bg=TOP,
            fg=GREEN,
            font=self.ui_bold,
        ).pack(side="left", padx=(10, 0))

        actions = tk.Frame(bar, bg=TOP)
        actions.pack(side="right", padx=14)
        self.btn_excel = Chip(actions, "Open workbook", self.open_workbook, kind="secondary")
        self.btn_excel.pack(side="left", padx=(0, 8))
        self.btn_demo = Chip(actions, "Run demo scan", self.run_demo, kind="secondary")
        self.btn_demo.pack(side="left", padx=(0, 8))
        self.btn_live = Chip(actions, "Run live scan", self.run_live, kind="primary")
        self.btn_live.pack(side="left")

        search = tk.Frame(bar, bg=TOP)
        search.pack(side="right", padx=(0, 18))
        tk.Label(search, text="Search", bg=TOP, fg="#ffffff", font=self.ui_bold).pack(side="left", padx=(0, 8))
        entry = tk.Entry(
            search,
            textvariable=self.search_var,
            bg=SEARCH_BG,
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=self.ui,
            width=28,
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=GREEN,
        )
        entry.pack(side="left", ipady=7)
        self.search_var.trace_add("write", lambda *_: self.refresh_sheet())

    def _build_report_header(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=PANEL, pady=10)
        header.pack(fill="x")
        tk.Label(
            header,
            text="Public docket screening  ·  not a tax-evasion finding",
            bg=PANEL,
            fg="#ffffff",
            font=self.ui_bold,
        ).pack(anchor="w", padx=16)
        stats = tk.Frame(header, bg=PANEL)
        stats.pack(fill="x", padx=16, pady=(8, 2))
        self._stat(stats, "Scored", self.stat_scored, TEXT)
        self._stat(stats, "Flagged", self.stat_flagged, UNCOMMON)
        self._stat(stats, "High", self.stat_high, LEGENDARY)
        self._stat(stats, "Medium", self.stat_medium, EPIC)
        self._stat(stats, "Mode", self.stat_mode, MUTED)
        legend = tk.Frame(header, bg=PANEL)
        legend.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(legend, text="Parse", bg=PANEL, fg=MUTED, font=self.ui_small).pack(side="left", padx=(0, 10))
        for label, color in (
            ("100", "#e6cc80"),
            ("95", "#ff8000"),
            ("75", "#a335ee"),
            ("50", "#0070dd"),
            ("25", "#1eff00"),
            ("0", "#9d9d9d"),
        ):
            swatch = tk.Frame(legend, bg=color, width=12, height=12)
            swatch.pack(side="left", padx=(0, 4))
            swatch.pack_propagate(False)
            tk.Label(legend, text=label, bg=PANEL, fg=color, font=self.ui_small).pack(side="left", padx=(0, 12))

        self.load_wrap = tk.Frame(header, bg=PANEL)
        load_row = tk.Frame(self.load_wrap, bg=PANEL)
        load_row.pack(fill="x", padx=16, pady=(8, 4))
        tk.Label(
            load_row,
            textvariable=self.load_text,
            bg=PANEL,
            fg="#ffffff",
            font=self.ui_bold,
            anchor="w",
        ).pack(side="left")
        tk.Label(
            load_row,
            textvariable=self.load_pct,
            bg=PANEL,
            fg=GREEN,
            font=self.ui_bold,
        ).pack(side="right")
        self.load_canvas = tk.Canvas(
            self.load_wrap,
            height=18,
            bg=PARSE_TRACK,
            highlightthickness=0,
            bd=0,
        )
        self.load_canvas.pack(fill="x", padx=16, pady=(0, 8))

    def _stat(self, parent: tk.Frame, label: str, value: tk.StringVar, color: str) -> None:
        box = tk.Frame(parent, bg=PANEL)
        box.pack(side="left", padx=(0, 28))
        tk.Label(box, text=label, bg=PANEL, fg=MUTED, font=self.ui_small).pack(anchor="w")
        tk.Label(box, textvariable=value, bg=PANEL, fg=color, font=self.ui_bold).pack(anchor="w")

    def _build_fight_list(self, parent: tk.Frame) -> None:
        rail = tk.Frame(parent, bg=RAIL, width=230)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        tk.Label(
            rail,
            text="Fights",
            bg=RAIL,
            fg="#ffffff",
            font=self.ui_bold,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(14, 8))
        self.fight_host = tk.Frame(rail, bg=RAIL)
        self.fight_host.pack(fill="both", expand=True, padx=8)
        self._paint_fight_list()
        tk.Label(
            rail,
            text="HIGH / MEDIUM rows are review leads, same idea as a wipe that still needs a look.",
            bg=RAIL,
            fg=MUTED,
            font=self.ui_small,
            wraplength=200,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=14, pady=14)

    def _paint_fight_list(self) -> None:
        for child in self.fight_host.winfo_children():
            child.destroy()
        self.fight_rows.clear()
        counts = self._band_counts()
        for key, label in FIGHTS:
            count = counts.get(key, 0)
            active = self.filter_band.get() == key
            row = tk.Frame(self.fight_host, bg="#1b3d1b" if active else RAIL, cursor="hand2")
            row.pack(fill="x", pady=2)
            color = BAND_FG.get(key, TEXT if key in {"ALL", "FLAGGED"} else TEXT)
            if key == "FLAGGED":
                color = UNCOMMON
            elif key == "ALL":
                color = "#ffffff"
            name = tk.Label(row, text=label, bg=row["bg"], fg=color, font=self.ui_bold, anchor="w")
            name.pack(side="left", padx=(10, 4), pady=8)
            num = tk.Label(row, text=str(count), bg=row["bg"], fg="#ffffff", font=self.ui_bold)
            num.pack(side="right", padx=10)
            for widget in (row, name, num):
                widget.bind("<Button-1>", lambda _e, k=key: self._select_fight(k))
            self.fight_rows[key] = row

    def _select_fight(self, key: str) -> None:
        self.filter_band.set(key)
        self.refresh_sheet()
        self._paint_fight_list()

    def _band_counts(self) -> dict[str, int]:
        counts = {"ALL": len(self.rows), "FLAGGED": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
        for row in self.rows:
            band = row.get("risk_band", "INFO") or "INFO"
            counts[band] = counts.get(band, 0) + 1
            if band in {"HIGH", "MEDIUM"}:
                counts["FLAGGED"] += 1
        return counts

    def _build_tabs(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=TOP)
        bar.pack(fill="x")
        for key, label in TABS:
            chip = Chip(bar, label, lambda k=key: self.show_page(k), kind="tab", compact=True)
            chip.configure(font=self.tab_font)
            chip.pack(side="left", padx=(0, 2), pady=0)
            self.tab_chips[key] = chip
        self._paint_tabs()

    def _paint_tabs(self) -> None:
        for key, chip in self.tab_chips.items():
            chip.configure(kind="tab-on" if key == self.page else "tab")

    def show_page(self, name: str) -> None:
        self.page = name
        for key, frame in self.pages.items():
            frame.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self._paint_tabs()

    def _build_rankings(self, parent: tk.Frame) -> None:
        stage = tk.Frame(parent, bg=BG)
        stage.pack(fill="both", expand=True)

        header = tk.Frame(stage, bg="#0f0f0f")
        header.pack(fill="x")
        headers: tuple[tuple[str, int, str], ...] = (
            ("#", 44, "e"),
            ("Parse", 236, "w"),
            ("Subject", 200, "w"),
            ("Case", 280, "w"),
            ("Amount", 110, "e"),
            ("Court", 170, "w"),
            ("Ended", 100, "w"),
        )
        for text, width, side in headers:
            tk.Label(
                header,
                text=text,
                bg="#0f0f0f",
                fg="#ffffff",
                font=self.ui_bold,
                width=width // 8,
                anchor="e" if side == "e" else "w",
            ).pack(side="left", padx=6, pady=8)

        list_wrap = tk.Frame(stage, bg=BG)
        list_wrap.pack(fill="both", expand=True)
        self.parse_canvas = tk.Canvas(list_wrap, bg=BG, highlightthickness=0, bd=0)
        scroll = tk.Scrollbar(
            list_wrap,
            orient="vertical",
            command=self.parse_canvas.yview,
            bg="#2a2a2a",
            troughcolor=BG,
            activebackground=GREEN,
            highlightthickness=0,
            bd=0,
            width=12,
        )
        self.parse_canvas.configure(yscrollcommand=scroll.set)
        self.parse_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._parse_canvas_width = 0
        self._parse_redraw_job = None
        self.parse_canvas.bind("<Configure>", self._on_parse_canvas_configure)
        self.parse_canvas.bind("<MouseWheel>", self._on_parse_wheel)
        self.parse_canvas.bind("<Button-4>", lambda e: self.parse_canvas.yview_scroll(-1, "units"))
        self.parse_canvas.bind("<Button-5>", lambda e: self.parse_canvas.yview_scroll(1, "units"))

        self.loading_overlay = tk.Frame(list_wrap, bg="#111111")
        overlay_inner = tk.Frame(self.loading_overlay, bg="#111111")
        overlay_inner.place(relx=0.5, rely=0.4, anchor="center")
        tk.Label(
            overlay_inner,
            text="Scanning public dockets",
            bg="#111111",
            fg="#ffffff",
            font=self.display,
        ).pack()
        tk.Label(
            overlay_inner,
            textvariable=self.load_text,
            bg="#111111",
            fg=MUTED,
            font=self.ui,
        ).pack(pady=(8, 14))
        self.overlay_canvas = tk.Canvas(
            overlay_inner,
            width=420,
            height=22,
            bg=PARSE_TRACK,
            highlightthickness=0,
            bd=0,
        )
        self.overlay_canvas.pack()
        tk.Label(
            overlay_inner,
            textvariable=self.load_pct,
            bg="#111111",
            fg=GREEN,
            font=self.ui_bold,
        ).pack(pady=(8, 0))

        event_bar = tk.Frame(parent, bg=PANEL)
        event_bar.pack(fill="x")
        tk.Label(
            event_bar,
            text="Selected parse",
            bg=PANEL,
            fg="#ffffff",
            font=self.ui_bold,
        ).pack(anchor="w", padx=12, pady=(8, 4))
        self.narrative = tk.Text(
            event_bar,
            bg="#141414",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=self.mono,
            wrap="word",
            height=9,
            highlightthickness=1,
            highlightbackground=LINE,
            padx=12,
            pady=10,
        )
        self.narrative.pack(fill="x", padx=12, pady=(0, 10))
        self.narrative.insert("1.0", "Select a parse to read the screening narrative.")
        self.narrative.configure(state="disabled")

    def _build_table(self, parent: tk.Frame) -> None:
        sheet_wrap = tk.Frame(parent, bg=LINE)
        sheet_wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            sheet_wrap,
            columns=COLUMNS,
            show="headings",
            style="WCL.Treeview",
            selectmode="browse",
        )
        for col in COLUMNS:
            self.tree.heading(col, text=HEADINGS[col], command=lambda c=col: self._sort_by(c))
            anchor = "center" if col in {"risk_band", "risk_score", "review_priority"} else "w"
            self.tree.column(col, width=COL_WIDTHS[col], minwidth=70, stretch=False, anchor=anchor)
        yscroll = ttk.Scrollbar(sheet_wrap, orient="vertical", command=self.tree.yview, style="WCL.Vertical.TScrollbar")
        xscroll = ttk.Scrollbar(
            sheet_wrap, orient="horizontal", command=self.tree.xview, style="WCL.Horizontal.TScrollbar"
        )
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        sheet_wrap.grid_rowconfigure(0, weight=1)
        sheet_wrap.grid_columnconfigure(0, weight=1)
        for band, fg in BAND_FG.items():
            self.tree.tag_configure(band, background=BAND_BG[band], foreground=fg)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)

    def _on_parse_canvas_configure(self, event) -> None:
        if event.width > 1:
            self._parse_canvas_width = event.width

    def _on_parse_wheel(self, event) -> None:
        delta = event.delta
        if abs(delta) < 50:
            steps = -1 * int(delta)
        else:
            steps = int(-1 * (delta / 120))
        if steps:
            self.parse_canvas.yview_scroll(steps, "units")

    def _build_events(self, parent: tk.Frame) -> None:
        tk.Label(
            parent,
            text="Events",
            bg=BG,
            fg="#ffffff",
            font=self.ui_bold,
        ).pack(anchor="w", padx=16, pady=(12, 6))
        self.events_full = tk.Text(
            parent,
            bg="#141414",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=self.mono,
            wrap="word",
            highlightthickness=1,
            highlightbackground=LINE,
            padx=14,
            pady=12,
        )
        self.events_full.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.events_full.insert("1.0", "Select a rankings row to load the full lead narrative.")
        self.events_full.configure(state="disabled")

    def _build_watchlist(self, parent: tk.Frame) -> None:
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(
            head,
            text="Watchlist CSV  ·  name, entity_type, aliases, notes",
            bg=BG,
            fg="#ffffff",
            font=self.ui_bold,
        ).pack(side="left")
        Chip(head, "Save watchlist", self.save_watchlist, kind="primary", compact=True).pack(side="right")
        Chip(head, "Load CSV…", self.load_watchlist_file, kind="secondary", compact=True).pack(
            side="right", padx=(0, 8)
        )
        self.watch_text = tk.Text(
            parent,
            bg="#141414",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=self.mono,
            wrap="none",
            highlightthickness=1,
            highlightbackground=LINE,
            padx=12,
            pady=10,
        )
        self.watch_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        if self.watch_path.exists():
            self.watch_text.insert("1.0", self.watch_path.read_text(encoding="utf-8"))

    def _build_setup(self, parent: tk.Frame) -> None:
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(wrap, text="CourtListener token", bg=BG, fg="#ffffff", font=self.ui_bold).pack(anchor="w")
        tk.Entry(
            wrap,
            textvariable=self.token_var,
            bg=SEARCH_BG,
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=self.mono,
            show="•",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=GREEN,
        ).pack(fill="x", ipady=8, pady=(6, 8))
        tk.Label(
            wrap,
            text="Optional. Live mode works without one, just slower.",
            bg=BG,
            fg=MUTED,
            font=self.ui_small,
        ).pack(anchor="w", pady=(0, 16))

        tk.Label(wrap, text="Max dockets per name", bg=BG, fg="#ffffff", font=self.ui_bold).pack(anchor="w")
        tk.Entry(
            wrap,
            textvariable=self.max_var,
            bg=SEARCH_BG,
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=self.ui,
            width=8,
            highlightthickness=1,
            highlightbackground=LINE,
        ).pack(anchor="w", ipady=8, pady=(6, 16))

        tk.Label(wrap, text="Spreadsheet folder", bg=BG, fg="#ffffff", font=self.ui_bold).pack(anchor="w")
        out_row = tk.Frame(wrap, bg=BG)
        out_row.pack(fill="x", pady=(6, 16))
        tk.Entry(
            out_row,
            textvariable=self.out_var,
            bg=SEARCH_BG,
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=self.mono,
            highlightthickness=1,
            highlightbackground=LINE,
        ).pack(side="left", fill="x", expand=True, ipady=8)
        Chip(out_row, "Choose folder", self.choose_out, kind="secondary", compact=True).pack(side="left", padx=(8, 0))

        actions = tk.Frame(wrap, bg=BG)
        actions.pack(anchor="w", pady=(4, 16))
        Chip(actions, "Reveal in Finder", self.reveal_output, kind="secondary").pack(side="left", padx=(0, 8))
        Chip(actions, "Open workbook", self.open_workbook, kind="primary").pack(side="left")

        tk.Label(
            wrap,
            text="Flags are leads for a human. Lawful settlements, including IRC §104(a)(2) awards, will appear.",
            bg=BG,
            fg=MUTED,
            font=self.ui_small,
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(12, 0))

    def _bind(self) -> None:
        self.root.bind("<Command-r>", lambda _e: self.run_demo())
        self.root.bind("<Command-l>", lambda _e: self.run_live())
        self.root.bind("<Command-s>", lambda _e: self.save_watchlist())
        self.root.bind("<Command-o>", lambda _e: self.open_workbook())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        self._save_config()
        self.root.destroy()

    def _load_initial_sheet(self) -> None:
        out_csv = Path(self.out_var.get()) / "settlement_watch_leads.csv"
        for candidate in (out_csv, SAMPLE_CSV):
            if candidate.exists():
                try:
                    self.rows = load_rows_csv(candidate)
                    self.refresh_sheet()
                    self.status.set(f"Loaded {len(self.rows)} row(s) from {candidate}. Run a scan to refresh.")
                    return
                except (OSError, csv.Error):
                    continue
        self.status.set("Ready. Run a demo scan to fill the spreadsheet.")

    def visible_rows(self) -> list[dict[str, str]]:
        band = self.filter_band.get()
        needle = self.search_var.get().strip().lower()
        out: list[dict[str, str]] = []
        for row in self.rows:
            risk = row.get("risk_band", "INFO")
            if band == "FLAGGED" and risk not in {"HIGH", "MEDIUM"}:
                continue
            if band not in {"ALL", "FLAGGED"} and risk != band:
                continue
            if needle:
                hay = " ".join(row.get(col, "") for col in COLUMNS).lower()
                if needle not in hay:
                    continue
            out.append(row)
        return out

    def refresh_sheet(self) -> None:
        self.tree.delete(*self.tree.get_children())
        visible = self.visible_rows()
        for index, row in enumerate(visible):
            values = [row.get(col, "") for col in COLUMNS]
            band = row.get("risk_band", "INFO") or "INFO"
            self.tree.insert("", "end", iid=str(index), values=values, tags=(band,))
        self._rebuild_parses(visible)
        self._update_stats()
        if hasattr(self, "fight_host"):
            self._paint_fight_list()

    def _rebuild_parses(self, visible: list[dict[str, str]]) -> None:
        if getattr(self, "_rebuilding_parses", False):
            return
        self._rebuilding_parses = True
        try:
            self.parse_items = visible
            self.parse_canvas.delete("row")
            width = max(self._parse_canvas_width, 900)
            for index, row in enumerate(visible):
                self._draw_parse_row(index, row, width)
            height = max(len(visible) * PARSE_ROW_H, 1)
            self.parse_canvas.configure(scrollregion=(0, 0, width, height))
            if visible and not (0 <= self.selected_index < len(visible)):
                self.selected_index = 0
            if visible and 0 <= self.selected_index < len(visible):
                self._set_narrative(self._narrative_for(visible[self.selected_index]))
        finally:
            self._rebuilding_parses = False

    def _draw_parse_row(self, index: int, row: dict[str, str], width: int) -> None:
        score = parse_score(row)
        color = parse_color(score)
        y = index * PARSE_ROW_H
        bg = "#1b3d1b" if index == self.selected_index else (ROW_ALT if index % 2 else ROW)
        tag = f"row-{index}"
        tags = ("row", tag)
        self.parse_canvas.create_rectangle(0, y, width, y + PARSE_ROW_H, fill=bg, outline="", tags=tags)
        cy = y + PARSE_ROW_H / 2
        self.parse_canvas.create_text(36, cy, text=str(index + 1), fill=MUTED, anchor="e", font=self.ui_bold, tags=tags)
        self.parse_canvas.create_text(84, cy, text=str(score), fill=color, anchor="e", font=self.parse_num, tags=tags)
        bx, by, bw, bh = 96, y + 9, 168, 22
        self.parse_canvas.create_rectangle(bx, by, bx + bw, by + bh, fill=PARSE_TRACK, outline="", tags=tags)
        fill = max(6, int(bw * score / 100))
        self.parse_canvas.create_rectangle(bx, by, bx + fill, by + bh, fill=color, outline="", tags=tags)
        self.parse_canvas.create_text(
            bx + bw / 2, cy, text=str(score), fill=parse_label_color(score), font=self.ui_bold, tags=tags
        )
        self.parse_canvas.create_text(
            280, cy, text=row.get("subject_name", ""), fill=color, anchor="w", font=self.ui_bold, tags=tags
        )
        self.parse_canvas.create_text(
            500, cy, text=row.get("case_name", ""), fill=TEXT, anchor="w", font=self.ui, tags=tags
        )
        self.parse_canvas.create_text(
            900, cy, text=format_amount(row.get("amount_parsed_usd", "")), fill=color, anchor="e", font=self.ui_bold, tags=tags
        )
        self.parse_canvas.create_text(
            920, cy, text=row.get("court", ""), fill=MUTED, anchor="w", font=self.ui_small, tags=tags
        )
        self.parse_canvas.create_text(
            1140,
            cy,
            text=row.get("date_terminated") or row.get("date_filed") or "open",
            fill=MUTED,
            anchor="w",
            font=self.ui_small,
            tags=tags,
        )
        self.parse_canvas.tag_bind(tag, "<Button-1>", lambda _e, i=index: self._select_parse(i))
        self.parse_canvas.tag_bind(
            tag, "<Double-Button-1>", lambda _e, i=index: self._open_parse(i)
        )

    def _open_parse(self, index: int) -> None:
        self._select_parse(index)
        self._on_double_click()

    def _select_parse(self, index: int, scroll: bool = True) -> None:
        visible = self.visible_rows()
        if index < 0 or index >= len(visible) or self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            self.selected_index = index
            self._rebuild_parses(visible)
            if str(index) in self.tree.get_children():
                self.tree.selection_set(str(index))
                self.tree.focus(str(index))
            if scroll and visible:
                top = index * PARSE_ROW_H
                total = max(len(visible) * PARSE_ROW_H, 1)
                self.parse_canvas.yview_moveto(min(top / total, 1.0))
        finally:
            self._syncing_selection = False

    def _update_stats(self) -> None:
        counts = self._band_counts()
        self.stat_scored.set(str(counts["ALL"]))
        self.stat_flagged.set(str(counts["FLAGGED"]))
        self.stat_high.set(str(counts["HIGH"]))
        self.stat_medium.set(str(counts["MEDIUM"]))
        self.stat_mode.set(self.mode or "loaded file")
        if self.rows:
            self.status.set(
                f"{len(self.visible_rows())} shown · {len(self.rows)} scored · {counts['FLAGGED']} flagged"
                + (f" · {self.mode}" if self.mode else "")
            )

    def _sort_by(self, column: str) -> None:
        reverse = getattr(self, "_sort_desc", False) and getattr(self, "_sort_col", "") == column
        self._sort_col = column
        self._sort_desc = not reverse

        def key(row: dict[str, str]):
            value = row.get(column, "")
            if column == "risk_score":
                try:
                    return int(value)
                except ValueError:
                    return -1
            return value.lower()

        self.rows.sort(key=key, reverse=self._sort_desc)
        self.refresh_sheet()

    def _selected_row(self) -> dict[str, str] | None:
        visible = self.visible_rows()
        if 0 <= self.selected_index < len(visible):
            return visible[self.selected_index]
        selection = self.tree.selection()
        if not selection:
            return None
        index = int(selection[0])
        if 0 <= index < len(visible):
            return visible[index]
        return None

    def _set_narrative(self, text: str) -> None:
        for widget in (self.narrative, self.events_full):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.configure(state="disabled")

    def _on_select(self, _event=None) -> None:
        if self._syncing_selection:
            return
        selection = self.tree.selection()
        if selection:
            try:
                self._select_parse(int(selection[0]), scroll=True)
                return
            except ValueError:
                pass
        row = self._selected_row()
        if row is None:
            return
        self._set_narrative(self._narrative_for(row))

    def _narrative_for(self, row: dict[str, str]) -> str:
        lead_id = row.get("lead_id", "")
        for item in self.results:
            key = f"{item.watch_name}|{item.docket.docket_id or item.docket.docket_number}"
            if key == lead_id:
                return lead_narrative(item)
        parts = [
            f"Subject: {row.get('subject_name', '')} ({row.get('subject_type', '')})",
            f"Case: {row.get('case_name', '')}",
            f"Court: {row.get('court', '')}  Docket: {row.get('docket_number', '')}",
            f"Score: {row.get('risk_score', '')}  Band: {row.get('risk_band', '')}  Priority: {row.get('review_priority', '')}",
            f"Amount: {row.get('amount_parsed_usd', '') or 'n/a'}",
            f"Flags: {row.get('flag_codes', '') or 'none'}",
            "",
            row.get("flag_details", ""),
            "",
            row.get("source_url", ""),
        ]
        return "\n".join(part for part in parts if part is not None)

    def _on_double_click(self, _event=None) -> None:
        row = self._selected_row()
        if not row:
            return
        url = row.get("source_url", "").strip()
        if url.startswith("http"):
            webbrowser.open(url)

    def save_watchlist(self) -> None:
        text = self.watch_text.get("1.0", "end-1c")
        write_watchlist_text(self.watch_path, text)
        try:
            names = [target.name for target in load_watchlist(self.watch_path)]
        except (OSError, ValueError) as exc:
            messagebox.showerror(__app_name__, f"Watchlist is not valid yet:\n{exc}")
            return
        self._save_config()
        self.status.set(f"Saved {len(names)} name(s) to {self.watch_path}")

    def load_watchlist_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open watchlist CSV",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        self.watch_path = Path(path)
        self.watch_text.delete("1.0", "end")
        self.watch_text.insert("1.0", self.watch_path.read_text(encoding="utf-8"))
        self._save_config()
        self.status.set(f"Loaded watchlist {self.watch_path}")

    def choose_out(self) -> None:
        path = filedialog.askdirectory(title="Spreadsheet folder", initialdir=self.out_var.get())
        if path:
            self.out_var.set(path)
            self._save_config()

    def reveal_output(self) -> None:
        dest = Path(self.out_var.get())
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(dest)], check=False)

    def open_workbook(self) -> None:
        xlsx = self.paths.get("xlsx") or Path(self.out_var.get()) / "settlement_watch_leads.xlsx"
        if not Path(xlsx).exists():
            sample = ROOT / "sample-output" / "settlement_watch_leads.xlsx"
            if sample.exists():
                xlsx = sample
            else:
                messagebox.showinfo(__app_name__, "No workbook yet. Run a scan first.")
                return
        subprocess.run(["open", str(xlsx)], check=False)

    def run_demo(self) -> None:
        self._start_scan(demo=True)

    def run_live(self) -> None:
        self._start_scan(demo=False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.btn_demo.configure(state=state)
        self.btn_live.configure(state=state)

    def _show_loading(self, message: str, current: int = 0, total: int = 1) -> None:
        self._load_current = current
        self._load_total = max(total, 1)
        fraction = current / self._load_total
        self._load_anim = fraction
        self.load_text.set(message)
        self.load_pct.set(f"{int(fraction * 100)}%")
        if not self.load_wrap.winfo_ismapped():
            self.load_wrap.pack(fill="x")
        self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._draw_loading_bars(fraction)
        self.status.set(message)
        self.root.update_idletasks()

    def _hide_loading(self) -> None:
        self.load_wrap.pack_forget()
        self.loading_overlay.place_forget()

    def _draw_loading_bars(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, fraction))
        for canvas in (self.load_canvas, self.overlay_canvas):
            width = canvas.winfo_width()
            if width <= 1:
                width = 420
            height = int(canvas.cget("height") or 18)
            canvas.delete("all")
            canvas.create_rectangle(0, 0, width, height, fill=PARSE_TRACK, outline="")
            fill = max(8, int(width * fraction)) if fraction > 0 else 0
            if fill:
                canvas.create_rectangle(0, 0, fill, height, fill=GREEN, outline="")

    def _on_progress(self, message: str, current: int | None = None, total: int | None = None) -> None:
        if current is not None:
            self._load_current = current
        if total is not None:
            self._load_total = max(total, 1)
        fraction = self._load_current / self._load_total
        self._load_anim = max(self._load_anim, fraction)
        self.load_text.set(message)
        self.load_pct.set(f"{int(self._load_anim * 100)}%")
        self.status.set(message)
        self._draw_loading_bars(self._load_anim)

    def _tick_loading(self) -> None:
        if not self._busy:
            return
        ceiling = min(0.97, (self._load_current + 0.85) / self._load_total)
        if self._load_anim < ceiling:
            self._load_anim = min(ceiling, self._load_anim + 0.012)
            self.load_pct.set(f"{int(self._load_anim * 100)}%")
            self._draw_loading_bars(self._load_anim)
        self.root.after(90, self._tick_loading)

    def _start_scan(self, *, demo: bool) -> None:
        if self._busy:
            return
        self.save_watchlist()
        try:
            names = load_watchlist(self.watch_path)
        except (OSError, ValueError) as exc:
            messagebox.showerror(__app_name__, str(exc))
            return
        try:
            max_per_name = int(self.max_var.get().strip() or "25")
        except ValueError:
            messagebox.showerror(__app_name__, "Max dockets per name must be a number.")
            return
        out_dir = Path(self.out_var.get().strip() or (DOCUMENTS / "output"))
        self.out_var.set(str(out_dir))
        self._save_config()
        self._set_busy(True)
        kind = "demo" if demo else "live"
        self.show_page("rankings")
        self._show_loading(
            f"Starting {kind} scan of {len(names)} name(s)…",
            current=0,
            total=max(len(names), 1),
        )
        self.root.after(90, self._tick_loading)

        def progress(msg: str, current: int | None = None, total: int | None = None) -> None:
            self.root.after(0, lambda m=msg, c=current, t=total: self._on_progress(m, c, t))

        def work() -> None:
            try:
                scan = run_scan(
                    self.watch_path,
                    out_dir,
                    demo=demo,
                    token=self.token_var.get().strip(),
                    max_per_name=max_per_name,
                    progress=progress,
                )
                self.root.after(0, lambda: self._on_scan_done(scan, None))
            except Exception as exc:  # noqa: BLE001 — surface any scan failure in the UI
                self.root.after(0, lambda: self._on_scan_done(None, exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_scan_done(self, scan: ScanResult | None, error: BaseException | None) -> None:
        self._set_busy(False)
        self._hide_loading()
        if error is not None:
            messagebox.showerror(__app_name__, str(error))
            self.status.set(f"Scan failed: {error}")
            return
        assert scan is not None
        self.results = scan.results
        self.rows = scan.rows
        self.paths = scan.paths
        self.mode = scan.mode
        self.selected_index = 0
        try:
            self.refresh_sheet()
        except Exception as exc:  # noqa: BLE001 — never leave the window disabled
            messagebox.showerror(__app_name__, f"Scan finished but the report view failed:\n{exc}")
            self.status.set(f"Scan finished. Spreadsheet: {scan.paths['xlsx']}")
            return
        flagged = sum(1 for row in self.rows if row.get("risk_band") in {"HIGH", "MEDIUM"})
        self.status.set(f"Scored {len(self.rows)} · flagged {flagged} · {scan.paths['xlsx']}")


def run() -> None:
    app = SettlementWatchApp()
    app.root.mainloop()


if __name__ == "__main__":
    run()
