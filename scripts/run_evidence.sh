#!/usr/bin/env bash
# Regenera a evidência executável (quality + wasm + testes + cobertura).
# Uso: bash scripts/run_evidence.sh  (a partir da raiz do repo, venv ativado
# ou com PY pointing para o venv via $1)
set -o pipefail
cd "$(dirname "$0")/.."
PY="${1:-python3}"
{
echo "════ EVIDÊNCIA EXECUTÁVEL — $(date -u +%Y-%m-%dT%H:%M:%SZ) ════"
echo "Python: $($PY --version 2>&1)"
echo "Pacotes: wasmtime/$(pip show wasmtime 2>/dev/null | awk '/^Version/{print $2}') fastapi/$(pip show fastapi 2>/dev/null | awk '/^Version/{print $2}') pydantic/$(pip show pydantic 2>/dev/null | awk '/^Version/{print $2}') sqlalchemy/$(pip show sqlalchemy 2>/dev/null | awk '/^Version/{print $2}') instructor/$(pip show instructor 2>/dev/null | awk '/^Version/{print $2}') pytest/$(pip show pytest 2>/dev/null | awk '/^Version/{print $2}')"
echo
echo "── QUALITY: ruff check ──"
"$PY" -m ruff check team_builder tests scripts
echo
echo "── WASM VALIDATION: scripts/validate_wat.py ──"
"$PY" scripts/validate_wat.py
echo
echo "── SUITE UNIT ──"
"$PY" -m pytest tests/unit -q --junitxml=junit_unit.xml 2>&1 | tail -2
echo
echo "── SUITE INTEGRATION ──"
"$PY" -m pytest tests/integration -q --junitxml=junit_integration.xml 2>&1 | tail -2
echo
echo "── SUITE E2E ──"
"$PY" -m pytest tests/e2e -q --junitxml=junit_e2e.xml 2>&1 | tail -2
echo
echo "── FULL SUITE + COBERTURA ──"
"$PY" -m pytest --cov=team_builder --cov-report=term --cov-report=xml -q 2>&1 | tail -20
echo
echo "════ FIM DA EVIDÊNCIA ════"
} | tee docs/evidence/pytest_final.txt
