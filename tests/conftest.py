import pytest
from team_builder.db import AgentRepo, init_db, make_engine, make_session
from team_builder.fsm import FSMEngine
from team_builder.gates import GateRegistry
from team_builder.llm import MockLLM

from tests.helpers import GOD


@pytest.fixture
def registry() -> GateRegistry:
    return GateRegistry()


@pytest.fixture
def llm() -> MockLLM:
    return MockLLM()


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session = make_session(engine)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def fsm_engine(registry, db) -> FSMEngine:
    AgentRepo(db).save("dev-t1", "developer", "Dev T1")
    return FSMEngine("dev-t1", "developer", registry=registry, db=db)


@pytest.fixture
def client(tmp_path, llm):
    from fastapi.testclient import TestClient
    from team_builder.api import create_app

    app = create_app(
        db_url=f"sqlite:///{tmp_path / 'api.db'}",
        llm=llm,
        god_secret=GOD,
    )
    with TestClient(app) as c:
        yield c
