from __future__ import annotations

from gitforce.app.llm.models import LLMRequest

_REPOSITORY_JSON = """{
  "languages": ["python"],
  "frameworks": [],
  "package_manager": "pip",
  "build_system": "setuptools",
  "test_framework": "pytest",
  "architecture_summary": "A simple python package.",
  "important_files": ["src/app.py"],
  "relevant_modules": ["src/app.py"],
  "conventions": ["snake_case", "type hints"]
}"""

_FEEDBACK_JSON = """{
  "actionable": true,
  "category": "architecture_concern",
  "severity": "high",
  "requires_replanning": true,
  "affected_requirements": ["Use existing shared rate limiter"],
  "affected_files": ["src/app.py"],
  "summary": "Reuse the shared rate limiter.",
  "reason": "Architecture concern: do not reinvent the rate limiter."
}"""

_REQUIREMENTS_JSON = """{
  "problem": "Add a greeting endpoint",
  "requirements": ["Expose GET /greet"],
  "acceptance_criteria": ["GET /greet returns 200"],
  "constraints": ["No new deps"],
  "assumptions": ["python 3.12"],
  "ambiguities": [],
  "risk_factors": []
}"""

_PLAN_JSON = """{
  "summary": "Add greeting endpoint",
  "approach": "Add a new route",
  "alternatives_considered": [],
  "files_to_modify": ["src/app.py"],
  "files_to_create": [],
  "files_to_delete": [],
  "implementation_steps": ["add route"],
  "testing_strategy": ["add pytest test"],
  "risks": [],
  "rollback_strategy": "revert commit"
}"""

_CODING_JSON = """{
  "summary": "Add greeting endpoint",
  "files_to_modify": ["src/app.py"],
  "files_to_create": [],
  "implementation_notes": ["add GET /greet"],
  "tests_to_add": ["test_greet.py"]
}"""

_IMPLEMENT_JSON = """{
  "summary": "Implement greeting endpoint",
  "files": [
    {"path": "src/app.py", "content": "def greet(name: str) -> str:\\n    return f'Hello, {name}! ' + name\\n"},
    {"path": "tests/test_greet.py", "content": "from src.app import greet\\n\\ndef test_greet():\\n    assert greet('x') == 'Hello, x! x'\\n"}
  ]
}"""

_FAILURE_JSON = """{
  "root_cause": "greet function not defined",
  "category": "missing_implementation",
  "affected_files": ["src/app.py"],
  "recommended_fix": "define greet"
}"""

_SECURITY_JSON = """{
  "passed": true,
  "findings": [],
  "tools_run": ["static"],
  "summary": "No critical issues"
}"""

_REVIEW_JSON = """{
  "approved": true,
  "blocking_issues": [],
  "findings": [],
  "score": 0.9
}"""

_JUDGE_JSON = """{
  "ready": true,
  "requirements_score": 0.9,
  "correctness_score": 0.9,
  "quality_score": 0.8,
  "security_score": 0.9,
  "test_score": 0.9,
  "architecture_score": 0.8,
  "scope_score": 0.9,
  "regression_risk_score": 0.9,
  "overall_score": 0.88,
  "blocking_issues": [],
  "recommendations": []
}"""

_DELIVERY_JSON = """{
  "title": "Add a greeting endpoint",
  "body": "## Summary\\n\\nAdds a greeting endpoint.\\n\\n## Problem\\n\\nThe service had no way to greet users.\\n\\n## Requirements\\n\\n- Expose GET /greet\\n\\n## Implementation\\n\\n- Added a new route\\n\\n## Files Changed\\n\\n- src/app.py\\n\\n## Tests\\n\\nTests pass.\\n\\n## Security Review\\n\\nNo findings.\\n\\n## Risks\\n\\nNone.\\n\\n## Alternatives Considered\\n\\nN/A\\n\\n## Agent Evaluation\\n\\nJudge approved.\\n\\n## Validation Results\\n\\nAll tests passed.\\n\\n## Related Issue\\n\\n- N/A\\n\\n## ForgeAI Task Report\\n\\nSee task state."
}"""


def smart_responder(request: LLMRequest) -> str:
    """Return schema-valid JSON based on which agent is being called."""
    prompt = request.messages[0].content
    if "Requirements Analysis Agent" in prompt:
        return _REQUIREMENTS_JSON
    if "Planning Agent" in prompt:
        return _PLAN_JSON
    if "Security Agent" in prompt:
        return _SECURITY_JSON
    if "Code Review Agent" in prompt:
        return _REVIEW_JSON
    if "Judge Agent" in prompt:
        return _JUDGE_JSON
    if "Failure Analyzer" in prompt:
        return _FAILURE_JSON
    if "Feedback Analyzer Agent" in prompt:
        return _FEEDBACK_JSON
    if "Produce the actual file changes" in prompt:
        return _IMPLEMENT_JSON
    if "Coding Agent" in prompt:
        return _CODING_JSON
    if "Delivery Agent" in prompt:
        return _DELIVERY_JSON
    return _REPOSITORY_JSON