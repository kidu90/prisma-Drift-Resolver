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

APPROVED_LABEL = "drift-approved"
GITHUB_API_ACCEPT = "application/vnd.github+json"


@dataclass
class ApprovalResult:
	"""Outcome of the human approval gate."""

	approved: bool
	mode: str
	message: str


def check_approval(safe_items: list[DriftItem]) -> ApprovalResult:
	"""Decide whether safe drift may be applied.

	This is the only approval function called from main.py.
	Unapproved runs exit with code 2 so GitHub Actions pauses the job.
	"""

	auto = os.environ.get("AUTO_APPROVE", "false").lower()
	if auto == "true":
		print("[APPROVAL] AUTO_APPROVE=true. Skipping gate.")
		return ApprovalResult(
			approved=True,
			mode="auto",
			message="Auto-approve enabled. Proceeding without review.",
		)

	pr_number = os.environ.get("PR_NUMBER", "").strip()
	if not pr_number:
		_handle_no_pr_context()
		sys.exit(2)

	already_approved = _check_github_label(pr_number)
	if already_approved:
		print(f"[APPROVAL] ✓ {APPROVED_LABEL} label found on PR #{pr_number}")
		return ApprovalResult(
			approved=True,
			mode="github_label",
			message=f"Approved via label on PR #{pr_number}.",
		)

	_post_approval_comment(safe_items, pr_number)
	print("[APPROVAL] Comment posted. Waiting for drift-approved label.")
	print("[APPROVAL] Add the label and re-run this workflow to proceed.")
	sys.exit(2)


def _check_github_label(pr_number: str) -> bool:
	"""Return True if the PR has the drift-approved label."""

	token = os.environ.get("GITHUB_TOKEN", "")
	repo = os.environ.get("GITHUB_REPOSITORY", "")

	if not token or not repo:
		print("[APPROVAL] GITHUB_TOKEN or GITHUB_REPOSITORY not set.")
		return False

	url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels"
	headers = {
		"Authorization": f"Bearer {token}",
		"Accept": GITHUB_API_ACCEPT,
	}

	try:
		response = requests.get(url, headers=headers, timeout=10)
		if response.status_code == 200:
			labels = [label["name"] for label in response.json()]
			print(f"[APPROVAL] Labels on PR #{pr_number}: {labels}")
			return APPROVED_LABEL in labels

		print(f"[APPROVAL] Could not fetch labels. Status: {response.status_code}")
		return False
	except requests.RequestException as exc:
		print(f"[APPROVAL] Error checking labels: {exc}")
		return False


def _post_approval_comment(safe_items: list[DriftItem], pr_number: str) -> None:
	"""Post a markdown approval request comment on the PR."""

	token = os.environ.get("GITHUB_TOKEN", "")
	repo = os.environ.get("GITHUB_REPOSITORY", "")

	if not token or not repo:
		print("[APPROVAL] Cannot post comment: missing GITHUB_TOKEN or GITHUB_REPOSITORY")
		return

	url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
	headers = {
		"Authorization": f"Bearer {token}",
		"Accept": GITHUB_API_ACCEPT,
	}
	body = _build_comment_body(safe_items)

	try:
		response = requests.post(
			url,
			headers=headers,
			json={"body": body},
			timeout=15,
		)
		if response.status_code == 201:
			comment_url = response.json().get("html_url", "")
			print(f"[APPROVAL] ✓ Comment posted: {comment_url}")
		else:
			print(f"[APPROVAL] Failed to post comment. Status: {response.status_code}")
			print(f"[APPROVAL] Response: {response.text}")
	except requests.RequestException as exc:
		print(f"[APPROVAL] Error posting comment: {exc}")


def _build_comment_body(safe_items: list[DriftItem]) -> str:
	"""Build the full markdown comment from the detected safe items."""

	count = len(safe_items)
	table_rows = [
		"| # | Table | Change Type | SQL Statement |",
		"|---|-------|-------------|---------------|",
	]
	why_lines: list[str] = []
	rollback_lines: list[str] = []

	for index, item in enumerate(safe_items, start=1):
		table_name = item.table_name or "-"
		change_type = item.statement_type or "-"
		sql = _sql_for_markdown(item.sql)
		table_rows.append(f"| {index} | {table_name} | {change_type} | `{sql}` |")
		why_lines.append(f"- **#{index}** {item.reason or 'No reason provided'}")
		if item.rollback_sql:
			rollback_lines.append(
				f"- **#{index}** Rollback: `{_sql_for_markdown(item.rollback_sql)}`"
			)
		else:
			rollback_lines.append(f"- **#{index}** Rollback: No rollback available")

	if not why_lines:
		why_lines.append("- No safe items were provided.")
	if not rollback_lines:
		rollback_lines.append("- No rollback plan available.")

	return "\n".join(
		[
			"## 🔍 Schema Drift Detected — Approval Required",
			"",
			"The **Prisma Drift Auto-Resolver** detected safe schema changes",
			"in the live database that are not recorded in the migration history.",
			"",
			"These changes are classified as **safe** and can be automatically",
			"resolved. Please review them before approving.",
			"",
			f"### 📋 Safe Changes Detected ({count} total):",
			"",
			*table_rows,
			"",
			"### ✅ Why These Are Safe:",
			*why_lines,
			"",
			"### 🔄 Rollback Plan:",
			*rollback_lines,
			"",
			"---",
			"",
			"### ▶️ How to Approve:",
			"1. Review the changes listed above",
			"2. Add the label **`drift-approved`** to this Pull Request",
			"3. Click **Re-run failed jobs** in the Actions tab",
			"4. The resolver will apply the changes automatically",
			"",
			"### ❌ How to Reject:",
			"- Do NOT add the label",
			"- Do not re-run the workflow",
			"- Fix the drift manually if needed",
			"",
			"---",
			"> 🤖 This comment was posted automatically by",
			"> [drift-resolver](https://github.com/kidu90/prisma-Drift-Resolver)",
			"> — CB011943 Masha Kidurangi",
			"",
		]
	)


def _handle_no_pr_context() -> None:
	"""Explain how to run the gate when no pull request number is present."""

	print("[APPROVAL] No PR_NUMBER found in environment.")
	print("[APPROVAL] The approval gate requires a Pull Request.")
	print("[APPROVAL] Options:")
	print("[APPROVAL]   1. Run via a Pull Request (recommended for production)")
	print("[APPROVAL]   2. Set AUTO_APPROVE=true to bypass gate (for testing)")
	print("[APPROVAL] Exiting with code 2 — no changes applied.")


def _sql_for_markdown(sql: str) -> str:
	"""Flatten SQL so it is safe to place inside a markdown table cell."""

	return " ".join((sql or "").replace("`", "'").split())


def _sample_safe_items() -> list[DriftItem]:
	"""Return a single safe item used by the standalone smoke test."""

	return [
		DriftItem(
			sql='ALTER TABLE "User" ADD COLUMN "bio" TEXT',
			statement_type="AlterTable_Add",
			table_name="User",
			column_name="bio",
			classification=DriftClassification.SAFE,
			reason="Adding a nullable column is safe",
			rollback_sql='ALTER TABLE "User" DROP COLUMN "bio";',
		)
	]


if __name__ == "__main__":
	project_root = Path(__file__).resolve().parents[2]
	if str(project_root) not in sys.path:
		sys.path.insert(0, str(project_root))

	try:
		from dotenv import load_dotenv

		load_dotenv(project_root / ".env")
	except Exception:
		pass

	os.environ["AUTO_APPROVE"] = "true"
	fake_items = _sample_safe_items()
	result = check_approval(fake_items)
	print(f"Test 1 (AUTO_APPROVE): {result}")
	assert result.approved is True
	assert result.mode == "auto"

	# Test 2: No PR context
	# This should exit with code 2 — keep commented during normal standalone runs.
	# os.environ["AUTO_APPROVE"] = "false"
	# os.environ["PR_NUMBER"] = ""
	# result = check_approval(fake_items)

	print("[APPROVAL] Standalone tests passed.")
