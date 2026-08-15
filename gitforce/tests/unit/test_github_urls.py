import pytest

from gitforce.app.github.client import (
    GitHubValidationError,
    parse_issue_url,
    parse_repository_url,
)


class TestRepositoryUrl:
    def test_valid_repo(self) -> None:
        ref = parse_repository_url("https://github.com/org/repo")
        assert ref.owner == "org"
        assert ref.repo == "repo"
        assert ref.full_name == "org/repo"

    def test_valid_repo_trailing_slash(self) -> None:
        ref = parse_repository_url("https://github.com/org/repo/")
        assert ref.full_name == "org/repo"

    def test_https_required(self) -> None:
        with pytest.raises(GitHubValidationError):
            parse_repository_url("git@github.com:org/repo.git")

    def test_non_github_host(self) -> None:
        with pytest.raises(GitHubValidationError):
            parse_repository_url("https://gitlab.com/org/repo")

    def test_missing_repo(self) -> None:
        with pytest.raises(GitHubValidationError):
            parse_repository_url("https://github.com/org")

    def test_nested_path_rejected(self) -> None:
        with pytest.raises(GitHubValidationError):
            parse_repository_url("https://github.com/org/repo/sub")


class TestIssueUrl:
    def test_valid_issue(self) -> None:
        ref = parse_issue_url("https://github.com/org/repo/issues/42")
        assert ref.owner == "org"
        assert ref.repo == "repo"
        assert ref.number == 42

    def test_issue_url_without_issue_path(self) -> None:
        with pytest.raises(GitHubValidationError):
            parse_issue_url("https://github.com/org/repo")

    def test_non_numeric_issue_number(self) -> None:
        with pytest.raises(GitHubValidationError):
            parse_issue_url("https://github.com/org/repo/issues/abc")

    def test_issue_url_with_anchor(self) -> None:
        ref = parse_issue_url("https://github.com/org/repo/issues/7#issuecomment-1")
        assert ref.number == 7