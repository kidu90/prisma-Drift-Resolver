from __future__ import annotations

from pathlib import Path

import pytest

from drift_resolver.models.drift_item import DriftClassification, DriftItem
from drift_resolver.modules.generator import generate_migration, get_migration_preview
from drift_resolver.modules.validator import validate_safe_items


def _make_safe_items() -> list[DriftItem]:
	"""Create safe items that exercise normalization and rollback generation."""

	return [
		DriftItem(
			sql='ALTER TABLE "users" ADD COLUMN "bio" TEXT',
			statement_type="AlterTable_Add",
			table_name="users",
			column_name="bio",
			classification=DriftClassification.SAFE,
			reason="Adding a nullable column is safe",
		),
		DriftItem(
			sql='CREATE INDEX "idx_users_email" ON "users"("email")',
			statement_type="CreateIndex",
			table_name="users",
			classification=DriftClassification.SAFE,
			reason="Creating an index is safe",
		),
	]


def test_validate_safe_items_normalizes_and_generates_rollback() -> None:
	"""Validator should append semicolons and fill in rollback SQL when missing."""

	result = validate_safe_items(_make_safe_items())

	assert result.valid is True
	assert len(result.validated_items) == 2
	assert not result.rejected_items
	assert result.validated_items[0].sql.endswith(";")
	assert result.validated_items[0].rollback_sql is not None
	assert result.validated_items[1].rollback_sql is not None


def test_validate_safe_items_rejects_destructive_sql() -> None:
	"""Validator should reject obvious destructive SQL in the safe queue."""

	item = DriftItem(
		sql='DROP TABLE "users"',
		statement_type="DropTable",
		table_name="users",
		classification=DriftClassification.SAFE,
	)

	result = validate_safe_items([item])

	assert result.valid is False
	assert len(result.rejected_items) == 1
	assert "DROP statement" in result.rejection_reasons[item.sql]


def test_generator_preview_contains_header_and_sql() -> None:
	"""Preview should render the full migration content without touching disk."""

	preview = get_migration_preview(_make_safe_items())

	assert "-- Drift Auto-Resolution Migration" in preview
	assert "ALTER TABLE \"users\" ADD COLUMN \"bio\" TEXT;" in preview


def test_generate_migration_writes_folder_and_sql(tmp_path: Path) -> None:
	"""Generator should write a Prisma migration folder and migration.sql file."""

	migrations_dir = tmp_path / "prisma" / "migrations"
	migrations_dir.mkdir(parents=True)

	result = generate_migration(_make_safe_items(), migrations_dir=str(migrations_dir))

	assert result.folder_name.endswith("_drift_auto_resolve")
	assert Path(result.folder_path).is_dir()
	assert Path(result.sql_path).is_file()
	assert result.item_count == 2
	assert "-- Changes:" in result.sql_content


def test_generate_migration_missing_dir_raises(tmp_path: Path) -> None:
	"""Generator should fail fast if the migrations directory is missing."""

	missing_dir = tmp_path / "does-not-exist"

	with pytest.raises(FileNotFoundError):
		generate_migration(_make_safe_items(), migrations_dir=str(missing_dir))