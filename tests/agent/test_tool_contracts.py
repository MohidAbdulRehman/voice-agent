"""What the LLM sees of the tools: their schemas, and their results as JSON (no database)."""

import json

from livekit.agents.llm import ToolContext

from intake.agent.tools import AgentDeps, Facts, IntakeAgent
from intake.config import Settings
from intake.core.services import build_services
from intake.db.engine import make_engine

TOOL_NAMES = {
    "lookup_patient_by_phone",
    "prepare_record",
    "acknowledge_duplicate",
    "commit_record",
    "start_over",
    "find_appointment_slots",
    "book_appointment",
    "set_language",
    "end_call",
}


def _agent() -> IntakeAgent:
    settings = Settings(_env_file=None)
    engine = make_engine(settings.test_database_url.get_secret_value())  # never connects here
    deps = AgentDeps(
        services=build_services(engine, settings), settings=settings, switch_voice=print
    )
    return IntakeAgent(instructions="Test instructions.", deps=deps)


def test_the_nine_tools_have_strict_llm_schemas():
    schemas = ToolContext(_agent().tools).parse_function_tools("openai", strict=True)
    functions = {schema["function"]["name"]: schema["function"] for schema in schemas}

    assert set(functions) == TOOL_NAMES
    fields = functions["prepare_record"]["parameters"]["properties"]["fields"]
    assert "date_of_birth" in json.dumps(fields)
    assert "context" not in json.dumps(schemas)  # RunContext is not an LLM argument
    for function in functions.values():
        assert function["description"]  # the docstring is what the LLM reads


def test_results_reach_the_llm_as_json():
    facts = Facts(status="system_error", retryable=False, errors=[{"field": None}])

    assert str(facts) == (
        '{"status": "system_error", "retryable": false, "errors": [{"field": null}]}'
    )
    assert json.loads(str(facts)) == facts
