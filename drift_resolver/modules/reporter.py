from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4
import json
import os
import sys

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
	from drift_resolver.models.drift_item import DriftClassification, DriftItem
	from drift_resolver.modules.approval import ApprovalResult
	from drift_resolver.modules.executor import ExecutionResult
	from drift_resolver.modules.generator import MigrationFile
	from drift_resolver.modules.validator import ValidationResult
except ModuleNotFoundError:
	project_root = Path(__file__).resolve().parents[2]
	if str(project_root) not in sys.path:
		sys.path.insert(0, str(project_root))
	from drift_resolver.models.drift_item import DriftClassification, DriftItem
	from drift_resolver.modules.approval import ApprovalResult
	from drift_resolver.modules.executor import ExecutionResult
	from drift_resolver.modules.generator import MigrationFile
	from drift_resolver.modules.validator import ValidationResult


GITHUB_API_TIMEOUT_SECONDS = 10


@dataclass
class DriftReport:
	"""Aggregate report for a drift-resolver run."""

	run_id: str
	generated_at: str
	total_items: int
	safe_count: int
	unsafe_count: int
	resolved_count: int
	rejected_count: int
	approval_mode: str
	migration_name: Optional[str]
	execution_success: Optional[bool]
	all_items: list[dict]
	unsafe_items_detail: list[dict]
	pipeline_outcome: str


def generate_report(
	all_items: list[DriftItem],
	approval_result: Optional[ApprovalResult] = None,
	validation_result: Optional[ValidationResult] = None,
	migration_file: Optional[MigrationFile] = None,
	execution_result: Optional[ExecutionResult] = None,
	report_dir: str = ".",
) -> DriftReport:
	"""Build a report and write the JSON and HTML artifacts."""

	report = DriftReport(
		run_id=str(uuid4()),
		generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
		total_items=len(all_items),
		safe_count=sum(1 for item in all_items if item.classification == DriftClassification.SAFE),
		unsafe_count=sum(1 for item in all_items if item.classification == DriftClassification.UNSAFE),
		resolved_count=_resolved_count(validation_result, execution_result),
		rejected_count=len(validation_result.rejected_items) if validation_result else 0,
		approval_mode=approval_result.mode if approval_result else "none",
		migration_name=migration_file.folder_name if migration_file else None,
		execution_success=execution_result.success if execution_result else None,
		all_items=[_serialize_drift_item(item) for item in all_items],
		unsafe_items_detail=[_serialize_drift_item(item) for item in all_items if item.classification == DriftClassification.UNSAFE],
		pipeline_outcome=_determine_pipeline_outcome(all_items, approval_result, execution_result),
	)

	json_path = _write_json_report(report, report_dir)
	html_path = _write_html_report(report, report_dir)

	print(f"[REPORTER] Report generated: {report.pipeline_outcome}")
	print(f"[REPORTER] JSON: {json_path}")
	print(f"[REPORTER] HTML: {html_path}")

	return report


def _resolved_count(
	validation_result: Optional[ValidationResult],
	execution_result: Optional[ExecutionResult],
) -> int:
	"""Count safe items actually applied."""

	if execution_result is None or not execution_result.success:
		return 0

	if execution_result.applied_items is not None:
		return execution_result.applied_items

	if validation_result is not None:
		return len(validation_result.validated_items)

	return 0


def _determine_pipeline_outcome(
	all_items: list[DriftItem],
	approval_result: Optional[ApprovalResult],
	execution_result: Optional[ExecutionResult],
) -> str:
	"""Derive the pipeline outcome label from available results."""

	if not all_items:
		return "no_drift"

	has_safe = any(item.classification == DriftClassification.SAFE for item in all_items)
	has_unsafe = any(item.classification == DriftClassification.UNSAFE for item in all_items)

	if approval_result is not None and not approval_result.approved:
		return "approval_pending"

	if has_unsafe and execution_result is None:
		return "unsafe_detected"

	if execution_result is not None and not execution_result.success:
		return "execution_failed"

	if execution_result is not None and execution_result.success:
		if has_safe and has_unsafe:
			return "partial"
		return "resolved"

	if has_unsafe:
		return "unsafe_detected"

	return "resolved"


def _write_json_report(report: DriftReport, report_dir: str) -> str:
	"""Write the JSON artifact to disk."""

	output_dir = Path(report_dir)
	output_dir.mkdir(parents=True, exist_ok=True)
	json_path = output_dir / "drift-report.json"
	json_path.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
	return str(json_path)


def _write_html_report(report: DriftReport, report_dir: str) -> str:
	"""Render the HTML artifact from the bundled Jinja template."""

	output_dir = Path(report_dir)
	output_dir.mkdir(parents=True, exist_ok=True)
	html_path = output_dir / "drift-report.html"
	template_dir = Path(__file__).resolve().parents[1] / "templates"
	environment = Environment(
		loader=FileSystemLoader(str(template_dir)),
		autoescape=select_autoescape(["html", "xml"]),
		trim_blocks=True,
		lstrip_blocks=True,
	)
	template = environment.get_template("report.html.j2")
	html_path.write_text(template.render(report=asdict(report)), encoding="utf-8")
	return str(html_path)


def _serialize_drift_item(item: DriftItem) -> dict:
	"""Convert a DriftItem into JSON-safe primitives."""

	data = item.model_dump()
	classification = data.get("classification")
	if isinstance(classification, DriftClassification):
		data["classification"] = classification.value
	else:
		data["classification"] = str(classification)
	return data


def post_result_comment(report: DriftReport, pr_number: str) -> None:
	"""Post the final result comment to the GitHub PR, if configured."""

	if not os.environ.get("PR_NUMBER"):
		return

	try:
		token = os.environ.get("GITHUB_TOKEN")
		repo = os.environ.get("GITHUB_REPOSITORY")
		if not token or not repo:
			print("[REPORTER] Missing GITHUB_TOKEN or GITHUB_REPOSITORY; skipping PR comment.")
			return

		url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
		headers = {
			"Authorization": f"Bearer {token}",
			"Accept": "application/vnd.github+json",
		}
		body = _build_result_comment_body(report)
		response = requests.post(url, headers=headers, json={"body": body}, timeout=GITHUB_API_TIMEOUT_SECONDS)
		response.raise_for_status()
		print(f"[REPORTER] Result comment posted to PR #{pr_number}")
	except Exception as exc:
		print(f"[REPORTER] Failed to post result comment for PR #{pr_number}: {exc}")


def _build_result_comment_body(report: DriftReport) -> str:
	"""Render the markdown body for the final PR comment."""

	is_success = report.pipeline_outcome in {"resolved", "no_drift"}
	headline_emoji = "✅" if is_success else "❌"
	if report.pipeline_outcome == "partial":
		headline_emoji = "⚠️"

	lines: list[str] = []
	lines.append(f"## {headline_emoji} Drift Resolver — Run Complete")
	lines.append("")
	lines.append(f"**Outcome:** {report.pipeline_outcome}")
	lines.append(f"**Run ID:** {report.run_id}")
	lines.append(f"**Generated:** {report.generated_at}")
	lines.append("")
	lines.append("### Summary")
	lines.append("| Metric | Count |")
	lines.append("|--------|-------|")
	lines.append(f"| Total drift items | {report.total_items} |")
	lines.append(f"| Auto-resolved (safe) | {report.resolved_count} |")
	lines.append(f"| Manual required (unsafe) | {report.unsafe_count} |")
	lines.append("")

	if report.pipeline_outcome == "resolved" and report.migration_name:
		lines.append(f"✅ Migration `{report.migration_name}` was applied successfully.")
		lines.append("")

	if report.pipeline_outcome in {"unsafe_detected", "partial", "approval_pending", "execution_failed"} and report.unsafe_count > 0:
		lines.append(f"⚠️ **{report.unsafe_count} unsafe change(s) require manual intervention.**")
		lines.append("Check the drift-report artifact for full details and SQL.")
		lines.append("")

	lines.append("> Download the full drift report from the Actions artifacts.")
	return "\n".join(lines)


if __name__ == "__main__":
	from drift_resolver.models.drift_item import DriftClassification, DriftItem
	from drift_resolver.modules.executor import ExecutionResult
	from drift_resolver.modules.generator import MigrationFile
	from drift_resolver.modules.approval import ApprovalResult
	from drift_resolver.modules.validator import ValidationResult

	demo_items = [
		DriftItem(
			sql='ALTER TABLE "users" ADD COLUMN "bio" TEXT;',
			statement_type="AlterTable_Add",
			table_name="users",
			column_name="bio",
			classification=DriftClassification.SAFE,
			reason="Adding a nullable column is safe — existing rows are unaffected",
			rollback_sql='ALTER TABLE users DROP COLUMN bio;',
		),
		DriftItem(
			sql='CREATE INDEX "idx_users_email" ON "users"("email");',
			statement_type="CreateIndex",
			table_name="users",
			classification=DriftClassification.SAFE,
			reason="Creating an index does not change data — safe",
			rollback_sql='DROP INDEX IF EXISTS idx_users_email;',
		),
		DriftItem(
			sql='CREATE TABLE "audit_logs" ("id" SERIAL PRIMARY KEY);',
			statement_type="CreateTable",
			table_name="audit_logs",
			classification=DriftClassification.SAFE,
			reason="Creating a new table does not affect existing data — safe",
			rollback_sql='DROP TABLE IF EXISTS audit_logs;',
		),
		DriftItem(
			sql='ALTER TABLE "users" DROP COLUMN "password";',
			statement_type="AlterTable_Drop",
			table_name="users",
			column_name="password",
			classification=DriftClassification.UNSAFE,
			reason="Dropping a column permanently deletes its data — manual review required",
		),
		DriftItem(
			sql='DROP TABLE "sessions";',
			statement_type="DropTable",
			table_name="sessions",
			classification=DriftClassification.UNSAFE,
			reason="Dropping a table permanently deletes all its data — manual review required",
		),
	]

	approval = ApprovalResult(approved=True, mode="github_label", message="drift-approved label found on PR #123")
	validation = ValidationResult(valid=True, validated_items=demo_items[:3], rejected_items=[], rejection_reasons={})
	migration_file = MigrationFile(
		folder_name="20260606000000_drift_auto_resolve",
		folder_path=str(Path.cwd() / "prisma" / "migrations" / "20260606000000_drift_auto_resolve"),
		sql_path=str(Path.cwd() / "prisma" / "migrations" / "20260606000000_drift_auto_resolve" / "migration.sql"),
		sql_content="-- demo migration",
		item_count=3,
		created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
	)
	execution_result = ExecutionResult(
		success=True,
		error_message=None,
		applied_items=3,
		migration_name=migration_file.folder_name,
		executed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
	)

	output_dir = Path.cwd()
	report = generate_report(
		demo_items,
		approval_result=approval,
		validation_result=validation,
		migration_file=migration_file,
		execution_result=execution_result,
		report_dir=str(output_dir),
	)

	json_path = output_dir / "drift-report.json"
	html_path = output_dir / "drift-report.html"
	print(f"[REPORTER] JSON exists: {json_path.is_file()}")
	print(f"[REPORTER] HTML exists: {html_path.is_file()}")
	print(str(html_path.resolve()))
