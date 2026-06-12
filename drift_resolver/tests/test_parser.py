

from __future__ import annotations

from pathlib import Path

from drift_resolver.models.drift_item import DriftClassification
from drift_resolver.modules.parser import parse_drift_sql


def test_parse_add_nullable_column() -> None:
	"""ALTER TABLE ADD COLUMN should map to AlterTable_Add."""

	sql = 'ALTER TABLE "users" ADD COLUMN "bio" TEXT;'
	result = parse_drift_sql(sql)

	assert len(result) == 1
	assert result[0].statement_type == "AlterTable_Add"
	assert result[0].table_name == "users"
	assert result[0].column_name == "bio"
	assert result[0].classification == DriftClassification.UNKNOWN


def test_parse_drop_column() -> None:
	"""ALTER TABLE DROP COLUMN should map to AlterTable_Drop."""

	sql = 'ALTER TABLE "users" DROP COLUMN "password";'
	result = parse_drift_sql(sql)

	assert result[0].statement_type == "AlterTable_Drop"
	assert result[0].table_name == "users"
	assert result[0].column_name == "password"


def test_parse_create_table() -> None:
	"""CREATE TABLE should map to CreateTable with table extracted."""

	sql = 'CREATE TABLE "audit_logs" ("id" SERIAL PRIMARY KEY);'
	result = parse_drift_sql(sql)

	assert result[0].statement_type == "CreateTable"
	assert result[0].table_name == "audit_logs"


def test_parse_drop_table() -> None:
	"""DROP TABLE should map to DropTable with table extracted."""

	sql = 'DROP TABLE "sessions";'
	result = parse_drift_sql(sql)

	assert result[0].statement_type == "DropTable"
	assert result[0].table_name == "sessions"


def test_parse_create_index() -> None:
	"""CREATE INDEX should map to CreateIndex."""

	sql = 'CREATE INDEX "idx_users_email" ON "users"("email");'
	result = parse_drift_sql(sql)

	assert result[0].statement_type == "CreateIndex"


def test_table_name_preserves_case() -> None:
	"""Quoted PostgreSQL identifiers should preserve their original casing."""

	sql = 'ALTER TABLE "User" ADD COLUMN "bio" TEXT;'
	items = parse_drift_sql(sql)

	assert items[0].table_name == "User"
	assert items[0].table_name != "users"


def test_empty_input_returns_empty_list() -> None:
	"""Empty SQL input should return no items."""

	result = parse_drift_sql("")

	assert result == []


def test_comment_only_input_returns_empty_list() -> None:
	"""Comment-only SQL input should return no items."""

	sql = "-- This is a comment\n-- Another comment"
	result = parse_drift_sql(sql)

	assert result == []


def test_multiple_statements_parsed_correctly() -> None:
	"""Fixture file with safe drifts should parse into five UNKNOWN items."""

	fixture_path = Path("drift_resolver/tests/fixtures/safe_drift.sql")
	sql = fixture_path.read_text(encoding="utf-8")

	result = parse_drift_sql(sql)

	assert len(result) == 5
	assert all(item.classification == DriftClassification.UNKNOWN for item in result)
