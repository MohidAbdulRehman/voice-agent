"""Conversation evals: the real agent and LLM, in text mode, on the test database.

Opt-in, because every run spends LLM credits: ``uv run pytest -m evals``. The LLM
and LiveKit credentials come from .env; the database is still the local test
database, as in every other test.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from livekit.agents import AgentSession, inference, llm
from livekit.agents.voice.run_result import RunResult
from sqlalchemy.ext.asyncio import AsyncEngine

from intake.agent import scripts
from intake.agent.lifecycle import open_call
from intake.agent.prompts.loader import render_prompt
from intake.agent.session import build_llm, export_livekit_env
from intake.agent.state import CallState
from intake.agent.tools import AgentDeps, IntakeAgent
from intake.config import Settings
from intake.core.services import Services, build_services, utc_now
from intake.core.validation import clinic_today


@dataclass
class Conversation:
    """A text conversation with the agent, one caller turn at a time."""

    session: AgentSession[CallState]
    agent: IntakeAgent
    services: Services
    results: list[RunResult] = field(default_factory=list)

    @property
    def state(self) -> CallState:
        return self.session.userdata

    async def say(self, text: str) -> RunResult:
        result = await self.session.run(user_input=text)
        self.results.append(result)
        return result

    def calls(self, tool: str) -> list[dict[str, Any]]:
        """The arguments of every call to ``tool`` so far, in order."""
        return [
            json.loads(event.item.arguments)
            for result in self.results
            for event in result.events
            if event.type == "function_call" and event.item.name == tool
        ]

    def outputs(self, tool: str) -> list[dict[str, Any]]:
        """The results of every call to ``tool`` so far, in order."""
        return [
            json.loads(event.item.output)
            for result in self.results
            for event in result.events
            if event.type == "function_call_output" and event.item.name == tool
        ]

    async def judge_reply(self, judge: llm.LLM, intent: str) -> None:
        """Grade the agent's last message of the last turn against ``intent``."""
        result = self.results[-1]
        index = max(
            i
            for i, event in enumerate(result.events)
            if event.type == "message" and event.item.role == "assistant"
        )
        await result.expect[index].is_message(role="assistant").judge(judge, intent=intent)


@pytest.fixture
def eval_settings() -> Settings:
    """Settings from .env; tests/conftest.py already points DATABASE_URL at the test database."""
    settings = Settings()
    export_livekit_env(settings)  # LiveKit Inference reads its credentials from the environment
    return settings


@pytest.fixture
async def judge(eval_settings: Settings) -> AsyncIterator[llm.LLM]:
    """The LLM that grades the agent's replies."""
    async with inference.LLM(model=eval_settings.llm_primary_model) as model:
        yield model


@pytest.fixture
async def conversation(
    request: pytest.FixtureRequest, engine: AsyncEngine, eval_settings: Settings
) -> AsyncIterator[Conversation]:
    """A new call, already greeted. Parametrize indirectly to override settings."""
    settings = eval_settings.model_copy(update=getattr(request, "param", {}))
    services = build_services(engine, settings)
    state = await open_call(
        services, room_name=f"eval-{uuid4().hex[:12]}", channel="console", caller_number=None
    )
    prompt = render_prompt(
        agent_name=settings.agent_persona_name,
        clinic_name=settings.clinic_name,
        today=clinic_today(utc_now(), settings.clinic_zone),
        timezone=settings.clinic_timezone,
        caller_number=None,
    )
    deps = AgentDeps(services=services, settings=settings, switch_voice=lambda _language: None)
    agent = IntakeAgent(instructions=prompt, deps=deps)
    async with AgentSession[CallState](llm=build_llm(settings), userdata=state) as session:
        await session.start(agent)
        opener, rest = scripts.greeting(
            "English", clinic_name=settings.clinic_name, agent_name=settings.agent_persona_name
        )
        history = agent.chat_ctx.copy()
        history.add_message(role="assistant", content=f"{opener} {rest}")
        await agent.update_chat_ctx(history)
        yield Conversation(session=session, agent=agent, services=services)
