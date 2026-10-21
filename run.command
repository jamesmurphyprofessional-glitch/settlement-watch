#!/bin/bash
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt -q
python3 -m settlement_watch check --demo --out "./output"
echo
echo "Spreadsheet: $(pwd)/output/settlement_watch_leads.xlsx"
open "./output/settlement_watch_leads.xlsx" 2>/dev/null || true
