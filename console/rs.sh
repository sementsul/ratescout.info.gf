#!/usr/bin/env bash
# RateScout - interactive console rate monitor (macOS/Linux, built-in bash + curl).
# Keys: h heatmap, w watchlist, m movers; period 1/2/3 = 24h/7d/30d; r refresh, q quit.
# It only DOWNLOADS ready-made text pages from ratescout.ru and prints them. No install, no code from data.
# Source: https://ratescout.ru/cli/rs.sh
base="https://ratescout.ru/cli"; view="heat"; period="24h"
cleanup() { printf '\033[?25h'; clear; exit 0; }
trap cleanup INT
printf '\033[?25l'
while true; do
  if [ "$view" = "watch" ]; then p="watch"; else p="$view-$period"; fi
  clear
  curl -fsS --max-time 20 "$base/$p.txt" 2>/dev/null || echo "  no connection - press r to retry"
  IFS= read -rsn1 k
  case "$k" in
    h) view="heat" ;; w) view="watch" ;; m) view="movers" ;;
    1) period="24h" ;; 2) period="7d" ;; 3) period="30d" ;;
    q) cleanup ;;
  esac
done
