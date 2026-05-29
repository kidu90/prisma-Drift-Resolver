from __future__ import annotations

import pytest

from drift_resolver.models.drift_item import DriftClassification, DriftItem
from drift_resolver.modules.approval import ApprovalResult, check_approval, format_safe_items_summary


def _make_safe_items() -> list[DriftItem]:
	"""Create a small set of safe drift items for approval tests."""

	return [
		DriftItem(
			sql='ALTER TABLE "users" ADD COLUMN "bio" TEXT',
			statement_type="AlterTable_Add",
			table_name="users",
			column_name="bio",
			classification=DriftClassification.SAFE,
			reason="Adding a nullable column is safe — existing rows are unaffected",
		),
		DriftItem(
			sql='CREATE INDEX "idx_users_email" ON "users"("email")',
			statement_type="CreateIndex",
			table_name="users",
			classification=DriftClassification.SAFE,
			reason="Creating an index does not change data — safe",
		),
		DriftItem(
			sql='CREATE TABLE "audit_logs" ("id" SERIAL PRIMARY KEY)',
			statement_type="CreateTable",
			table_name="audit_logs",
			classification=DriftClassification.SAFE,
			reason="Creating a new table does not affect existing data — safe",
		),
	]


def test_format_safe_items_summary() -> None:
	"""The helper should render a concise one-line summary."""

	summary = format_safe_items_summary(_make_safe_items())

	assert summary.startswith("3 safe change(s):")
	assert "ADD COLUMN bio on users" in summary
	assert "CREATE INDEX on users" in summary


def test_check_approval_auto_mode(monkeypatch: pytest.MonkeyPatch) -> None:
	"""AUTO_APPROVE should skip the GitHub approval gate."""

	monkeypatch.setenv("AUTO_APPROVE", "true")
	monkeypatch.delenv("PR_NUMBER", raising=False)
	monkeypatch.delenv("GITHUB_PR_NUMBER", raising=False)

	result = check_approval(_make_safe_items())

	assert isinstance(result, ApprovalResult)
	assert result.approved is True
	assert result.mode == "auto"


def test_check_approval_without_pr_context_exits(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
	"""Missing PR metadata should exit with code 2 and log the local guidance."""

	monkeypatch.setenv("AUTO_APPROVE", "false")
	monkeypatch.delenv("PR_NUMBER", raising=False)
	monkeypatch.delenv("GITHUB_PR_NUMBER", raising=False)

	with pytest.raises(SystemExit) as exc_info:
		check_approval(_make_safe_items())

	assert exc_info.value.code == 2
	output = capsys.readouterr().out
	assert "No PR_NUMBER found in environment" in output