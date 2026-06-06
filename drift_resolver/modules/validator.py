from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

try:
	from drift_resolver.models.drift_item import DriftClassification, DriftItem
except ModuleNotFoundError:
	project_root = Path(__file__).resolve().parents[2]
	if str(project_root) not in sys.path:
		sys.path.insert(0, str(project_root))
	from drift_resolver.models.drift_item import DriftClassification, DriftItem


@dataclass
class ValidationResult:
	"""Represent the result of pre-flight validation for safe drift items."""

	valid: bool
	validated_items: list[DriftItem]
	rejected_items: list[DriftItem]
	rejection_reasons: dict[str, str]


def validate_safe_items(safe_items: list[DriftItem]) -> ValidationResult:
	"""Validate safe drift items before migration generation."""

	print(f"[VALIDATOR] Validating {len(safe_items)} safe items...")

	validated_items: list[DriftItem] = []
	rejected_items: list[DriftItem] = []
	rejection_reasons: dict[str, str] = {}

	for item in safe_items:
		is_valid, reason = _validate_single(item)
		if is_valid:
			validated_items.append(item)
			continue

		rejected_items.append(item)
		rejection_reasons[item.sql] = reason
		print(f"[VALIDATOR] Rejected safe item: {reason}")

	print(f"[VALIDATOR] {len(validated_items)} passed, {len(rejected_items)} rejected.")
	return ValidationResult(
		valid=not rejected_items,
		validated_items=validated_items,
		rejected_items=rejected_items,
		rejection_reasons=rejection_reasons,
	)


def _validate_single(item: DriftItem) -> tuple[bool, str]:
	"""Validate one safe item and normalize it when possible."""

	if not item.sql.strip():
		return False, "SQL statement is empty"

	if not item.table_name:
		return False, "Cannot determine target table"

	sql_upper = item.sql.upper()
	if "DROP COLUMN" in sql_upper or "DROP TABLE" in sql_upper:
		return False, "DROP statement found in safe queue — possible misclassification"

	if "TRUNCATE" in sql_upper or "DELETE FROM" in sql_upper:
		return False, "Destructive DML statement found — rejected"

	# Normalize statement termination so the generated migration is always valid SQL.
	item.sql = item.sql.strip()
	if not item.sql.endswith(";"):
		item.sql += ";"

	if item.statement_type == "AlterTable_Add" and "NOT NULL" in sql_upper and "DEFAULT" not in sql_upper:
		return False, "NOT NULL column without DEFAULT slipped through classifier"

	if item.rollback_sql is None and item.statement_type == "CreateTable":
		item.rollback_sql = f"DROP TABLE IF EXISTS {item.table_name};"

	if item.rollback_sql is None and item.statement_type == "AlterTable_Add" and item.column_name:
		item.rollback_sql = f"ALTER TABLE {item.table_name} DROP COLUMN {item.column_name};"

	if item.rollback_sql is None and item.statement_type == "CreateIndex":
		index_name = _extract_index_name(item.sql)
		if index_name:
			item.rollback_sql = f"DROP INDEX IF EXISTS {index_name};"

	return True, ""


def _extract_index_name(sql: str) -> str | None:
	"""Extract an index name from CREATE INDEX SQL for rollback generation."""

	clean_sql = sql.strip().rstrip(";")
	if not clean_sql:
		return None

	tokens = clean_sql.split()
	upper_tokens = [token.upper() for token in tokens]

	if "INDEX" not in upper_tokens:
		return None

	index_pos = upper_tokens.index("INDEX")
	if index_pos + 1 >= len(tokens):
		return None

	if upper_tokens[index_pos - 1] == "CREATE":
		name_token = tokens[index_pos + 1]
		return name_token.strip('"').strip("'")

	return None
