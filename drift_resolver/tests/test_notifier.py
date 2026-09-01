from __future__ import annotations

from unittest.mock import MagicMock, patch

import smtplib

from drift_resolver.models.drift_item import DriftClassification, DriftItem
from drift_resolver.modules.notifier import (
	GMAIL_SMTP_HOST,
	GMAIL_SMTP_PORT,
	NotificationResult,
	_build_email_body,
	_build_email_subject,
	_extract_recipients,
	_safe_db_url,
	_send_email,
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


def _configure_email(monkeypatch, to_addr: str = "admin@co.com") -> None:
	monkeypatch.setenv("NOTIFY_EMAIL_FROM", "bot@gmail.com")
	monkeypatch.setenv("NOTIFY_EMAIL_PASSWORD", "abcd efgh ijkl mnop")
	monkeypatch.setenv("NOTIFY_EMAIL_TO", to_addr)


def _safe_item() -> DriftItem:
	return DriftItem(
		sql='ALTER TABLE "User" ADD COLUMN "bio" TEXT',
		statement_type="AlterTable_Add",
		table_name="User",
		column_name="bio",
		classification=DriftClassification.SAFE,
		reason="Adding a nullable column is safe",
	)


def test_check_email_config_enabled_when_all_set(monkeypatch) -> None:
	_configure_email(monkeypatch, "admin@co.com, dev@co.com")
	assert check_email_config() is True


def test_check_email_config_disabled_when_password_missing(monkeypatch) -> None:
	monkeypatch.setenv("NOTIFY_EMAIL_FROM", "bot@gmail.com")
	monkeypatch.setenv("NOTIFY_EMAIL_TO", "admin@co.com")
	monkeypatch.delenv("NOTIFY_EMAIL_PASSWORD", raising=False)
	assert check_email_config() is False


def test_send_skips_when_to_is_only_commas(monkeypatch) -> None:
	monkeypatch.setenv("NOTIFY_EMAIL_FROM", "bot@gmail.com")
	monkeypatch.setenv("NOTIFY_EMAIL_PASSWORD", "abcdefghijklmnop")
	monkeypatch.setenv("NOTIFY_EMAIL_TO", " , , ")
	result = send_failure_notification(
		failure_type="EXECUTION_FAILED",
		migration_name="mig",
		error_message="boom",
		sql_content="SELECT 1;",
		db_url="postgresql://u:p@localhost:5432/db",
	)
	assert result.sent is False
	assert result.error == "Not configured"


def test_send_success_uses_gmail_starttls_and_strips_password_spaces(monkeypatch) -> None:
	_configure_email(monkeypatch, "admin@co.com, ops@co.com")
	monkeypatch.setenv("NOTIFY_REPO_URL", "https://github.com/kidu90/prisma-Drift-Resolver")

	server = MagicMock()
	with patch("drift_resolver.modules.notifier.smtplib.SMTP", return_value=server) as smtp_ctor:
		result = send_failure_notification(
			failure_type="EXECUTION_FAILED",
			migration_name="20260612093220_drift_auto_resolve",
			error_message="Prisma migrate deploy failed (exit code 1)",
			sql_content='ALTER TABLE "User" ADD COLUMN "bio" TEXT;',
			db_url="postgresql://testuser:secretpass@myhost:5432/mydb",
			all_items=[_safe_item()],
		)

	smtp_ctor.assert_called_once_with(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, timeout=30)
	server.starttls.assert_called_once()
	server.login.assert_called_once_with("bot@gmail.com", "abcdefghijklmnop")
	server.sendmail.assert_called_once()
	server.quit.assert_called_once()

	assert result.sent is True
	assert result.error is None
	assert result.recipients == ["admin@co.com", "ops@co.com"]
	assert "Migration Failed" in result.subject

	from_addr, recipients, raw_message = server.sendmail.call_args.args
	assert from_addr == "bot@gmail.com"
	assert recipients == ["admin@co.com", "ops@co.com"]
	assert "secretpass" not in raw_message
	assert "abcd efgh ijkl mnop" not in raw_message
	assert "abcdefghijklmnop" not in raw_message
	assert "X-Mailer: drift-resolver/1.0" in raw_message
	assert "Drift Resolver <bot@gmail.com>" in raw_message


def test_smtp_failure_does_not_raise_and_closes_connection(monkeypatch) -> None:
	_configure_email(monkeypatch)
	server = MagicMock()
	server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Bad credentials")

	with patch("drift_resolver.modules.notifier.smtplib.SMTP", return_value=server):
		result = send_failure_notification(
			failure_type="TOOL_ERROR",
			migration_name="unknown",
			error_message="RuntimeError: boom",
			sql_content="",
			db_url="postgresql://u:p@localhost:5432/db",
		)

	assert result.sent is False
	assert result.error is not None
	assert "535" in result.error or "Bad credentials" in result.error
	server.quit.assert_called_once()


def test_send_email_closes_on_connect_failure(monkeypatch) -> None:
	monkeypatch.setenv("NOTIFY_EMAIL_FROM", "bot@gmail.com")
	monkeypatch.setenv("NOTIFY_EMAIL_PASSWORD", "abcdefghijklmnop")

	with patch(
		"drift_resolver.modules.notifier.smtplib.SMTP",
		side_effect=OSError("smtp.gmail.com unreachable"),
	):
		sent, error = _send_email("subject", "body", ["admin@co.com"])

	assert sent is False
	assert error is not None
	assert "unreachable" in error


def test_tool_error_body_uses_crash_copy_and_omits_repo_when_unset(monkeypatch) -> None:
	monkeypatch.delenv("NOTIFY_REPO_URL", raising=False)
	body = _build_email_body(
		"TOOL_ERROR",
		"unknown",
		"ValueError: Database URL is required.",
		"",
		"not available",
	)
	assert "unhandled exception" in body
	assert "ValueError: Database URL is required." in body
	assert "(no migration SQL available)" in body
	assert "Repository" not in body
	assert "/actions" not in body
	assert "Confirm DATABASE_URL" in body


def test_validation_failed_body_and_unknown_failure_type() -> None:
	validation_body = _build_email_body(
		"VALIDATION_FAILED",
		"20260612093220_drift_auto_resolve",
		"All safe items rejected",
		"",
		"postgresql://u:p@localhost:5432/db",
	)
	assert "rejected all safe items" in validation_body
	assert "Review rejected items" in validation_body

	unknown_subject = _build_email_subject("SOMETHING_ELSE", "mig")
	assert unknown_subject == "⚠️ [Drift Resolver] Failure — mig"

	unknown_body = _build_email_body("SOMETHING_ELSE", "", "", "", "")
	assert "requires manual attention" in unknown_body
	assert "Host: (not available)" in unknown_body
	assert "(no error message provided)" in unknown_body


def test_email_body_includes_repo_and_formats_dict_items(monkeypatch) -> None:
	monkeypatch.setenv("NOTIFY_REPO_URL", "https://github.com/kidu90/prisma-Drift-Resolver/")
	body = _build_email_body(
		"EXECUTION_FAILED",
		"mig",
		"failed",
		"ALTER TABLE x ADD COLUMN y TEXT;",
		"postgresql://u:p@localhost:5432/db",
		all_items=[
			{
				"classification": "UNSAFE",
				"sql": 'ALTER TABLE "User" DROP COLUMN "name"',
				"reason": "Dropping a column — manual review required",
			}
		],
	)
	assert "Repository   : https://github.com/kidu90/prisma-Drift-Resolver" in body
	assert "https://github.com/kidu90/prisma-Drift-Resolver/actions" in body
	assert "[UNSAFE]" in body
	assert "prisma migrate resolve --rolled-back mig" in body


def test_safe_db_url_handles_empty_and_credential_free_urls() -> None:
	assert _safe_db_url("") == ""
	assert _safe_db_url("postgresql://localhost:5432/db") == "postgresql://localhost:5432/db"
	assert "hunter2" not in _safe_db_url("postgres://admin:hunter2@db.internal/app")
