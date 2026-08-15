from __future__ import annotations

import enum

from pydantic import BaseModel, Field


class FeedbackCategory(enum.StrEnum):
    """PR feedback classification (Requirement section 26)."""

    APPROVAL = "approval"
    GENERAL_DISCUSSION = "general_discussion"
    QUESTION = "question"
    MINOR_REQUESTED_CHANGE = "minor_requested_change"
    IMPLEMENTATION_BUG = "implementation_bug"
    SECURITY_CONCERN = "security_concern"
    ARCHITECTURE_CONCERN = "architecture_concern"
    REQUIREMENT_CHANGE = "requirement_change"
    UNRELATED_SUGGESTION = "unrelated_suggestion"


class FeedbackSeverity(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FeedbackAnalysis(BaseModel):
    """Feedback Analyzer output (Requirement section 27)."""

    actionable: bool = False
    category: FeedbackCategory = FeedbackCategory.GENERAL_DISCUSSION
    severity: FeedbackSeverity = FeedbackSeverity.LOW
    requires_replanning: bool = False
    affected_requirements: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    summary: str = ""
    reason: str = ""


class RepositoryAnalysis(BaseModel):
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    package_manager: str = ""
    build_system: str = ""
    test_framework: str = ""
    architecture_summary: str = ""
    important_files: list[str] = Field(default_factory=list)
    relevant_modules: list[str] = Field(default_factory=list)
    conventions: list[str] = Field(default_factory=list)


class RequirementsAnalysis(BaseModel):
    problem: str = ""
    requirements: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)

    @property
    def is_ambiguous(self) -> bool:
        """Workflow can request human clarification (section 10)."""
        return len(self.ambiguities) >= 2 and not self.acceptance_criteria


class ImplementationPlan(BaseModel):
    summary: str = ""
    approach: str = ""
    alternatives_considered: list[str] = Field(default_factory=list)
    files_to_modify: list[str] = Field(default_factory=list)
    files_to_create: list[str] = Field(default_factory=list)
    files_to_delete: list[str] = Field(default_factory=list)
    implementation_steps: list[str] = Field(default_factory=list)
    testing_strategy: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    rollback_strategy: str = ""


class CodingIntent(BaseModel):
    """Coder's declared change before touching the workspace (plan.v1)."""

    summary: str = ""
    files_to_modify: list[str] = Field(default_factory=list)
    files_to_create: list[str] = Field(default_factory=list)
    implementation_notes: list[str] = Field(default_factory=list)
    tests_to_add: list[str] = Field(default_factory=list)


class FileChange(BaseModel):
    path: str
    content: str


class CodingImplementation(BaseModel):
    """Final artifact the coder writes into the workspace."""

    summary: str = ""
    files: list[FileChange] = Field(default_factory=list)


class TestResults(BaseModel):
    passed: bool = False
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    coverage: float = 0.0
    lint_passed: bool = True
    typecheck_passed: bool = True
    build_passed: bool = True
    failures: list[str] = Field(default_factory=list)


class SecurityFinding(BaseModel):
    severity: str = "info"
    category: str = ""
    file: str = ""
    line: int | None = None
    description: str = ""
    remediation: str = ""


class SecurityResults(BaseModel):
    passed: bool = True
    findings: list[SecurityFinding] = Field(default_factory=list)
    tools_run: list[str] = Field(default_factory=list)
    summary: str = ""


class ReviewFinding(BaseModel):
    severity: str = "info"
    category: str = ""
    location: str = ""
    description: str = ""
    recommendation: str = ""


class ReviewDecision(BaseModel):
    approved: bool = False
    blocking_issues: list[str] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)
    score: float = 0.0


class JudgeDecision(BaseModel):
    ready: bool = False
    requirements_score: float = 0.0
    correctness_score: float = 0.0
    quality_score: float = 0.0
    security_score: float = 0.0
    test_score: float = 0.0
    architecture_score: float = 0.0
    scope_score: float = 0.0
    regression_risk_score: float = 0.0
    overall_score: float = 0.0
    blocking_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class FailureAnalysis(BaseModel):
    root_cause: str = ""
    category: str = ""
    affected_files: list[str] = Field(default_factory=list)
    recommended_fix: str = ""