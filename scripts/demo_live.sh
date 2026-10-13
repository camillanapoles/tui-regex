#!/usr/bin/env bash
# Demo do servidor real (uvicorn) com curls — gera docs/evidence/live_server.txt.
# Uso: bash scripts/demo_live.sh [PY]
set -o pipefail
cd "$(dirname "$0")/.."
PY="${1:-python3}"
OUT=docs/evidence/live_server.txt
mkdir -p docs/evidence

"$PY" - <<'EOF' &
import uvicorn, os
os.chdir(os.path.dirname(os.path.abspath("team_builder"))) if False else None
from team_builder.api import create_app
from team_builder.llm import MockLLM
app = create_app(db_url="sqlite:///./evidence_live.db", llm=MockLLM(), god_secret="demo-secret")
uvicorn.run(app, host="0.0.0.0", port=8011, log_level="warning")
EOF
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT
sleep 4
BASE=http://localhost:8011
J() { "$PY" -c 'import sys,json; d=json.load(sys.stdin); print(*sys.argv[1:])' "$@" <<< "$(curl -s "$BASE$1")" 2>/dev/null || true; }

{
echo "════ LIVE SERVER EVIDENCE — $(date -u +%Y-%m-%dT%H:%M:%SZ) ════"
echo
echo "── 1) /health"
curl -s $BASE/health
echo; echo
echo "── 2) CONTINUITY: setar o estado da sessão (PUT /continuity/session/current)"
curl -s -X PUT $BASE/continuity/session/current -H 'Content-Type: application/json' -d '{
  "data": {
    "branch": "arena/01a0d0f0-tui-regex",
    "base_branch": "main",
    "last_commit": "299d332",
    "cursor": "continuidade-entregue",
    "next_steps": ["E1 tenancy", "E3 LLM real", "criar PR"],
    "evidence": ["docs/evidence/pytest_final.txt", "docs/evidence/live_server.txt"]
  }
}'
echo; echo
echo "── 3) CONTINUITY: RECUPERAR (GET) — set/recover via API"
curl -s $BASE/continuity/session/current
echo; echo
echo "── 4) CONTINUITY: kinds (registry da META-CLASSE)"
curl -s $BASE/continuity/kinds
echo; echo
echo "── 5) CONTINUITY: gate bloqueia kind desconhecido (403 deny-by-default)"
curl -s -o /dev/null -w "HTTP %{http_code} " -X PUT $BASE/continuity/hacker/x -H 'Content-Type: application/json' -d '{"data":{}}'
curl -s -X PUT $BASE/continuity/hacker/x -H 'Content-Type: application/json' -d '{"data":{}}'
echo; echo
echo "── 6) CONTINUITY: gate bloqueia key inválida (403) — %20 decodifica p/ espaço"
curl -s -X PUT "$BASE/continuity/kv/bad%20key!" -H 'Content-Type: application/json' -d '{"data":{"value":1}}'
echo; echo
echo "── 7) CONTINUITY: versionamento (409 em expected_version obsoleto)"
curl -s -X PUT $BASE/continuity/kv/ver -H 'Content-Type: application/json' -d '{"data":{"value":1}}' > /dev/null
curl -s -X PUT $BASE/continuity/kv/ver -H 'Content-Type: application/json' -d '{"data":{"value":2},"expected_version":9}'
echo; echo
echo "── 8) CONTINUITY: /gates/blocked mostra as violações"
curl -s $BASE/gates/blocked | head -c 700
echo; echo
echo "── 9) AGENT: Factory cria developer + work completo"
AGENT=$(curl -s -X POST $BASE/agents/ -H 'Content-Type: application/json' -d '{"spec":{"role":"developer","name":"Dev Live","responsibilities":["implementar"],"tools_needed":["uppercase"]}}' | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["agent_id"])')
echo "agent_id=$AGENT"
curl -s -X POST $BASE/agents/$AGENT/work -H 'Content-Type: application/json' -d '{"task":{"title":"Implementar feature","task_id":"task-live-1"}}' | head -c 500
echo; echo
echo "── 10) TOOL WASM: uppercase no sandbox (fuel real)"
curl -s -X POST $BASE/tools/uppercase/execute -H 'Content-Type: application/json' -d "{\"agent_id\":\"$AGENT\",\"params\":{\"text\":\"wasm live server\"}}"
echo; echo
echo "── 11) TOOL WASM: fuel exhaustion (fib 40, limite 5M)"
curl -s -X POST $BASE/tools/fibonacci/execute -H 'Content-Type: application/json' -d "{\"agent_id\":\"$AGENT\",\"params\":{\"n\":40}}"
echo; echo
echo "── 12) GOD sem credential (403) e com (201 forge 'double' + exec 21+21)"
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST $BASE/god/build-team -H 'Content-Type: application/json' -d '{"project_description":"x"}'
curl -s -X POST $BASE/god/tools/forge -H 'Content-Type: application/json' -H 'X-God-Mode: demo-secret' -d '{"name":"double","wat":"\n(module\n  (memory (export \"memory\") 1)\n  (func (export \"add\") (param i32 i32) (result i32)\n    local.get 0\n    local.get 1\n    i32.add)\n)\n","entrypoint":"add","param_names":["a","b"],"assigned_roles":["developer"]}' | head -c 300
echo
curl -s -X POST $BASE/tools/double/execute -H 'Content-Type: application/json' -d "{\"agent_id\":\"$AGENT\",\"params\":{\"a\":21,\"b\":21}}"
echo; echo
echo "── 13) CONTINUITY: stats finais"
curl -s $BASE/continuity/stats
echo
} > "$OUT" 2>&1

kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
rm -f evidence_live.db
echo "OK: $OUT"
tail -5 "$OUT"
