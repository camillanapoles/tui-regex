"""Integration — endpoints de continuidade (set/recover via API + gates)."""



class TestContinuityKinds:
    def test_list_kinds(self, client):
        resp = client.get("/continuity/kinds")
        assert resp.status_code == 200
        data = resp.json()
        assert {"session", "git_op", "artifact", "kv"} <= set(data["kinds"])
        assert data["registry"]["session"] == "SessionState"

    def test_stats(self, client):
        resp = client.get("/continuity/stats")
        assert resp.status_code == 200
        assert resp.json()["total_objects"] == 0


class TestContinuitySetGet:
    def test_set_then_recover(self, client):
        payload = {
            "data": {
                "branch": "arena/demo",
                "last_commit": "abc123",
                "pr_url": "",
                "next_steps": ["continuar a fase 2"],
                "notes": "estado da sessão",
            }
        }
        put = client.put("/continuity/session/current", json=payload)
        assert put.status_code == 200, put.text
        assert put.json()["version"] == 1

        got = client.get("/continuity/session/current")
        assert got.status_code == 200
        body = got.json()
        assert body["data"]["branch"] == "arena/demo"
        assert body["data"]["next_steps"] == ["continuar a fase 2"]
        assert body["version"] == 1
        assert body["gate_id"].startswith("gate-")

    def test_post_is_set_alias(self, client):
        resp = client.post(
            "/continuity/kv/generic", json={"data": {"value": {"a": 1}}}
        )
        assert resp.status_code == 200
        assert client.get("/continuity/kv/generic").json()["data"] == {"value": {"a": 1}}

    def test_version_bumps_and_conflict(self, client):
        client.put("/continuity/kv/v", json={"data": {"value": 1}})
        ok = client.put(
            "/continuity/kv/v", json={"data": {"value": 2}, "expected_version": 1}
        )
        assert ok.status_code == 200
        assert ok.json()["version"] == 2
        conflict = client.put(
            "/continuity/kv/v", json={"data": {"value": 3}, "expected_version": 1}
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["current_version"] == 2

    def test_keys_with_slashes(self, client):
        """key '{key:path}' aceita barras: git_op/branch/<nome-da-branch>."""
        set_resp = client.put(
            "/continuity/git_op/branch/arena-demo",
            json={"data": {"branch": "arena/demo"}},
        )
        assert set_resp.status_code == 200, set_resp.text
        got = client.get("/continuity/git_op/branch/arena-demo")
        assert got.json()["data"]["branch"] == "arena/demo"
        # query por prefixo encontra as duas chaves com barra
        listing = client.get("/continuity/", params={"kind": "git_op"}).json()
        assert listing["total"] >= 1


class TestContinuityGatesViaAPI:
    def test_unknown_kind_blocked_403(self, client):
        resp = client.put(
            "/continuity/hacker/x", json={"data": {}}
        )
        assert resp.status_code == 403
        assert "deny-by-default" in resp.json()["detail"]

    def test_unknown_kind_get_403(self, client):
        assert client.get("/continuity/hacker/x").status_code == 403

    def test_bad_key_blocked_403(self, client):
        resp = client.put("/continuity/kv/bad key!", json={"data": {}})
        assert resp.status_code == 403
        assert "key inválida" in resp.json()["detail"]

    def test_invalid_schema_blocked_403(self, client):
        resp = client.put(
            "/continuity/artifact/a1", json={"data": {"description": "sem path"}}
        )
        assert resp.status_code == 403
        assert "schema inválido" in resp.json()["detail"]

    def test_missing_key_404(self, client):
        assert client.get("/continuity/session/nao-existe").status_code == 404

    def test_gates_persisted_to_db(self, client):
        client.put("/continuity/kv/g", json={"data": {"value": 1}})
        client.get("/continuity/kv/g")
        client.get("/continuity/hacker/x")  # bloqueada
        blocked = client.get("/gates/blocked").json()
        assert blocked["total_blocked"] >= 1
        assert any("hacker" in (r["reason"] or "") for r in blocked["records"])


class TestContinuityDeleteAndQuery:
    def test_delete_flow(self, client):
        client.put("/continuity/kv/d", json={"data": {"value": 1}})
        resp = client.delete("/continuity/kv/d")
        assert resp.status_code == 200
        assert client.get("/continuity/kv/d").status_code == 404
        assert client.delete("/continuity/kv/d").status_code == 404

    def test_query_filters(self, client):
        client.put("/continuity/session/current", json={"data": {}})
        client.put("/continuity/session/archive-1", json={"data": {}})
        client.put("/continuity/kv/current", json={"data": {}})

        all_rows = client.get("/continuity/").json()
        assert all_rows["total"] == 3

        by_kind = client.get("/continuity/", params={"kind": "session"}).json()
        assert by_kind["total"] == 2

        by_prefix = client.get(
            "/continuity/", params={"kind": "session", "key_prefix": "archive"}
        ).json()
        assert by_prefix["total"] == 1
        assert by_prefix["objects"][0]["key"] == "archive-1"

    def test_end_to_end_session_recovery(self, client):
        """Cenário da constituição: setar numa sessão, recuperar na outra."""
        client.put(
            "/continuity/session/current",
            json={
                "data": {
                    "branch": "arena/01a0d0f0-tui-regex",
                    "last_commit": "f" * 40,
                    "next_steps": ["E1 tenant", "E3 LLM real"],
                }
            },
        )
        got = client.get("/continuity/session/current").json()
        assert got["data"]["branch"] == "arena/01a0d0f0-tui-regex"
        assert got["data"]["next_steps"] == ["E1 tenant", "E3 LLM real"]
        # e a gate dessa recuperação ficou registrada
        trace = client.get(f"/gates/{got['gate_id']}").json()
        assert trace["gate_name"] == "continuity_read_gate"
        assert trace["status"] == "allowed"
