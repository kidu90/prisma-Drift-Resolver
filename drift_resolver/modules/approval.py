from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys

import requests

try:
	from drift_resolver.models.drift_item import DriftClassification, DriftItem
except ModuleNotFoundError:
	project_root = Path(__file__).resolve().parents[2]
	if str(project_root) not in sys.path:
		sys.path.insert(0, str(project_root))
	from drift_resolver.models.drift_item import DriftClassification, DriftItem


GITHUB_API_TIMEOUT_SECONDS = 10
GITHUB_DRIFT_LABEL = "drift-approved"


@dataclass
class ApprovalResult:
	"""Represent the approval decision for a batch of safe drift items."""

	approved: bool
	mode: str
	message: str


def format_safe_items_summary(safe_items: list[DriftItem]) -> str:
	"""Build a compact plain-text summary of safe drift items."""

	if not safe_items:
		return "0 safe change(s)."

	descriptions: list[str] = []
	for item in safe_items:
		descriptions.append(_describe_safe_item(item))

	return f"{len(safe_items)} safe change(s): {', '.join(descriptions)}"


def check_approval(safe_items: list[DriftItem]) -> ApprovalResult:
	"""Check whether the current run is approved to auto-resolve safe drift."""

	if os.environ.get("AUTO_APPROVE", "false").lower() == "true":
		# Development and test runs can bypass the PR approval gate entirely.
		message = "AUTO_APPROVE is set; skipping approval gate."
		print(f"[APPROVAL] {message}")
		return ApprovalResult(approved=True, mode="auto", message=message)

	pr_number = os.environ.get("PR_NUMBER") or os.environ.get("GITHUB_PR_NUMBER")
	if not pr_number:
		_handle_no_pr_context()
		sys.exit(2)

	if _check_github_label(pr_number):
		message = f"drift-approved label found on PR #{pr_number}"
		print(f"[APPROVAL] {message}. Proceeding with safe auto-resolution.")
		return ApprovalResult(approved=True, mode="github_label", message=message)

	_post_approval_comment(safe_items, pr_number)
	print(f"[APPROVAL] Approval pending for PR #{pr_number}; waiting for drift-approved label.")
	sys.exit(2)


def _check_github_label(pr_number: str) -> bool:
	"""Return True when the GitHub PR already has the drift-approved label."""

	token = os.environ.get("GITHUB_TOKEN")
	repo = os.environ.get("GITHUB_REPOSITORY")

	if not token:
		print("[APPROVAL] GITHUB_TOKEN is missing; cannot check PR labels.")
		return False

	if not repo:
		print("[APPROVAL] GITHUB_REPOSITORY is missing; cannot check PR labels.")
		return False

	url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels"
	headers = {
		"Authorization": f"Bearer {token}",
		"Accept": "application/vnd.github+json",
	}

	try:
		response = requests.get(url, headers=headers, timeout=GITHUB_API_TIMEOUT_SECONDS)
		response.raise_for_status()
		labels = response.json()
		if not isinstance(labels, list):
			print("[APPROVAL] Unexpected GitHub label payload; expected a list.")
			return False

		for label in labels:
			if isinstance(label, dict) and label.get("name") == GITHUB_DRIFT_LABEL:
				return True

		return False
	except requests.RequestException as exc:
		print(f"[APPROVAL] Failed to check GitHub labels for PR #{pr_number}: {exc}")
		return False
	except ValueError as exc:
		print(f"[APPROVAL] Failed to decode GitHub label payload for PR #{pr_number}: {exc}")
		return False


def _post_approval_comment(safe_items: list[DriftItem], pr_number: str) -> None:
	"""Post a GitHub comment requesting explicit approval for safe drift."""

	token = os.environ.get("GITHUB_TOKEN")
	repo = os.environ.get("GITHUB_REPOSITORY")

	if not token:
		print("[APPROVAL] GITHUB_TOKEN is missing; cannot post approval comment.")
		return

	if not repo:
		print("[APPROVAL] GITHUB_REPOSITORY is missing; cannot post approval comment.")
		return

	url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
	headers = {
		"Authorization": f"Bearer {token}",
		"Accept": "application/vnd.github+json",
	}
	body = _build_approval_comment_body(safe_items, pr_number)

	try:
		response = requests.post(url, headers=headers, json={"body": body}, timeout=GITHUB_API_TIMEOUT_SECONDS)
		response.raise_for_status()
		print(f"[APPROVAL] Comment posted to PR #{pr_number}")
	except requests.RequestException as exc:
		print(f"[APPROVAL] Failed to post approval comment to PR #{pr_number}: {exc}")


def _handle_no_pr_context() -> None:
	"""Log guidance for runs that do not have PR metadata available."""

	print("[APPROVAL] No PR_NUMBER found in environment.")
	print("[APPROVAL] This can happen on direct pushes to main without a PR.")
	print("[APPROVAL] Set AUTO_APPROVE=true to bypass, or run via a Pull Request.")


def _build_approval_comment_body(safe_items: list[DriftItem], pr_number: str) -> str:
	"""Render the markdown comment that asks for approval on the PR."""

	lines: list[str] = []
	lines.append("## 🔍 Schema Drift Detected — Approval Required")
	lines.append("")
	lines.append(
		f"The drift-resolver found **{len(safe_items)} safe** schema change(s) in the live database not reflected in your migration history."
	)
	lines.append("")
	lines.append("### Changes Detected:")
	lines.append("| # | Table | Change | SQL |")
	lines.append("|---|-------|--------|-----|")

	for index, item in enumerate(safe_items, start=1):
		table_name = item.table_name or "-"
		change_name = item.statement_type or "-"
		sql_text = _format_markdown_cell(item.sql)
		lines.append(f"| {index} | {table_name} | {change_name} | {sql_text} |")

	lines.append("")
	lines.append("### Why These Are Safe:")
	for item in safe_items:
		lines.append(f"- {item.reason or 'No reason provided.'}")

	lines.append("")
	lines.append("---")
	lines.append("**To approve:** Add the label `drift-approved` to this PR and re-run the failed pipeline job.")
	lines.append("")
	lines.append("**To reject:** Close this PR or do not re-run. No changes will be applied.")
	lines.append("")
	lines.append("> ⚠️ Unsafe changes (if any) are listed in the drift report artifact and require manual migration.")
	lines.append("")
	lines.append(f"> Approval requested for PR #{pr_number}: {format_safe_items_summary(safe_items)}")

	return "\n".join(lines)


def _format_markdown_cell(value: str) -> str:
	"""Escape a string for safe use inside a GitHub markdown table cell."""

	return value.replace("|", "\\|").replace("\n", " ").strip() or "-"


def _describe_safe_item(item: DriftItem) -> str:
	"""Produce a concise, human-readable description for one safe item."""

	table_name = item.table_name or "unknown table"
	column_name = item.column_name or "unknown column"
	statement_type = item.statement_type

	if statement_type == "AlterTable_Add":
		return f"ADD COLUMN {column_name} on {table_name}"

	if statement_type == "CreateIndex":
		return f"CREATE INDEX on {table_name}"

	if statement_type == "CreateTable":
		return f"CREATE TABLE {table_name}"

	if statement_type == "AlterTable_AlterColumn":
		return f"ALTER COLUMN {column_name} on {table_name}"

	if statement_type == "DropIndex":
		return f"DROP INDEX on {table_name}"

	return f"{statement_type} on {table_name}"


if __name__ == "__main__":
	"""Run a small self-test for the approval gate when the module is executed directly."""

	demo_safe_items = [
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
			column_name=None,
			classification=DriftClassification.SAFE,
			reason="Creating an index does not change data — safe",
		),
		DriftItem(
			sql='CREATE TABLE "audit_logs" ("id" SERIAL PRIMARY KEY)',
			statement_type="CreateTable",
			table_name="audit_logs",
			column_name=None,
			classification=DriftClassification.SAFE,
			reason="Creating a new table does not affect existing data — safe",
		),
	]

	os.environ["AUTO_APPROVE"] = "true"
	auto_result = check_approval(demo_safe_items)
	print(auto_result)

	os.environ["AUTO_APPROVE"] = "false"
	os.environ["PR_NUMBER"] = ""
	try:
		check_approval(demo_safe_items)
	except SystemExit as exc:
		print(f"[APPROVAL] Exited with code {exc.code}")
