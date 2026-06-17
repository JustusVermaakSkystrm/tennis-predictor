#!/usr/bin/env bash
# Fetch bookmaker odds (Bet365 + Pinnacle closing) from tennis-data.co.uk into
# data/odds/, for the market / CLV benchmark. ATP: /{year}/{year}.xlsx,
# WTA: /{year}w/{year}.xlsx. Idempotent — re-run to refresh the current year.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/data/odds"
START="${1:-2019}"
END="${2:-2026}"
mkdir -p "$OUT"

ok=0; miss=0
for y in $(seq "$START" "$END"); do
  if curl -s -f --max-time 40 -o "$OUT/atp_$y.xlsx" "http://www.tennis-data.co.uk/$y/$y.xlsx"; then ok=$((ok+1)); else rm -f "$OUT/atp_$y.xlsx"; miss=$((miss+1)); fi
  if curl -s -f --max-time 40 -o "$OUT/wta_$y.xlsx" "http://www.tennis-data.co.uk/${y}w/$y.xlsx"; then ok=$((ok+1)); else rm -f "$OUT/wta_$y.xlsx"; miss=$((miss+1)); fi
done
echo "Odds: $ok files fetched, $miss missing -> $OUT"
