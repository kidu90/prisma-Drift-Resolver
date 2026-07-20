

from __future__ import annotations

from pathlib import Path

from drift_resolver.models.drift_item import DriftClassification
from drift_resolver.modules.classifier import classify_drift_items
from drift_resolver.modules.parser import parse_drift_sql, split_compound_alter


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


def test_split_compound_alter_drop_and_add() -> None:
	"""Compound ALTER TABLE statements should split into single actions."""

	sql = 'ALTER TABLE "User" DROP COLUMN "old_col", ADD COLUMN "new_col" TEXT;'
	result = split_compound_alter(sql)

	assert len(result) == 2
	assert "DROP COLUMN" in result[0]
	assert "ADD COLUMN" in result[1]
	assert all('ALTER TABLE "User"' in statement for statement in result)


def test_compound_alter_classifies_correctly() -> None:
	"""Compound ALTER TABLE statements should classify each action separately."""

	sql = '''ALTER TABLE "User" DROP COLUMN "old_col",
	         ADD COLUMN "new_col" TEXT;'''
	items = parse_drift_sql(sql)
	classify_drift_items(items)

	assert len(items) == 2
	drop_item = next(item for item in items if "DROP" in item.sql.upper())
	add_item = next(item for item in items if "ADD" in item.sql.upper())
	assert drop_item.classification.value == "UNSAFE"
	assert add_item.classification.value == "SAFE"


def test_single_alter_not_split() -> None:
	"""Single ALTER TABLE statements should remain intact."""

	sql = 'ALTER TABLE "User" ADD COLUMN "bio" TEXT;'
	result = split_compound_alter(sql)

	assert len(result) == 1


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
