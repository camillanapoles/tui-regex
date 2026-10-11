#!/usr/bin/env bash
# Verificação de sintaxe de todos os userscripts do pacote.
set -euo pipefail
cd "$(dirname "$0")/.."
for f in userscripts/ushub.user.js userscripts/gist/*.user.js; do
  node --check "$f"
  echo "OK  $f"
done
