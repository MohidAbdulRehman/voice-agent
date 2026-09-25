"""Agent fixtures: the agent's tools on the test database, and a stand-in for RunContext.

No LLM runs here: the tests call the tools the way the LLM would, one by one.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from intake.agent import tools
from intake.agent.state import CallState
from intake.agent.tools import AgentDeps, IntakeAgent, PatientFields
from intake.config import Settings
from intake.core.services import Services, build_services
from intake.db.engine import make_engine
from tests.db.helpers import NOW

JANE = PatientFields(
    first_name="Jane",
    last_name="Davis",
    date_of_birth="03/05/1990",
    sex="female",
    phone_number="(512) 555-0100",
    address_line_1="12 Oak Street",
    city="Austin",
    state="Texas",
    zip_code="78701",
)


@dataclass
class FakeSession:
    """Records what a tool asked of the session."""

    shutdowns: list[bool] = field(default_factory=list)

    def shutdown(self, *, drain: bool = True) -> None:
        self.shutdowns.append(drain)


@dataclass
class FakeSpeechHandle:
    """The reply being spoken; ``finish`` plays it to the end."""

    callbacks: list[Callable[["FakeSpeechHandle"], None]] = field(default_factory=list)

    def add_done_callback(self, callback: Callable[["FakeSpeechHandle"], None]) -> None:
        self.callbacks.append(callback)

    def finish(self) -> None:
        for callback in self.callbacks:
            callback(self)


@dataclass
class FakeRunContext:
    """The parts of LiveKit's ``RunContext`` the tools use."""

    userdata: CallState
    session: FakeSession = field(default_factory=FakeSession)
    speech_handle: FakeSpeechHandle = field(default_factory=FakeSpeechHandle)
    interruptible: bool = True

    def disallow_interruptions(self) -> None:
        self.interruptible = False


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "RETRY_BACKOFF_SECONDS", 0)


@pytest.fixture
def voices() -> list[str]:
    """The languages the agent switched its voice to."""
    return []


AgentFactory = Callable[..., IntakeAgent]


@pytest.fixture
def make_agent(engine: AsyncEngine, voices: list[str]) -> AgentFactory:
    """An agent on the test database; settings (e.g. simulate_db_failure) can be overridden."""

    def make(**settings: object) -> IntakeAgent:
        config = Settings(_env_file=None, **settings)
        # "Today" is pinned for validation; slot searches use the real clock, like the database.
        services = build_services(engine, config, clock=lambda: NOW)
        deps = AgentDeps(services=services, settings=config, switch_voice=voices.append)
        return IntakeAgent(instructions="Test instructions.", deps=deps)

    return make


@pytest.fixture
def agent(make_agent: AgentFactory) -> IntakeAgent:
    return make_agent()


@pytest.fixture
async def unreachable_agent(voices: list[str]) -> AsyncIterator[IntakeAgent]:
    """An agent whose database refuses every connection."""
    engine = make_engine("postgresql://postgres:postgres@127.0.0.1:5433/unreachable_test")

    @event.listens_for(engine.sync_engine, "do_connect")
    def _refuse(*_args: object) -> None:
        raise ConnectionRefusedError("the database is down")

    config = Settings(_env_file=None)
    deps = AgentDeps(
        services=build_services(engine, config), settings=config, switch_voice=voices.append
    )
    yield IntakeAgent(instructions="Test instructions.", deps=deps)
    await engine.dispose()


@pytest.fixture
def services(engine: AsyncEngine) -> Services:
    """Services for setting up and checking the database around a tool call."""
    return build_services(engine, Settings(_env_file=None), clock=lambda: NOW)


@pytest.fixture
async def call(services: Services) -> FakeRunContext:
    """A console call in progress, opened the way the entrypoint opens one."""
    call_id = await services.calls.start(
        room_name="console-test", channel="console", caller_number=None
    )
    return FakeRunContext(CallState(call_id=call_id, channel="console", caller_number=None))
