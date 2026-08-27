from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
import os
import re
import smtplib
import sys
from pathlib import Path

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
X_MAILER = "drift-resolver/1.0"


@dataclass
class NotificationResult:
	"""Outcome of an attempted failure notification."""

	sent: bool
	recipients: list[str]
	subject: str
	error: Optional[str] = None


def send_failure_notification(
	failure_type: str,
	migration_name: str,
	error_message: str,
	sql_content: str,
	db_url: str,
	all_items: Optional[list] = None,
) -> NotificationResult:
	"""Send a failure email to the configured admin recipients.

	Email sending is optional and must never crash the caller.
	"""

	try:
		from_addr = (os.environ.get("NOTIFY_EMAIL_FROM") or "").strip()
		to_raw = (os.environ.get("NOTIFY_EMAIL_TO") or "").strip()

		if not from_addr or not to_raw:
			print("[NOTIFIER] Email not configured. Skipping notification.")
			return NotificationResult(
				sent=False,
				recipients=[],
				subject="",
				error="Not configured",
			)

		recipients = _extract_recipients(to_raw)
		if not recipients:
			print("[NOTIFIER] Email not configured. Skipping notification.")
			return NotificationResult(
				sent=False,
				recipients=[],
				subject="",
				error="Not configured",
			)

		subject = _build_email_subject(failure_type, migration_name)
		body = _build_email_body(
			failure_type,
			migration_name,
			error_message,
			sql_content,
			db_url,
			all_items,
		)
		sent, error = _send_email(subject, body, recipients)
		return NotificationResult(
			sent=sent,
			recipients=recipients,
			subject=subject,
			error=error,
		)
	except Exception as exc:
		print(f"[NOTIFIER] ✗ Failed to send notification: {exc}")
		return NotificationResult(
			sent=False,
			recipients=[],
			subject="",
			error=str(exc),
		)


def check_email_config() -> bool:
	"""Return True when email notifications are fully configured.

	Missing configuration is optional — the tool continues normally.
	"""

	from_addr = (os.environ.get("NOTIFY_EMAIL_FROM") or "").strip()
	password = (os.environ.get("NOTIFY_EMAIL_PASSWORD") or "").replace(" ", "")
	to_raw = (os.environ.get("NOTIFY_EMAIL_TO") or "").strip()
	recipients = _extract_recipients(to_raw) if to_raw else []

	if from_addr and password and recipients:
		print(f"[NOTIFIER] Email notifications: ENABLED → {', '.join(recipients)}")
		return True

	print("[NOTIFIER] Email notifications: DISABLED (env vars not set)")
	return False


def _build_email_subject(failure_type: str, migration_name: str) -> str:
	"""Return the subject line for the given failure type."""

	if failure_type == "EXECUTION_FAILED":
		return f"❌ [Drift Resolver] Migration Failed — {migration_name}"
	if failure_type == "TOOL_ERROR":
		return "⚠️ [Drift Resolver] Tool Error — Manual Check Required"
	if failure_type == "VALIDATION_FAILED":
		return f"⚠️ [Drift Resolver] Validation Failed — {migration_name}"
	return f"⚠️ [Drift Resolver] Failure — {migration_name or 'unknown'}"


def _build_email_body(
	failure_type: str,
	migration_name: str,
	error_message: str,
	sql_content: str,
	db_url: str,
	all_items: Optional[list] = None,
) -> str:
	"""Build a plain-text failure email body. Never includes DB passwords."""

	timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
	repo_url = (os.environ.get("NOTIFY_REPO_URL") or "").strip().rstrip("/")
	safe_url = _safe_db_url(db_url or "")

	lines = [
		"============================================",
		"PRISMA DRIFT RESOLVER — FAILURE NOTIFICATION",
		"============================================",
		"",
		f"Failure Type : {failure_type}",
		f"Time         : {timestamp}",
		f"Migration    : {migration_name or 'unknown'}",
	]
	if repo_url:
		lines.append(f"Repository   : {repo_url}")

	lines.extend(
		[
			"",
			"── WHAT HAPPENED ──────────────────────────",
			_what_happened(failure_type),
			"",
			"── ERROR MESSAGE ──────────────────────────",
			error_message or "(no error message provided)",
			"",
			"── MIGRATION SQL ──────────────────────────",
			sql_content or "(no migration SQL available)",
			"",
			"── DATABASE ───────────────────────────────",
			f"Host: {safe_url or '(not available)'}",
			"",
			"── WHAT TO DO ─────────────────────────────",
			_what_to_do(failure_type, migration_name),
		]
	)

	if all_items:
		lines.extend(
			[
				"",
				"── DRIFT ITEMS DETECTED ───────────────────",
				_format_drift_items(all_items),
			]
		)

	if repo_url:
		lines.extend(
			[
				"",
				"── ACTIONS LOG ────────────────────────────",
				f"{repo_url}/actions",
			]
		)

	lines.extend(
		[
			"",
			"============================================",
			"This is an automated message from drift-resolver.",
			"Do not reply to this email.",
			"============================================",
		]
	)
	return "\n".join(lines)


def _send_email(
	subject: str,
	body: str,
	recipients: list[str],
) -> tuple[bool, Optional[str]]:
	"""Send a plain-text email via Gmail SMTP. Never raises to the caller."""

	from_addr = (os.environ.get("NOTIFY_EMAIL_FROM") or "").strip()
	password = (os.environ.get("NOTIFY_EMAIL_PASSWORD") or "").replace(" ", "")
	server: Optional[smtplib.SMTP] = None

	try:
		print(f"[NOTIFIER] Sending failure notification to: {', '.join(recipients)}...")

		message = MIMEMultipart()
		message["From"] = f"Drift Resolver <{from_addr}>"
		message["To"] = ", ".join(recipients)
		message["Subject"] = subject
		message["X-Mailer"] = X_MAILER
		message.attach(MIMEText(body, "plain", "utf-8"))

		server = smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, timeout=30)
		server.ehlo()
		server.starttls()
		server.ehlo()
		server.login(from_addr, password)
		server.sendmail(from_addr, recipients, message.as_string())

		print("[NOTIFIER] ✓ Notification sent successfully.")
		return True, None
	except Exception as exc:
		error_message = str(exc)
		print(f"[NOTIFIER] ✗ Failed to send notification: {error_message}")
		return False, error_message
	finally:
		if server is not None:
			try:
				server.quit()
			except Exception:
				try:
					server.close()
				except Exception:
					pass


def _extract_recipients(email_str: str) -> list[str]:
	"""Split a comma-separated recipient string into clean addresses."""

	return [address.strip() for address in email_str.split(",") if address.strip()]


def _safe_db_url(db_url: str) -> str:
	"""Hide credentials in a database URL for safe display."""

	if not db_url:
		return ""
	return re.sub(r"://[^@]+@", "://*****@", db_url)


def _what_happened(failure_type: str) -> str:
	"""Return a short explanation of the failure for the email body."""

	if failure_type == "EXECUTION_FAILED":
		return (
			"The drift-resolver tool detected safe schema drift and generated\n"
			"a migration file, but \"prisma migrate deploy\" failed when trying\n"
			"to apply it to the database."
		)
	if failure_type == "TOOL_ERROR":
		return (
			"The drift-resolver tool crashed with an unhandled exception\n"
			"before it could complete the pipeline. Manual investigation is required."
		)
	if failure_type == "VALIDATION_FAILED":
		return (
			"The drift-resolver tool detected schema drift, but the validator\n"
			"rejected all safe items. No migration was generated or applied."
		)
	return "The drift-resolver tool reported a failure that requires manual attention."


def _what_to_do(failure_type: str, migration_name: str) -> str:
	"""Return numbered recovery steps for the given failure type."""

	name = migration_name or "<migration_name>"
	if failure_type == "TOOL_ERROR":
		return (
			"1. Check the GitHub Actions run logs for the full traceback\n"
			"2. Confirm DATABASE_URL and schema path are set correctly\n"
			"3. Re-run the pipeline after fixing the underlying issue"
		)
	if failure_type == "VALIDATION_FAILED":
		return (
			"1. Check the GitHub Actions run logs for full details\n"
			"2. Review rejected items in the drift report\n"
			"3. Fix the underlying schema or database issue manually\n"
			"4. Re-run the pipeline"
		)
	return (
		"1. Check the GitHub Actions run logs for full details\n"
		"2. Connect to the database and check _prisma_migrations table:\n"
		"   SELECT * FROM _prisma_migrations ORDER BY started_at DESC LIMIT 5;\n"
		"3. If migration is marked failed, resolve it:\n"
		f"   npx prisma migrate resolve --rolled-back {name}\n"
		"4. Fix the underlying issue manually\n"
		"5. Re-run the pipeline"
	)


def _format_drift_items(all_items: list) -> str:
	"""Render classified drift items for the email body."""

	lines: list[str] = []
	for index, item in enumerate(all_items, start=1):
		classification = _item_attr(item, "classification", "UNKNOWN")
		if hasattr(classification, "value"):
			classification = classification.value
		sql = str(_item_attr(item, "sql", "") or "")
		reason = str(_item_attr(item, "reason", "") or "")
		label = f"[{classification}]".ljust(8)
		lines.append(f"{index}. {label} {sql}")
		if reason:
			lines.append(f"         Reason: {reason}")
	return "\n".join(lines) if lines else "No drift items available."


def _item_attr(item: object, name: str, default: str = "") -> object:
	"""Read a field from a DriftItem or a serialized dict."""

	if isinstance(item, dict):
		return item.get(name, default)
	return getattr(item, name, default)


if __name__ == "__main__":
	project_root = Path(__file__).resolve().parents[2]
	if str(project_root) not in sys.path:
		sys.path.insert(0, str(project_root))

	try:
		from dotenv import load_dotenv

		load_dotenv(project_root / ".env")
	except Exception:
		pass

	print("──────── EMAIL BODY PREVIEW ────────")
	preview_items = [
		type("Item", (), {
			"classification": type("C", (), {"value": "SAFE"})(),
			"sql": 'ALTER TABLE "User" ADD COLUMN "bio" TEXT',
			"reason": "Adding a nullable column is safe",
		})(),
		type("Item", (), {
			"classification": type("C", (), {"value": "UNSAFE"})(),
			"sql": 'ALTER TABLE "User" DROP COLUMN "name"',
			"reason": "Dropping a column — manual review required",
		})(),
	]
	os.environ.setdefault("NOTIFY_REPO_URL", "https://github.com/kidu90/prisma-Drift-Resolver")
	print(
		_build_email_body(
			"EXECUTION_FAILED",
			"20260612093220_drift_auto_resolve",
			"ERROR: relation 'User' does not exist\nDbError code: 42P01",
			'ALTER TABLE "User" ADD COLUMN "bio" TEXT;',
			"postgresql://testuser:testpass@localhost:5432/testdb",
			all_items=preview_items,
		)
	)
	print("────────────────────────────────────")
	print()

	configured = check_email_config()
	if not configured:
		print("[NOTIFIER] Skipping test send — email env vars are not set.")
		print("[NOTIFIER] Set NOTIFY_EMAIL_FROM, NOTIFY_EMAIL_PASSWORD, and NOTIFY_EMAIL_TO in .env")
		sys.exit(0)

	result = send_failure_notification(
		failure_type="EXECUTION_FAILED",
		migration_name="20260612093220_drift_auto_resolve",
		error_message="ERROR: relation 'User' does not exist\nDbError code: 42P01",
		sql_content='ALTER TABLE "User" ADD COLUMN "bio" TEXT;',
		db_url="postgresql://testuser:testpass@localhost:5432/testdb",
	)
	print("[NOTIFIER] NotificationResult:")
	print(f"  sent       = {result.sent}")
	print(f"  recipients = {result.recipients}")
	print(f"  subject    = {result.subject}")
	print(f"  error      = {result.error}")
