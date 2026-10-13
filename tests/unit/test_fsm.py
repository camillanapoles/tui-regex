"""FSM engine tests — gate-driven transitions, blocking, persistence."""
import pytest
from team_builder.db import FSMRepo
from team_builder.fsm import FSMEvent, FSMState


class TestFSMBasics:
    @pytest.mark.asyncio
    async def test_initial_state_is_idle(self, fsm_engine):
        assert fsm_engine.state == FSMState.IDLE

    @pytest.mark.asyncio
    async def test_idle_to_planning_via_task_received(self, fsm_engine):
        result = await fsm_engine.trigger(
            FSMEvent.TASK_RECEIVED,
            payload={"_api_context": True, "task_id": "t1"},
            sdlc_phase="development",
        )
        assert result.success is True
        assert result.from_state == FSMState.IDLE
        assert result.to_state == FSMState.PLANNING
        assert fsm_engine.state == FSMState.PLANNING

    @pytest.mark.asyncio
    async def test_transition_carries_all_gate_outputs(self, fsm_engine):
        result = await fsm_engine.trigger(
            FSMEvent.TASK_RECEIVED,
            payload={"_api_context": True},
            sdlc_phase="development",
        )
        assert result.success is True
        # 3 pre-gates + 1 post gate (audit)
        assert len(result.gate_outputs) == 4
        assert len(result.gate_ids) == 4
        for out in result.gate_outputs:
            assert out.gate_id.startswith("gate-")
            assert out.input_id.startswith("inp-")


class TestFSMBlocking:
    @pytest.mark.asyncio
    async def test_blocked_when_no_api_context(self, fsm_engine):
        result = await fsm_engine.trigger(
            FSMEvent.TASK_RECEIVED,
            payload={"_api_context": False},  # direct call, not via API
        )
        assert result.success is False
        assert result.to_state == FSMState.BLOCKED
        assert fsm_engine.state == FSMState.BLOCKED
        assert "FORA da API" in (result.error or "")

    @pytest.mark.asyncio
    async def test_invalid_transition_rejected(self, fsm_engine):
        result = await fsm_engine.trigger(
            FSMEvent.COMPLETE,  # no IDLE -> COMPLETE transition
            payload={"_api_context": True},
        )
        assert result.success is False
        assert "inválida" in (result.error or "")
        assert fsm_engine.state == FSMState.IDLE  # unchanged

    @pytest.mark.asyncio
    async def test_role_gate_blocks_developer_deploy(self, fsm_engine):
        await fsm_engine.trigger(FSMEvent.TASK_RECEIVED, payload={"_api_context": True})
        await fsm_engine.trigger(FSMEvent.PLAN_READY, payload={"_api_context": True})
        # deploy é válido na fase 'deployment' — mas NÃO para o role developer
        result = await fsm_engine.trigger(
            FSMEvent.DEPLOY,
            payload={"_api_context": True},
            sdlc_phase="deployment",
        )
        assert result.success is False
        assert fsm_engine.state == FSMState.BLOCKED
        assert "developer" in (result.error or "")

    @pytest.mark.asyncio
    async def test_sdlc_gate_blocks_wrong_phase(self, fsm_engine):
        result = await fsm_engine.trigger(
            FSMEvent.DEPLOY,
            payload={"_api_context": True},
            sdlc_phase="planning",  # deploy not allowed in planning
        )
        assert result.success is False


class TestFSMFlows:
    @pytest.mark.asyncio
    async def test_happy_path_to_completed(self, fsm_engine):
        for event, expected in [
            (FSMEvent.TASK_RECEIVED, FSMState.PLANNING),
            (FSMEvent.PLAN_READY, FSMState.EXECUTING),
            (FSMEvent.COMPLETE, FSMState.COMPLETED),
        ]:
            result = await fsm_engine.trigger(event, payload={"_api_context": True})
            assert result.success is True, result.error
            assert fsm_engine.state == expected

    @pytest.mark.asyncio
    async def test_review_flow_approve(self, fsm_engine):
        for event in [FSMEvent.TASK_RECEIVED, FSMEvent.PLAN_READY, FSMEvent.REQUEST_REVIEW]:
            assert (
                await fsm_engine.trigger(event, payload={"_api_context": True})
            ).success
        assert fsm_engine.state == FSMState.REVIEWING
        # APPROVE é emitido pelo QA (outro role) via API
        assert (
            await fsm_engine.trigger(
                FSMEvent.APPROVE,
                payload={"_api_context": True, "emit_role": "qa_engineer"},
            )
        ).success
        assert fsm_engine.state == FSMState.COMPLETED

    @pytest.mark.asyncio
    async def test_review_flow_reject_returns_to_executing(self, fsm_engine):
        for event in [FSMEvent.TASK_RECEIVED, FSMEvent.PLAN_READY, FSMEvent.REQUEST_REVIEW]:
            assert (
                await fsm_engine.trigger(event, payload={"_api_context": True})
            ).success
        assert (
            await fsm_engine.trigger(
                FSMEvent.REJECT,
                payload={"_api_context": True, "emit_role": "qa_engineer"},
            )
        ).success
        assert fsm_engine.state == FSMState.EXECUTING

    @pytest.mark.asyncio
    async def test_owner_role_cannot_approve_own_work(self, fsm_engine):
        for event in [FSMEvent.TASK_RECEIVED, FSMEvent.PLAN_READY, FSMEvent.REQUEST_REVIEW]:
            assert (
                await fsm_engine.trigger(event, payload={"_api_context": True})
            ).success
        result = await fsm_engine.trigger(
            FSMEvent.APPROVE, payload={"_api_context": True}  # dono=developer
        )
        assert result.success is False
        assert "developer" in (result.error or "")

    @pytest.mark.asyncio
    async def test_retry_flow(self, fsm_engine):
        for event in [FSMEvent.TASK_RECEIVED, FSMEvent.PLAN_READY, FSMEvent.FAIL]:
            assert (
                await fsm_engine.trigger(event, payload={"_api_context": True})
            ).success
        assert fsm_engine.state == FSMState.FAILED
        assert (
            await fsm_engine.trigger(FSMEvent.RETRY, payload={"_api_context": True})
        ).success
        assert fsm_engine.state == FSMState.PLANNING

    @pytest.mark.asyncio
    async def test_rollback_flow(self, fsm_engine):
        for event in [FSMEvent.TASK_RECEIVED, FSMEvent.PLAN_READY, FSMEvent.FAIL]:
            assert (
                await fsm_engine.trigger(event, payload={"_api_context": True})
            ).success
        # ROLLBACK é emitido pelo DevOps (outro role)
        assert (
            await fsm_engine.trigger(
                FSMEvent.ROLLBACK,
                payload={"_api_context": True, "emit_role": "devops"},
            )
        ).success
        assert fsm_engine.state == FSMState.ROLLBACK
        assert (
            await fsm_engine.trigger(FSMEvent.RESET, payload={"_api_context": True})
        ).success
        assert fsm_engine.state == FSMState.IDLE


class TestFSMPersistence:
    @pytest.mark.asyncio
    async def test_transitions_persisted_with_gate_fks(self, fsm_engine, db):
        await fsm_engine.trigger(FSMEvent.TASK_RECEIVED, payload={"_api_context": True})
        await fsm_engine.trigger(FSMEvent.PLAN_READY, payload={"_api_context": True})

        rows = FSMRepo(db).list_by_agent("dev-t1")
        assert len(rows) == 2
        assert rows[0].from_state == "idle"
        assert rows[0].to_state == "planning"
        assert rows[0].event == "task_received"
        assert len(rows[0].gate_ids) == 3  # pre-gates only at persist time
        assert all(g.startswith("gate-") for g in rows[0].gate_ids)
