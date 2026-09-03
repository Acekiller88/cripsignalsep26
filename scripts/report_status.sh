#!/usr/bin/env bash
# =============================================================================
# report_status.sh – compact daily/weekly status report for the operator.
#
#   ./scripts/report_status.sh          # last 7 days
#   ./scripts/report_status.sh 14       # last 14 days
#
# Prints statistics, per-symbol breakdown, last signals, error counts and the
# health of the containers between ===== REPORT ===== markers.
# =============================================================================
set -u
cd "$(dirname "$0")/.."
DAYS="${1:-7}"
API="http://localhost:${API_PORT:-8000}"
LIB="python3 scripts/report_lib.py"

compose() { if docker compose version >/dev/null 2>&1; then docker compose "$@"; else docker-compose "$@"; fi; }
api() { curl -s -m 10 "$API$1" || true; }

echo "===== REPORT ====="
echo "time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')  window: last ${DAYS} days  commit: $(git rev-parse --short HEAD 2>/dev/null || echo n/a)"
echo
echo "## containers"
if command -v docker >/dev/null 2>&1; then compose ps --format '  {{.Name}}  {{.State}}  {{.Status}}' 2>/dev/null; else echo "  (docker not available)"; fi
echo
echo "## health"
echo "  $(api /health)"
echo
echo "## bot status"
api /api/status | $LIB status
echo
echo "## market snapshot"
api /api/market | $LIB market
echo
echo "## performance (all time)"
api /api/performance | $LIB performance
echo
echo "## breakdown (last ${DAYS} days)"
api "/api/performance/breakdown?days=${DAYS}" | $LIB breakdown
echo
echo "## last 10 signals"
api "/api/signals?limit=10&source=live" | $LIB signals
echo
echo "## active signals"
api /api/signals/active | $LIB signals
echo
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^crypto_backend$'; then
  echo "## errors / warnings in backend log (last 24h)"
  echo "  count: $(docker logs --since 24h crypto_backend 2>&1 | grep -cE 'ERROR|WARNING')"
  docker logs --since 24h crypto_backend 2>&1 | grep -E 'ERROR|WARNING' | tail -8 | sed 's/^/  /'
  echo
  echo "## resources"
  docker stats --no-stream --format '  {{.Name}}  cpu={{.CPUPerc}}  mem={{.MemUsage}}' 2>/dev/null
fi
df -h / | awk 'NR==2{print "  disk: "$3" used / "$2" ("$5")"}'
echo "===== END REPORT ====="
