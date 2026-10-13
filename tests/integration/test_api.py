"""Integration tests — full HTTP API (FastAPI + TestClient).

Covers: health, agents CRUD, FSM trigger, work lifecycle, tools
(authorized + blocked), gate traces, GOD MODE (403 without credential,
build-team, forge-tool, fsm-edit, audit).
"""

from team_builder.models import AgentRole
from team_builder.wasm_tools import ADD_WAT

from tests.helpers import GOD, create_agent

GOD_HEADERS = {"X-God-Mode": GOD}


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["platform"] == "team-builder-wasm"
        assert data["wasm_runtime"] == "wasmtime"
        assert data["tools"] >= 4
        assert data["agents_live"] == 0

    def test_platform_header(self, client):
        resp = client.get("/health")
        assert resp.headers["X-Team-Builder"].startswith("wasm-fsm/")


class TestAgents:
    def test_create_agent_via_factory(self, client):
        agent = create_agent(client)
        assert agent["agent_id"].startswith("dev-")
        assert agent["role"] == "developer"
        assert agent["state"] == "idle"
        listing = client.get("/agents/").json()
        assert listing["total"] == 1

    def test_agent_detail(self, client):
        agent = create_agent(client)
        detail = client.get(f"/agents/{agent['agent_id']}").json()
        assert detail["state"] == "idle"
        assert detail["spec"]["role"] == "developer"

    def test_get_missing_agent_404(self, client):
        assert client.get("/agents/does-not-exist").status_code == 404

    def test_work_lifecycle_completes(self, client):
        agent = create_agent(client)
        resp = client.post(
            f"/agents/{agent['agent_id']}/work",
            json={"task": {"title": "T1", "description": "Implemente X", "task_id": "task-api-1"}},
        )
        assert resp.status_code == 200, resp.text
        output = resp.json()
        assert output["agent_role"] == "developer"
        assert output["next_event"] == "complete"
        assert isinstance(output["result"], dict)
        assert output["result"].get("file_path")

        assert client.get(f"/agents/{agent['agent_id']}").json()["state"] == "completed"

        tasks = client.get("/tasks/").json()
        assert tasks["total"] == 1
        assert tasks["tasks"][0]["status"] == "completed"
        assert tasks["tasks"][0]["gate_ids"], "task deve carregar gate_ids (FK)"


class TestFSMThroughAPI:
    def test_trigger_task_received(self, client):
        agent = create_agent(client)
        resp = client.post(
            "/fsm/trigger",
            json={
                "agent_id": agent["agent_id"],
                "event": "task_received",
                "payload": {"task_id": "t1"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["to_state"] == "planning"
        assert len(data["gate_ids"]) == 4

    def test_trigger_missing_agent_404(self, client):
        resp = client.post(
            "/fsm/trigger",
            json={"agent_id": "ghost", "event": "task_received", "payload": {}},
        )
        assert resp.status_code == 404

    def test_invalid_event_after_completed(self, client):
        agent = create_agent(client)
        client.post(
            f"/agents/{agent['agent_id']}/work",
            json={"task": {"title": "T", "task_id": "t0"}},
        )
        resp = client.post(
            "/fsm/trigger",
            json={
                "agent_id": agent["agent_id"],
                "event": "task_received",  # COMPLETED + task_received inexistente
                "payload": {},
            },
        )
        data = resp.json()
        assert data["success"] is False
        assert "inválida" in data["error"]


class TestTools:
    def test_list_builtin_tools(self, client):
        data = client.get("/tools/").json()
        names = {t["name"] for t in data["tools"]}
        assert {"uppercase", "fibonacci", "add", "echo"} <= names

    def test_execute_uppercase_tool(self, client):
        agent = create_agent(client)
        resp = client.post(
            "/tools/uppercase/execute",
            json={"agent_id": agent["agent_id"], "params": {"text": "wasm e2e"}},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["output"] == "WASM E2E"
        assert data["success"] is True
        assert data["gate_id"].startswith("gate-")

    def test_tool_blocked_for_wrong_role(self, client):
        agent = create_agent(client, role=AgentRole.PROJECT_MANAGER)
        resp = client.post(
            "/tools/uppercase/execute",
            json={"agent_id": agent["agent_id"], "params": {"text": "x"}},
        )
        assert resp.status_code == 403
        assert "project_manager" in resp.json()["detail"]

    def test_blocked_tool_visible_in_gates(self, client):
        agent = create_agent(client, role=AgentRole.PROJECT_MANAGER)
        client.post(
            "/tools/uppercase/execute",
            json={"agent_id": agent["agent_id"], "params": {"text": "x"}},
        )
        data = client.get("/gates/blocked").json()
        assert data["total_blocked"] >= 1
        assert "project_manager" in data["records"][0]["reason"]

    def test_missing_tool_404(self, client):
        agent = create_agent(client)
        resp = client.post(
            "/tools/nope/execute",
            json={"agent_id": agent["agent_id"], "params": {}},
        )
        assert resp.status_code == 404


class TestGateTraces:
    def test_gate_trace_full_input_output(self, client):
        agent = create_agent(client)
        client.post(
            "/fsm/trigger",
            json={"agent_id": agent["agent_id"], "event": "task_received", "payload": {}},
        )
        gates = client.get("/gates/").json()
        assert gates["total"] >= 4
        gate_id = gates["records"][0]["gate_id"]
        trace = client.get(f"/gates/{gate_id}").json()
        assert trace["gate_id"] == gate_id
        assert trace["input"] is not None
        assert trace["output"] is not None
        # FK invariants visible through the API
        assert trace["output"]["gate_id"] == trace["gate_id"]
        assert trace["output"]["input_id"] == trace["input"]["object_id"]

    def test_unknown_gate_404(self, client):
        assert client.get("/gates/gate-nonexistent").status_code == 404


class TestGodMode:
    def test_requires_credential(self, client):
        assert client.post("/god/build-team", json={"project_description": "x"}).status_code == 403
        assert client.get("/god/audit").status_code == 403

    def test_wrong_credential_rejected(self, client):
        resp = client.post(
            "/god/build-team",
            json={"project_description": "x"},
            headers={"X-God-Mode": "wrong"},
        )
        assert resp.status_code == 403

    def test_build_team(self, client):
        resp = client.post(
            "/god/build-team",
            json={"project_description": "Plataforma de e-commerce com API, mobile e dados"},
            headers=GOD_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["summary"]["total_agents"] >= 1
        agents = client.get("/agents/").json()
        assert agents["total"] == data["summary"]["total_agents"]

    def test_forge_tool_and_execute(self, client):
        agent = create_agent(client)
        resp = client.post(
            "/god/tools/forge",
            json={
                "name": "double",
                "description": "Dobra um inteiro em WASM",
                "wat": ADD_WAT,
                "entrypoint": "add",
                "parameters": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "param_names": ["a", "b"],
                "assigned_roles": ["developer"],
            },
            headers=GOD_HEADERS,
        )
        assert resp.status_code == 201, resp.text
        tool_id = resp.json()["tool_id"]

        exec_resp = client.post(
            "/tools/double/execute",
            json={"agent_id": agent["agent_id"], "params": {"a": 21, "b": 21}},
        )
        assert exec_resp.status_code == 200
        assert exec_resp.json()["output"] == "42"
        assert tool_id.startswith("tool-")

    def test_forge_invalid_wat_rejected(self, client):
        resp = client.post(
            "/god/tools/forge",
            json={"name": "broken", "wat": "(module broken", "entrypoint": "x"},
            headers=GOD_HEADERS,
        )
        assert resp.status_code == 400
        assert "WAT inválida" in resp.json()["detail"]

    def test_fsm_edit_requires_impact_analysis(self, client):
        agent = create_agent(client)
        resp = client.patch(
            "/god/fsm/edit",
            json={
                "agent_id": agent["agent_id"],
                "impact_analysis": "curto",  # < 30 chars -> 422
                "refactor_reason": "x" * 12,
            },
            headers=GOD_HEADERS,
        )
        assert resp.status_code == 422

    def test_fsm_edit_applies_custom_transitions(self, client):
        agent = create_agent(client)
        resp = client.patch(
            "/god/fsm/edit",
            json={
                "agent_id": agent["agent_id"],
                "impact_analysis": "Substitui a tabela para validar apenas o fluxo mínimo idle->planning->completed.",
                "refactor_reason": "Simplificar para smoke test",
                "new_transitions": [
                    {"from_state": "idle", "event": "task_received", "to_state": "planning", "action_name": "on_task_received"},
                    {"from_state": "planning", "event": "complete", "to_state": "completed", "action_name": "on_complete"},
                ],
            },
            headers=GOD_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["transitions_applied"] == 2

        # custom table now rejects plan_ready (no longer in the map)
        trigger = client.post(
            "/fsm/trigger",
            json={"agent_id": agent["agent_id"], "event": "task_received", "payload": {}},
        )
        assert trigger.json()["to_state"] == "planning"
        rejected = client.post(
            "/fsm/trigger",
            json={"agent_id": agent["agent_id"], "event": "plan_ready", "payload": {}},
        )
        assert rejected.json()["success"] is False

    def test_audit_trail(self, client):
        client.post(
            "/god/build-team",
            json={"project_description": "projeto teste"},
            headers=GOD_HEADERS,
        )
        resp = client.get("/god/audit", headers=GOD_HEADERS)
        assert resp.status_code == 200
        actions = {e["action"] for e in resp.json()["entries"]}
        assert "god.build_team" in actions
