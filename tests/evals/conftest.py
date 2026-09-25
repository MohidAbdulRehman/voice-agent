"""Conversation evals: the real agent and LLM, in text mode, on the test database.

Opt-in, because every run spends LLM credits: ``uv run pytest -m evals``. The LLM
and LiveKit credentials come from .env; the database is still the local test
database, as in every other test. The run ends with the tokens it used and, for
models with a known price, what they cost.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from livekit.agents import AgentSession, inference, llm
from livekit.agents.metrics import LLMModelUsage, ModelUsageCollector
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

# Every LLM call the evals make, the agent's and the judge's.
USAGE = ModelUsageCollector()
# LiveKit Inference, US$ per million tokens: input, cached input, output (September 2026).
PRICES = {"openai/gpt-4.1-mini": (0.40, 0.10, 1.60)}


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """After an eval run, the tokens it used and what they cost."""
    usage = [entry for entry in USAGE.flatten() if isinstance(entry, LLMModelUsage)]
    if not usage:
        return
    terminalreporter.write_sep("-", "LLM usage")
    for entry in usage:
        fresh = entry.input_tokens - entry.input_cached_tokens
        line = (
            f"{entry.provider} {entry.model}: {entry.input_tokens:,} input tokens "
            f"({entry.input_cached_tokens:,} cached), {entry.output_tokens:,} output tokens"
        )
        if price := PRICES.get(entry.model):
            dollars = (
                fresh * price[0]
                + entry.input_cached_tokens * price[1]
                + entry.output_tokens * price[2]
            ) / 1_000_000
            line += f", about ${dollars:.3f}"
        terminalreporter.write_line(line)


@dataclass
class Conversation:
    """A text conversation with the agent, one caller turn at a time."""

    session: AgentSession[CallState]
    agent: IntakeAgent
    services: Services
    said: list[str] = field(default_factory=list)
    results: list[RunResult] = field(default_factory=list)

    @property
    def state(self) -> CallState:
        return self.session.userdata

    async def say(self, text: str) -> RunResult:
        self.said.append(text)
        result = await self.session.run(user_input=text)
        self.results.append(result)
        return result

    def transcript(self) -> str:
        """The conversation so far, with every tool call and its result."""
        lines = []
        for text, result in zip(self.said, self.results, strict=False):
            lines.append(f"caller: {text}")
            for event in result.events:
                if event.type == "message":
                    lines.append(f"agent: {event.item.text_content}")
                elif event.type == "function_call":
                    lines.append(f"  {event.item.name}({event.item.arguments})")
                elif event.type == "function_call_output":
                    lines.append(f"    -> {event.item.output}")
        return "\n".join(lines)

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
        model.on("metrics_collected", USAGE.collect)
        yield model


@pytest.fixture
async def conversation(engine: AsyncEngine, eval_settings: Settings) -> AsyncIterator[Conversation]:
    """A new call, already greeted."""
    services = build_services(engine, eval_settings)
    state = await open_call(
        services, room_name=f"eval-{uuid4().hex[:12]}", channel="console", caller_number=None
    )
    clinic, persona = eval_settings.clinic_name, eval_settings.agent_persona_name
    prompt = render_prompt(
        agent_name=persona,
        clinic_name=clinic,
        today=clinic_today(utc_now(), eval_settings.clinic_zone),
        timezone=eval_settings.clinic_timezone,
        caller_number=None,
    )
    deps = AgentDeps(services=services, settings=eval_settings, switch_voice=lambda _language: None)
    agent = IntakeAgent(instructions=prompt, deps=deps)
    model = build_llm(eval_settings)
    model.on("metrics_collected", USAGE.collect)  # the fallback adapter passes on each model's
    async with AgentSession[CallState](llm=model, userdata=state) as session:
        await session.start(agent)
        opener, rest = scripts.greeting("English", clinic_name=clinic, agent_name=persona)
        history = agent.chat_ctx.copy()
        history.add_message(role="assistant", content=f"{opener} {rest}")
        await agent.update_chat_ctx(history)
        conversation = Conversation(session=session, agent=agent, services=services)
        yield conversation
        print(conversation.transcript())  # pytest shows it when the eval fails
