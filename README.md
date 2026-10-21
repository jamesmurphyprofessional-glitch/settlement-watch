# Roach Detector

Public-docket screening tool. You keep a CSV watchlist of people and companies. One command searches US public court records (CourtListener / RECAP), scores settlement-like activity against tax-characterization red flags, and writes a spreadsheet plus CSV/JSON that an analyst can import.

**This does not determine tax evasion.** It flags patterns for a human to review. Lawful settlements — including physical-injury awards excluded under IRC §104(a)(2) — will appear.

## Quick start

On a Mac, double-click **Roach Detector** in Applications. The window is a local spreadsheet: run a demo or live scan, then read and filter the rows in place. Workbooks still write to `~/Documents/Roach Detector/output/` for Excel or Numbers.

From Terminal:

```bash
cd settlement-watch
python3 -m pip install -r requirements.txt
python3 -m settlement_watch
python3 -m settlement_watch check --demo --out ./output
```

Open `output/settlement_watch_leads.xlsx`.

Live search (free CourtListener token recommended):

```bash
export COURT_LISTENER_TOKEN="your-token"
python3 -m settlement_watch check --watchlist watchlist.example.csv --out ./output
```

Get a token at [CourtListener API help](https://www.courtlistener.com/help/api/rest/).

## Watchlist CSV

```csv
name,entity_type,aliases,notes
Harbor Creek Holdings LLC,company,Harbor Creek Holdings; Harbor Creek,optional note
Maria Alvarez,person,,
```

## What you get in `--out`

| File | Use |
| --- | --- |
| `settlement_watch_leads.xlsx` | Analyst workbook (disclaimer, flagged sheet, all matches, field dictionary, narratives) |
| `settlement_watch_leads.csv` | UTF-8 CSV for Excel / Access / Tableau |
| `settlement_watch_flagged.csv` | MEDIUM and HIGH rows only |
| `settlement_watch_leads.json` | Machine-readable extract |
| `lead_narratives.txt` | Paste-ready write-ups |
| `field_dictionary.csv` | Column meanings |

## Honest limits

- Coverage is public RECAP/CourtListener, not a full PACER pull.
- Settlement amounts and tax characterization are often missing or sealed.
- Scores are weighted heuristics, not probabilities and not legal conclusions.
- The program does not connect to IRS systems (CIMIS, RRP, EFDS, MeF, SarGenXpress). See `IRS-INTEROP.txt`.

## License

MIT. CourtListener data remains subject to Free Law Project terms.


## Contact

James Murphy, jamesmurphyprofessional@gmail.com. More projects: https://huntingtondeveloper.pages.dev
