from __future__ import annotations

from pathlib import Path

from drift_resolver.models.drift_item import DriftClassification, DriftItem
from drift_resolver.modules.classifier import classify_drift_items
from drift_resolver.modules.parser import parse_drift_sql


def test_add_nullable_column_is_safe() -> None:
	item = DriftItem(
		sql='ALTER TABLE "users" ADD COLUMN "bio" TEXT',
		statement_type="AlterTable_Add",
		table_name="users",
		column_name="bio",
		classification=DriftClassification.UNKNOWN,
	)

	classify_drift_items([item])

	assert item.classification == DriftClassification.SAFE
	assert "nullable" in item.reason.lower()
	assert item.rollback_sql is not None
	assert "DROP COLUMN" in item.rollback_sql


def test_add_column_with_default_is_safe() -> None:
	item = DriftItem(
		sql='ALTER TABLE "users" ADD COLUMN "age" INTEGER DEFAULT 0',
		statement_type="AlterTable_Add",
		table_name="users",
		column_name="age",
		classification=DriftClassification.UNKNOWN,
	)

	classify_drift_items([item])

	assert item.classification == DriftClassification.SAFE
	assert "default" in item.reason.lower()


def test_add_not_null_no_default_is_unsafe() -> None:
	item = DriftItem(
		sql='ALTER TABLE "users" ADD COLUMN "verified" BOOLEAN NOT NULL',
		statement_type="AlterTable_Add",
		table_name="users",
		column_name="verified",
		classification=DriftClassification.UNKNOWN,
	)

	classify_drift_items([item])

	assert item.classification == DriftClassification.UNSAFE
	assert "NOT NULL" in item.reason or "not null" in item.reason.lower()


def test_drop_column_is_unsafe() -> None:
	item = DriftItem(
		sql='ALTER TABLE "users" DROP COLUMN "password"',
		statement_type="AlterTable_Drop",
		table_name="users",
		column_name="password",
		classification=DriftClassification.UNKNOWN,
	)

	classify_drift_items([item])

	assert item.classification == DriftClassification.UNSAFE
	assert item.rollback_sql is None


def test_drop_table_is_unsafe() -> None:
	item = DriftItem(
		sql='DROP TABLE "sessions"',
		statement_type="DropTable",
		table_name="sessions",
		classification=DriftClassification.UNKNOWN,
	)

	classify_drift_items([item])

	assert item.classification == DriftClassification.UNSAFE


def test_create_table_is_safe() -> None:
	item = DriftItem(
		sql='CREATE TABLE "audit_logs" ("id" SERIAL PRIMARY KEY)',
		statement_type="CreateTable",
		table_name="audit_logs",
		classification=DriftClassification.UNKNOWN,
	)

	classify_drift_items([item])

	assert item.classification == DriftClassification.SAFE
	assert item.rollback_sql == "DROP TABLE IF EXISTS audit_logs;"


def test_create_index_is_safe() -> None:
	item = DriftItem(
		sql='CREATE INDEX "idx_users_email" ON "users"("email")',
		statement_type="CreateIndex",
		table_name="users",
		classification=DriftClassification.UNKNOWN,
	)

	classify_drift_items([item])

	assert item.classification == DriftClassification.SAFE
	assert item.rollback_sql is not None
	assert "DROP INDEX" in item.rollback_sql


def test_rename_is_unsafe() -> None:
	item = DriftItem(
		sql='ALTER TABLE "users" RENAME COLUMN "name" TO "full_name"',
		statement_type="AlterTable_Rename",
		table_name="users",
		column_name="name",
		classification=DriftClassification.UNKNOWN,
	)

	classify_drift_items([item])

	assert item.classification == DriftClassification.UNSAFE


def test_type_change_is_unsafe() -> None:
	item = DriftItem(
		sql='ALTER TABLE "users" ALTER COLUMN "age" TYPE VARCHAR(10)',
		statement_type="AlterTable_AlterColumn",
		table_name="users",
		column_name="age",
		classification=DriftClassification.UNKNOWN,
	)

	classify_drift_items([item])

	assert item.classification == DriftClassification.UNSAFE


def test_change_default_is_safe() -> None:
	item = DriftItem(
		sql="ALTER TABLE \"users\" ALTER COLUMN \"status\" SET DEFAULT 'active'",
		statement_type="AlterTable_AlterColumn",
		table_name="users",
		column_name="status",
		classification=DriftClassification.UNKNOWN,
	)

	classify_drift_items([item])

	assert item.classification == DriftClassification.SAFE


def test_all_safe_fixtures_classified_safe() -> None:
	fixture_path = Path("drift_resolver/tests/fixtures/safe_drift.sql")
	sql = fixture_path.read_text(encoding="utf-8")

	items = parse_drift_sql(sql)
	classify_drift_items(items)

	assert all(item.classification == DriftClassification.SAFE for item in items)


def test_all_unsafe_fixtures_classified_unsafe() -> None:
	fixture_path = Path("drift_resolver/tests/fixtures/unsafe_drift.sql")
	sql = fixture_path.read_text(encoding="utf-8")

	items = parse_drift_sql(sql)
	classify_drift_items(items)

	assert all(item.classification == DriftClassification.UNSAFE for item in items)


def test_no_unknown_after_classification() -> None:
	safe_sql = Path("drift_resolver/tests/fixtures/safe_drift.sql").read_text(encoding="utf-8")
	unsafe_sql = Path("drift_resolver/tests/fixtures/unsafe_drift.sql").read_text(encoding="utf-8")

	items = parse_drift_sql(f"{safe_sql}\n{unsafe_sql}")
	classify_drift_items(items)

	assert all(item.classification != DriftClassification.UNKNOWN for item in items)
