from __future__ import annotations

from drift_resolver.models.drift_item import DriftClassification, DriftItem
from drift_resolver.modules.notifier import (
	NotificationResult,
	_build_email_body,
	_build_email_subject,
	_extract_recipients,
	_safe_db_url,
	check_email_config,
	send_failure_notification,
)


def test_extract_recipients_splits_and_strips() -> None:
	assert _extract_recipients("admin@co.com, dev@co.com") == [
		"admin@co.com",
		"dev@co.com",
	]
	assert _extract_recipients("  admin@co.com , ,dev@co.com  ") == [
		"admin@co.com",
		"dev@co.com",
	]
	assert _extract_recipients("") == []


def test_safe_db_url_hides_credentials() -> None:
	raw = "postgresql://testuser:testpass@localhost:5432/testdb"
	safe = _safe_db_url(raw)
	assert "testpass" not in safe
	assert "testuser" not in safe
	assert safe == "postgresql://*****@localhost:5432/testdb"


def test_email_subjects() -> None:
	assert (
		_build_email_subject("EXECUTION_FAILED", "20260612093220_drift_auto_resolve")
		== "❌ [Drift Resolver] Migration Failed — 20260612093220_drift_auto_resolve"
	)
	assert _build_email_subject("TOOL_ERROR", "unknown") == (
		"⚠️ [Drift Resolver] Tool Error — Manual Check Required"
	)
	assert (
		_build_email_subject("VALIDATION_FAILED", "mig")
		== "⚠️ [Drift Resolver] Validation Failed — mig"
	)


def test_email_body_never_includes_db_password() -> None:
	body = _build_email_body(
		"EXECUTION_FAILED",
		"20260612093220_drift_auto_resolve",
		"ERROR: relation 'User' does not exist",
		'ALTER TABLE "User" ADD COLUMN "bio" TEXT;',
		"postgresql://testuser:secretpass@myhost:5432/mydb",
		all_items=[
			DriftItem(
				sql='ALTER TABLE "User" ADD COLUMN "bio" TEXT',
				statement_type="AlterTable_Add",
				table_name="User",
				column_name="bio",
				classification=DriftClassification.SAFE,
				reason="Adding a nullable column is safe",
			)
		],
	)
	assert "secretpass" not in body
	assert "testuser" not in body
	assert "postgresql://*****@myhost:5432/mydb" in body
	assert "[SAFE]" in body
	assert "prisma migrate deploy" in body


def test_send_skips_when_not_configured(monkeypatch) -> None:
	monkeypatch.delenv("NOTIFY_EMAIL_FROM", raising=False)
	monkeypatch.delenv("NOTIFY_EMAIL_TO", raising=False)
	monkeypatch.delenv("NOTIFY_EMAIL_PASSWORD", raising=False)

	assert check_email_config() is False
	result = send_failure_notification(
		failure_type="EXECUTION_FAILED",
		migration_name="mig",
		error_message="boom",
		sql_content="SELECT 1;",
		db_url="postgresql://u:p@localhost:5432/db",
	)
	assert isinstance(result, NotificationResult)
	assert result.sent is False
	assert result.error == "Not configured"
