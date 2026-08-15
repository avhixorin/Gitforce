from __future__ import annotations

import asyncio

from gitforce.app.agents.requirements import RequirementsAgent
from gitforce.app.config.settings import get_settings
from gitforce.app.llm.providers import MockProvider
from gitforce.tests.helpers import smart_responder


def test_requirements_agent_parses_structured_output() -> None:
    provider = MockProvider(get_settings(), responder=smart_responder)
    agent = RequirementsAgent(provider)
    issue = {"title": "Add greeting", "body": "Please add a greeting endpoint."}
    result = asyncio.run(agent.analyze(issue, []))
    assert result.problem == "Add a greeting endpoint"
    assert "Expose GET /greet" in result.requirements
    assert result.acceptance_criteria == ["GET /greet returns 200"]
    assert result.is_ambiguous is False


def test_requirements_ambiguous_flag() -> None:
    provider = MockProvider(get_settings(), responder=smart_responder)
    agent = RequirementsAgent(provider)
    issue = {"title": "Vague", "body": "Do something good."}
    # Override the responder to return ambiguity + no acceptance criteria.
    provider._responder = lambda req: (
        '{"problem": "", "requirements": [], "acceptance_criteria": [], '
        '"constraints": [], "assumptions": [], "ambiguities": ["a", "b", "c"], '
        '"risk_factors": []}'
    )
    result = asyncio.run(agent.analyze(issue, []))
    assert result.is_ambiguous is True