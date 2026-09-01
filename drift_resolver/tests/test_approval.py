from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from drift_resolver.models.drift_item import DriftClassification, DriftItem
from drift_resolver.modules.approval import (
	APPROVED_LABEL,
	_build_comment_body,
	_check_github_label,
	_post_approval_comment,
	_sql_for_markdown,
	check_approval,
)


def _safe_item() -> DriftItem:
	return DriftItem(
		sql='ALTER TABLE "User" ADD COLUMN "bio" TEXT',
		statement_type="AlterTable_Add",
		table_name="User",
		column_name="bio",
		classification=DriftClassification.SAFE,
		reason="Adding a nullable column is safe",
		rollback_sql='ALTER TABLE "User" DROP COLUMN "bio";',
	)


def test_auto_approve_skips_gate(monkeypatch) -> None:
	monkeypatch.setenv("AUTO_APPROVE", "true")
	result = check_approval([_safe_item()])
	assert result.approved is True
	assert result.mode == "auto"


def test_no_pr_context_exits_2(monkeypatch) -> None:
	monkeypatch.setenv("AUTO_APPROVE", "false")
	monkeypatch.setenv("PR_NUMBER", "")
	with pytest.raises(SystemExit) as exc:
		check_approval([_safe_item()])
	assert exc.value.code == 2


def test_approved_label_allows_pipeline(monkeypatch) -> None:
	monkeypatch.setenv("AUTO_APPROVE", "false")
	monkeypatch.setenv("PR_NUMBER", "42")
	monkeypatch.setenv("GITHUB_TOKEN", "token")
	monkeypatch.setenv("GITHUB_REPOSITORY", "kidu90/prisma-Drift-Resolver")

	response = MagicMock()
	response.status_code = 200
	response.json.return_value = [{"name": "drift-approved"}, {"name": "bug"}]

	with patch("drift_resolver.modules.approval.requests.get", return_value=response):
		result = check_approval([_safe_item()])

	assert result.approved is True
	assert result.mode == "github_label"
	assert "42" in result.message


def test_missing_label_posts_comment_and_exits_2(monkeypatch) -> None:
	monkeypatch.setenv("AUTO_APPROVE", "false")
	monkeypatch.setenv("PR_NUMBER", "7")
	monkeypatch.setenv("GITHUB_TOKEN", "token")
	monkeypatch.setenv("GITHUB_REPOSITORY", "kidu90/prisma-Drift-Resolver")

	get_response = MagicMock()
	get_response.status_code = 200
	get_response.json.return_value = []

	post_response = MagicMock()
	post_response.status_code = 201
	post_response.json.return_value = {
		"html_url": "https://github.com/kidu90/prisma-Drift-Resolver/issues/7#issuecomment-1"
	}

	with patch("drift_resolver.modules.approval.requests.get", return_value=get_response), patch(
		"drift_resolver.modules.approval.requests.post", return_value=post_response
	) as mock_post:
		with pytest.raises(SystemExit) as exc:
			check_approval([_safe_item()])
		assert exc.value.code == 2
		mock_post.assert_called_once()
		posted_body = mock_post.call_args.kwargs["json"]["body"]
		assert "Schema Drift Detected" in posted_body
		assert "drift-approved" in posted_body
		assert 'ALTER TABLE "User" ADD COLUMN "bio" TEXT' in posted_body


def test_check_github_label_returns_false_without_token(monkeypatch) -> None:
	monkeypatch.delenv("GITHUB_TOKEN", raising=False)
	monkeypatch.setenv("GITHUB_REPOSITORY", "kidu90/prisma-Drift-Resolver")
	assert _check_github_label("1") is False


def test_comment_body_lists_each_safe_item() -> None:
	items = [
		_safe_item(),
		DriftItem(
			sql='CREATE INDEX "idx_users_email" ON "User"("email")',
			statement_type="CreateIndex",
			table_name="User",
			classification=DriftClassification.SAFE,
			reason="Creating an index does not change data — safe",
			rollback_sql='DROP INDEX IF EXISTS "idx_users_email";',
		),
	]
	body = _build_comment_body(items)
	assert "Safe Changes Detected (2 total)" in body
	assert "AlterTable_Add" in body
	assert "CreateIndex" in body
	assert "Why These Are Safe" in body
	assert "Rollback Plan" in body
	assert "No rollback available" not in body


def _github_env(monkeypatch, pr_number: str = "12") -> None:
	monkeypatch.setenv("AUTO_APPROVE", "false")
	monkeypatch.setenv("PR_NUMBER", pr_number)
	monkeypatch.setenv("GITHUB_TOKEN", "ghs_test_token")
	monkeypatch.setenv("GITHUB_REPOSITORY", "kidu90/prisma-Drift-Resolver")


def test_auto_approve_is_case_insensitive(monkeypatch) -> None:
	monkeypatch.setenv("AUTO_APPROVE", "TRUE")
	result = check_approval([_safe_item()])
	assert result.approved is True
	assert result.mode == "auto"


def test_auto_approve_true_does_not_call_github(monkeypatch) -> None:
	monkeypatch.setenv("AUTO_APPROVE", "true")
	monkeypatch.setenv("PR_NUMBER", "9")
	with patch("drift_resolver.modules.approval.requests.get") as mock_get, patch(
		"drift_resolver.modules.approval.requests.post"
	) as mock_post:
		result = check_approval([_safe_item()])
	assert result.mode == "auto"
	mock_get.assert_not_called()
	mock_post.assert_not_called()


def test_auto_approve_yes_does_not_bypass_gate(monkeypatch) -> None:
	monkeypatch.setenv("AUTO_APPROVE", "yes")
	monkeypatch.setenv("PR_NUMBER", "")
	with pytest.raises(SystemExit) as exc:
		check_approval([_safe_item()])
	assert exc.value.code == 2


def test_pr_number_whitespace_only_exits_2(monkeypatch) -> None:
	monkeypatch.setenv("AUTO_APPROVE", "false")
	monkeypatch.setenv("PR_NUMBER", "   ")
	with pytest.raises(SystemExit) as exc:
		check_approval([_safe_item()])
	assert exc.value.code == 2


def test_similar_label_names_do_not_approve(monkeypatch) -> None:
	_github_env(monkeypatch, "5")
	response = MagicMock()
	response.status_code = 200
	response.json.return_value = [
		{"name": "approved"},
		{"name": "Drift-Approved"},
		{"name": "drift_approved"},
	]
	post_response = MagicMock()
	post_response.status_code = 201
	post_response.json.return_value = {"html_url": "https://example.com/comment"}

	with patch("drift_resolver.modules.approval.requests.get", return_value=response), patch(
		"drift_resolver.modules.approval.requests.post", return_value=post_response
	) as mock_post:
		with pytest.raises(SystemExit) as exc:
			check_approval([_safe_item()])
		assert exc.value.code == 2
		mock_post.assert_called_once()


def test_label_fetch_http_error_still_exits_2(monkeypatch) -> None:
	_github_env(monkeypatch)
	get_response = MagicMock()
	get_response.status_code = 403
	post_response = MagicMock()
	post_response.status_code = 201
	post_response.json.return_value = {"html_url": "https://example.com/comment"}

	with patch("drift_resolver.modules.approval.requests.get", return_value=get_response), patch(
		"drift_resolver.modules.approval.requests.post", return_value=post_response
	):
		with pytest.raises(SystemExit) as exc:
			check_approval([_safe_item()])
		assert exc.value.code == 2


def test_label_fetch_network_error_still_exits_2(monkeypatch) -> None:
	_github_env(monkeypatch)
	post_response = MagicMock()
	post_response.status_code = 201
	post_response.json.return_value = {"html_url": "https://example.com/comment"}

	with patch(
		"drift_resolver.modules.approval.requests.get",
		side_effect=requests.ConnectionError("dns failed"),
	), patch("drift_resolver.modules.approval.requests.post", return_value=post_response):
		with pytest.raises(SystemExit) as exc:
			check_approval([_safe_item()])
		assert exc.value.code == 2


def test_comment_post_failure_still_exits_2(monkeypatch) -> None:
	_github_env(monkeypatch, "3")
	get_response = MagicMock()
	get_response.status_code = 200
	get_response.json.return_value = []
	post_response = MagicMock()
	post_response.status_code = 401
	post_response.text = "Bad credentials"

	with patch("drift_resolver.modules.approval.requests.get", return_value=get_response), patch(
		"drift_resolver.modules.approval.requests.post", return_value=post_response
	):
		with pytest.raises(SystemExit) as exc:
			check_approval([_safe_item()])
		assert exc.value.code == 2


def test_comment_post_network_error_still_exits_2(monkeypatch) -> None:
	_github_env(monkeypatch)
	get_response = MagicMock()
	get_response.status_code = 200
	get_response.json.return_value = []

	with patch("drift_resolver.modules.approval.requests.get", return_value=get_response), patch(
		"drift_resolver.modules.approval.requests.post",
		side_effect=requests.Timeout("timed out"),
	):
		with pytest.raises(SystemExit) as exc:
			check_approval([_safe_item()])
		assert exc.value.code == 2


def test_approved_label_does_not_post_another_comment(monkeypatch) -> None:
	_github_env(monkeypatch, "42")
	response = MagicMock()
	response.status_code = 200
	response.json.return_value = [{"name": APPROVED_LABEL}]

	with patch("drift_resolver.modules.approval.requests.get", return_value=response) as mock_get, patch(
		"drift_resolver.modules.approval.requests.post"
	) as mock_post:
		result = check_approval([_safe_item()])

	assert result.approved is True
	assert result.mode == "github_label"
	mock_get.assert_called_once()
	assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer ghs_test_token"
	assert mock_get.call_args.kwargs["timeout"] == 10
	mock_post.assert_not_called()


def test_check_github_label_false_without_repository(monkeypatch) -> None:
	monkeypatch.setenv("GITHUB_TOKEN", "token")
	monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
	assert _check_github_label("1") is False


def test_post_comment_skips_without_token(monkeypatch, capsys) -> None:
	monkeypatch.delenv("GITHUB_TOKEN", raising=False)
	monkeypatch.setenv("GITHUB_REPOSITORY", "kidu90/prisma-Drift-Resolver")
	_post_approval_comment([_safe_item()], "8")
	assert "missing GITHUB_TOKEN" in capsys.readouterr().out


def test_comment_body_handles_missing_fields_and_empty_list() -> None:
	empty = _build_comment_body([])
	assert "Safe Changes Detected (0 total)" in empty
	assert "No safe items were provided." in empty
	assert "No rollback plan available." in empty

	item = DriftItem(
		sql='ALTER TABLE "User" ADD COLUMN "bio" TEXT\nDEFAULT NULL',
		statement_type="AlterTable_Add",
		table_name=None,
		classification=DriftClassification.SAFE,
		reason="",
		rollback_sql=None,
	)
	body = _build_comment_body([item])
	assert "| 1 | - | AlterTable_Add |" in body
	assert "No reason provided" in body
	assert "No rollback available" in body
	assert "\nDEFAULT" not in body


def test_sql_for_markdown_flattens_newlines_and_backticks() -> None:
	assert _sql_for_markdown("") == ""
	assert _sql_for_markdown("ALTER TABLE `User`\n  ADD COLUMN bio") == (
		"ALTER TABLE 'User' ADD COLUMN bio"
	)
