#!/bin/zsh
# Buduje obraz mullid i (re)startuje kontener pod Apple `container`.
set -euo pipefail

MULLID=/Users/fran/projects/mullid
STATE=/Users/fran/.mullid   # klucz WireGuard, katalog relayow, state.json

if [[ ! -f "$STATE/wg.conf" ]]; then
  echo "brak $STATE/wg.conf — uruchom najpierw na hoscie: python3 setup.py" >&2
  exit 1
fi

container system start >/dev/null 2>&1 || true

echo "== build =="
container build -t mullid -f "$MULLID/Containerfile" "$MULLID"

echo "== restart =="
container stop mullid 2>/dev/null || true
container rm mullid 2>/dev/null || true

# Publikacja na 0.0.0.0 jest swiadoma: proxy nie sprawdza hasla, wiec kazdy
# w sieci lokalnej moze przez nie wyjsc na koncie Mullvad wlasciciela.
container run -d --name mullid \
  --dns 1.1.1.1 --dns 9.9.9.9 \
  --publish 0.0.0.0:8888:8888 \
  --publish 0.0.0.0:8889:8889 \
  --volume "$STATE:/root/.mullid" \
  --env MULLID_BIND=0.0.0.0 \
  --env MULLID_WIREPROXY_BIN=/usr/local/bin/wireproxy \
  mullid

echo "== status =="
container ls
