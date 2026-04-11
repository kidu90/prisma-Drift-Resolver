from __future__ import annotations

from pathlib import Path
import sys
from typing import Optional

try:
	from drift_resolver.models.drift_item import DriftClassification, DriftItem
except ModuleNotFoundError:
	project_root = Path(__file__).resolve().parents[2]
	if str(project_root) not in sys.path:
		sys.path.insert(0, str(project_root))
	from drift_resolver.models.drift_item import DriftClassification, DriftItem


def classify_drift_items(items: list[DriftItem]) -> list[DriftItem]:
	"""Classify all drift items in-place and return them."""

	print(f"[CLASSIFIER] Classifying {len(items)} drift items...")

	for item in items:
		_classify_single(item)

	safe_count = sum(1 for item in items if item.classification == DriftClassification.SAFE)
	unsafe_count = sum(1 for item in items if item.classification == DriftClassification.UNSAFE)
	unknown_count = sum(1 for item in items if item.classification == DriftClassification.UNKNOWN)

	print(
		f"[CLASSIFIER] Results: {safe_count} SAFE, {unsafe_count} UNSAFE, {unknown_count} UNKNOWN"
	)
	return items


def _classify_single(item: DriftItem) -> DriftItem:
	"""Classify one drift item using ordered rules and fallbacks."""

	try:
		# Rule 2 must be checked before Rule 1 because they overlap.
		if _is_add_with_default(item):
			item.classification = DriftClassification.SAFE
			item.reason = "Adding a column with a default is safe — existing rows get the default value"
			item.rollback_sql = _build_rollback(item)
			return item

		if _is_add_nullable_column(item):
			item.classification = DriftClassification.SAFE
			item.reason = "Adding a nullable column is safe — existing rows are unaffected"
			item.rollback_sql = _build_rollback(item)
			return item

		if _is_change_default(item):
			item.classification = DriftClassification.SAFE
			item.reason = "Changing a column default only affects future inserts — safe"
			item.rollback_sql = _build_rollback(item)
			return item

		if _is_create_index(item):
			item.classification = DriftClassification.SAFE
			item.reason = "Creating an index does not change data — safe"
			item.rollback_sql = _build_rollback(item)
			return item

		if _is_create_table(item):
			item.classification = DriftClassification.SAFE
			item.reason = "Creating a new table does not affect existing data — safe"
			item.rollback_sql = _build_rollback(item)
			return item

		if _is_drop_column(item):
			item.classification = DriftClassification.UNSAFE
			item.reason = "Dropping a column permanently deletes its data — manual review required"
			item.rollback_sql = None
			return item

		if _is_drop_table(item):
			item.classification = DriftClassification.UNSAFE
			item.reason = "Dropping a table permanently deletes all its data — manual review required"
			item.rollback_sql = None
			return item

		if _is_rename(item):
			item.classification = DriftClassification.UNSAFE
			item.reason = "Renaming breaks existing application queries — manual review required"
			item.rollback_sql = None
			return item

		if _is_type_change(item):
			item.classification = DriftClassification.UNSAFE
			item.reason = "Changing a column type may corrupt or truncate existing data — manual review required"
			item.rollback_sql = None
			return item

		if _is_not_null_no_default(item):
			item.classification = DriftClassification.UNSAFE
			item.reason = "Adding NOT NULL without a default fails on tables with existing rows — manual review required"
			item.rollback_sql = None
			return item

		if _is_drop_index(item):
			item.classification = DriftClassification.SAFE
			item.reason = "Dropping an index does not affect data — safe but monitor query performance"
			item.rollback_sql = _build_rollback(item)
			return item

		item.classification = DriftClassification.UNSAFE
		item.reason = "Unrecognized change type — defaulting to unsafe, manual review required"
		item.rollback_sql = None
		return item
	except Exception as exc:
		print(f"[CLASSIFIER] Failed to classify statement safely: {exc}")
		item.classification = DriftClassification.UNSAFE
		item.reason = "Unrecognized change type — defaulting to unsafe, manual review required"
		item.rollback_sql = None
		return item


def _is_add_nullable_column(item: DriftItem) -> bool:
	"""Return True when ALTER TABLE ADD introduces a nullable column."""

	sql_upper = item.sql.upper()
	return item.statement_type == "AlterTable_Add" and "NOT NULL" not in sql_upper and "DEFAULT" not in sql_upper


def _is_add_with_default(item: DriftItem) -> bool:
	"""Return True when ALTER TABLE ADD includes DEFAULT and no NOT NULL."""

	sql_upper = item.sql.upper()
	return item.statement_type == "AlterTable_Add" and "DEFAULT" in sql_upper and "NOT NULL" not in sql_upper


def _is_change_default(item: DriftItem) -> bool:
	"""Return True when ALTER COLUMN changes default without changing type."""

	sql_upper = item.sql.upper()
	return (
		item.statement_type == "AlterTable_AlterColumn"
		and ("SET DEFAULT" in sql_upper or "DROP DEFAULT" in sql_upper)
		and "TYPE" not in sql_upper
	)


def _is_create_index(item: DriftItem) -> bool:
	"""Return True when the statement creates an index."""

	return item.statement_type == "CreateIndex"


def _is_create_table(item: DriftItem) -> bool:
	"""Return True when the statement creates a table."""

	return item.statement_type == "CreateTable"


def _is_drop_column(item: DriftItem) -> bool:
	"""Return True when the statement drops a column."""

	return item.statement_type == "AlterTable_Drop"


def _is_drop_table(item: DriftItem) -> bool:
	"""Return True when the statement drops a table."""

	return item.statement_type == "DropTable"


def _is_rename(item: DriftItem) -> bool:
	"""Return True when the statement renames a table or column."""

	return item.statement_type == "AlterTable_Rename"


def _is_type_change(item: DriftItem) -> bool:
	"""Return True when ALTER COLUMN performs a data type change."""

	sql_upper = item.sql.upper()
	return item.statement_type == "AlterTable_AlterColumn" and (
		"SET DATA TYPE" in sql_upper or "TYPE" in sql_upper
	)


def _is_not_null_no_default(item: DriftItem) -> bool:
	"""Return True when ADD COLUMN uses NOT NULL without DEFAULT."""

	sql_upper = item.sql.upper()
	return item.statement_type == "AlterTable_Add" and "NOT NULL" in sql_upper and "DEFAULT" not in sql_upper


def _is_drop_index(item: DriftItem) -> bool:
	"""Return True when the statement drops an index."""

	return item.statement_type == "DropIndex"


def _extract_index_name(sql: str) -> Optional[str]:
	"""Extract index name from CREATE INDEX or DROP INDEX SQL."""

	clean_sql = sql.strip().rstrip(";")
	if not clean_sql:
		return None

	tokens = clean_sql.split()
	upper_tokens = [token.upper() for token in tokens]

	if "INDEX" not in upper_tokens:
		return None

	index_pos = upper_tokens.index("INDEX")

	if index_pos == 0 or index_pos + 1 >= len(tokens):
		return None

	if upper_tokens[index_pos - 1] == "CREATE":
		if "ON" not in upper_tokens[index_pos + 1 :]:
			return None
		name_token = tokens[index_pos + 1]
		return name_token.strip('"').strip("'")

	if upper_tokens[index_pos - 1] == "DROP":
		next_token = upper_tokens[index_pos + 1]
		if next_token == "IF" and index_pos + 4 < len(tokens):
			name_token = tokens[index_pos + 4]
			return name_token.strip('"').strip("'")
		name_token = tokens[index_pos + 1]
		return name_token.strip('"').strip("'")

	return None


def _build_rollback(item: DriftItem) -> Optional[str]:
	"""Build rollback SQL for safe statement types when possible."""

	if item.statement_type == "AlterTable_Add" and item.table_name and item.column_name:
		return f"ALTER TABLE {item.table_name} DROP COLUMN {item.column_name};"

	if item.statement_type == "CreateIndex":
		index_name = _extract_index_name(item.sql)
		if index_name:
			return f"DROP INDEX IF EXISTS {index_name};"
		return None

	if item.statement_type == "CreateTable" and item.table_name:
		return f"DROP TABLE IF EXISTS {item.table_name};"

	return None


if __name__ == "__main__":
	try:
		from drift_resolver.modules.parser import parse_drift_sql
	except ModuleNotFoundError:
		project_root = Path(__file__).resolve().parents[2]
		if str(project_root) not in sys.path:
			sys.path.insert(0, str(project_root))
		from drift_resolver.modules.parser import parse_drift_sql

	safe_fixture = Path("drift_resolver/tests/fixtures/safe_drift.sql")
	unsafe_fixture = Path("drift_resolver/tests/fixtures/unsafe_drift.sql")

	safe_sql = safe_fixture.read_text(encoding="utf-8")
	unsafe_sql = unsafe_fixture.read_text(encoding="utf-8")

	safe_items = parse_drift_sql(safe_sql)
	unsafe_items = parse_drift_sql(unsafe_sql)
	combined_items = safe_items + unsafe_items

	classify_drift_items(combined_items)

	headers = ["SQL", "statement_type", "classification", "reason"]
	rows: list[list[str]] = []
	for item in combined_items:
		rows.append(
			[
				item.sql,
				item.statement_type,
				item.classification.value,
				item.reason,
			]
		)

	widths = [len(header) for header in headers]
	for row in rows:
		for idx, value in enumerate(row):
			widths[idx] = max(widths[idx], len(value))

	separator = " | ".join("-" * width for width in widths)
	print()
	print(" | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
	print(separator)
	for row in rows:
		print(" | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))

	safe_count = sum(1 for item in combined_items if item.classification == DriftClassification.SAFE)
	unsafe_count = sum(1 for item in combined_items if item.classification == DriftClassification.UNSAFE)
	print(f"\n[CLASSIFIER] Expected SAFE=5, UNSAFE=5 | Actual SAFE={safe_count}, UNSAFE={unsafe_count}")
