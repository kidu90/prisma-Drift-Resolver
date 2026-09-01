from __future__ import annotations

import json

from drift_resolver.models.drift_item import DriftClassification, DriftItem
from drift_resolver.modules.approval import ApprovalResult
from drift_resolver.modules.executor import ExecutionResult
from drift_resolver.modules.reporter import generate_report


def _item(classification: DriftClassification, sql: str) -> DriftItem:
	return DriftItem(
		sql=sql,
		statement_type="AlterTable_Add",
		table_name="User",
		classification=classification,
		reason="test reason",
	)


def test_report_records_auto_approval_and_unsent_notification(tmp_path) -> None:
	report = generate_report(
		[_item(DriftClassification.SAFE, 'ALTER TABLE "User" ADD COLUMN "bio" TEXT')],
		report_dir=str(tmp_path),
		approval_result=ApprovalResult(
			approved=True,
			mode="auto",
			message="Auto-approve enabled. Proceeding without review.",
		),
	)
	assert report.approval_mode == "auto"
	assert "Auto-approve" in report.approval_message
	assert report.notification_sent is False
	assert report.notification_recipient == ""

	html = (tmp_path / "drift-report.html").read_text(encoding="utf-8")
	assert "Auto-Approved" in html
	assert "Email Notifications: Not Configured" in html

	payload = json.loads((tmp_path / "drift-report.json").read_text(encoding="utf-8"))
	assert payload["approval_mode"] == "auto"
	assert payload["notification_sent"] is False


def test_report_records_github_label_approval(tmp_path) -> None:
	report = generate_report(
		[_item(DriftClassification.SAFE, 'ALTER TABLE "User" ADD COLUMN "bio" TEXT')],
		report_dir=str(tmp_path),
		approval_result=ApprovalResult(
			approved=True,
			mode="github_label",
			message="Approved via label on PR #12.",
		),
	)
	assert report.approval_mode == "github_label"
	html = (tmp_path / "drift-report.html").read_text(encoding="utf-8")
	assert "Approved via PR Label" in html
	assert "Approved via label on PR #12." in html


def test_report_records_pending_and_no_pr_context(tmp_path) -> None:
	pending = generate_report(
		[_item(DriftClassification.SAFE, "SELECT 1")],
		report_dir=str(tmp_path / "pending"),
		approval_result=ApprovalResult(
			approved=False,
			mode="pending",
			message="Waiting for drift-approved label.",
		),
	)
	assert pending.approval_mode == "pending"
	pending_html = (tmp_path / "pending" / "drift-report.html").read_text(encoding="utf-8")
	assert "Awaiting Approval" in pending_html

	no_pr = generate_report(
		[_item(DriftClassification.SAFE, "SELECT 1")],
		report_dir=str(tmp_path / "nopr"),
		approval_result=ApprovalResult(
			approved=False,
			mode="no_pr_context",
			message="No PR_NUMBER found in environment.",
		),
	)
	assert no_pr.approval_mode == "no_pr_context"
	no_pr_html = (tmp_path / "nopr" / "drift-report.html").read_text(encoding="utf-8")
	assert "No PR Context" in no_pr_html


def test_report_records_notification_sent_on_execution_failure(tmp_path) -> None:
	execution = ExecutionResult(
		success=False,
		error_message="prisma migrate deploy failed",
		applied_items=0,
		migration_name="20260612093220_drift_auto_resolve",
	)
	report = generate_report(
		[_item(DriftClassification.SAFE, 'ALTER TABLE "User" ADD COLUMN "bio" TEXT')],
		execution_result=execution,
		report_dir=str(tmp_path),
		notification_sent=True,
		notification_recipient="admin@co.com, ops@co.com",
		approval_result=ApprovalResult(
			approved=True,
			mode="auto",
			message="Auto-approve enabled. Proceeding without review.",
		),
	)
	assert report.pipeline_outcome == "execution_failed"
	assert report.notification_sent is True
	assert report.notification_recipient == "admin@co.com, ops@co.com"

	html = (tmp_path / "drift-report.html").read_text(encoding="utf-8")
	assert "Admin Notified" in html
	assert "admin@co.com, ops@co.com" in html
	assert "Email Notifications: Not Configured" not in html


def test_report_omits_approval_section_when_gate_not_reached(tmp_path) -> None:
	report = generate_report([], report_dir=str(tmp_path))
	assert report.approval_mode == ""
	assert report.pipeline_outcome == "no_drift"
	html = (tmp_path / "drift-report.html").read_text(encoding="utf-8")
	assert "Approval Status" not in html
