
from __future__ import annotations

from pathlib import Path
import sys
from typing import Optional

import sqlglot
from sqlglot import exp

try:
	from drift_resolver.models.drift_item import DriftClassification, DriftItem
except ModuleNotFoundError:
	project_root = Path(__file__).resolve().parents[2]
	if str(project_root) not in sys.path:
		sys.path.insert(0, str(project_root))
	from drift_resolver.models.drift_item import DriftClassification, DriftItem


def clean_sql_input(raw_sql: str) -> str:
	# Remove empty lines and comments from raw SQL to avoid parsing issues.
	cleaned_lines: list[str] = []
	for line in raw_sql.splitlines():
		stripped = line.strip()
		if not stripped or stripped.startswith("--"):
			continue
		cleaned_lines.append(line)
	return "\n".join(cleaned_lines).strip()


def _extract_table_name(node: exp.Expression) -> Optional[str]:
	"""Extract the first table name found in an AST node, if present."""

	# sqlglot stores table references as Table expressions across many statement types.
	table_expr = node.find(exp.Table)
	return table_expr.name if table_expr else None


def _extract_column_name(node: exp.Expression) -> Optional[str]:
	"""Extract a column name by preferring ColumnDef, then Column nodes."""

	# For ADD COLUMN, sqlglot uses ColumnDef
	column_def = node.find(exp.ColumnDef)
	if column_def and column_def.name:
		return column_def.name

	column_expr = node.find(exp.Column)
	if column_expr and column_expr.name:
		return column_expr.name

	return None


def _parse_single_statement(node: exp.Expression) -> Optional[DriftItem]:
	

	statement_class = node.__class__.__name__

	try:
		normalized_sql = node.sql(dialect="postgres")
	except Exception:
		normalized_sql = str(node)

	# sqlglot models ALTER TABLE 
	if isinstance(node, exp.Alter) and str(node.args.get("kind", "")).upper() == "TABLE":
		table_name = _extract_table_name(node)
		actions = node.args.get("actions") or []
		if not actions:
			return DriftItem(
				sql=normalized_sql,
				statement_type="AlterTable",
				table_name=table_name,
				column_name=None,
				classification=DriftClassification.UNKNOWN,
			)

		first_action = actions[0]
		action_type = first_action.__class__.__name__
		column_name = _extract_column_name(first_action) or _extract_column_name(node)

		if action_type in {"Add", "ColumnDef"}:
			statement_type = "AlterTable_Add"
		elif action_type == "Drop":
			statement_type = "AlterTable_Drop"
		elif action_type == "AlterColumn":
			statement_type = "AlterTable_AlterColumn"
		elif action_type in {"RenameColumn", "RenameTable"}:
			statement_type = "AlterTable_Rename"
		else:
			statement_type = f"AlterTable_{action_type}"

		return DriftItem(
			sql=normalized_sql,
			statement_type=statement_type,
			table_name=table_name,
			column_name=column_name,
			classification=DriftClassification.UNKNOWN,
		)

	if isinstance(node, exp.Create):
		kind = str(node.args.get("kind", "")).upper()
		table_name = _extract_table_name(node)

		if kind == "TABLE":
			statement_type = "CreateTable"
		elif kind == "INDEX":
			statement_type = "CreateIndex"
		else:
			statement_type = "Create"

		return DriftItem(
			sql=normalized_sql,
			statement_type=statement_type,
			table_name=table_name,
			column_name=None,
			classification=DriftClassification.UNKNOWN,
		)

	if isinstance(node, exp.Drop):
		kind = str(node.args.get("kind", "")).upper()
		expressions = node.args.get("expressions") or []

		table_name: Optional[str] = None
		if expressions:
			first_expr = expressions[0]
			table_name = getattr(first_expr, "name", None)

		# For most Prisma drop statements, sqlglot stores the target in `this`.
		if not table_name:
			table_name = _extract_table_name(node)

		if kind == "TABLE":
			statement_type = "DropTable"
		elif kind == "INDEX":
			statement_type = "DropIndex"
		else:
			statement_type = "Drop"

		return DriftItem(
			sql=normalized_sql,
			statement_type=statement_type,
			table_name=table_name,
			column_name=None,
			classification=DriftClassification.UNKNOWN,
		)

	print(f"[PARSER] Unknown statement type: {statement_class} - marking as UNKNOWN")
	return DriftItem(
		sql=normalized_sql,
		statement_type=statement_class,
		table_name=None,
		column_name=None,
		classification=DriftClassification.UNKNOWN,
	)


def parse_drift_sql(raw_sql: str) -> list[DriftItem]:


	cleaned_sql = clean_sql_input(raw_sql)
	if not cleaned_sql:
		print("[PARSER] Parsing 0 statements from diff output.")
		print("[PARSER] Successfully parsed 0 DriftItems.")
		return []

	try:
		nodes = sqlglot.parse(cleaned_sql, dialect="postgres")
	except Exception as exc:
		print(f"[PARSER] Failed to parse SQL diff: {exc}")
		print("[PARSER] Successfully parsed 0 DriftItems.")
		return []

	print(f"[PARSER] Parsing {len(nodes)} statements from diff output.")

	parsed_items: list[DriftItem] = []
	for node in nodes:
		if node is None:
			continue

		try:
			item = _parse_single_statement(node)
		except Exception as exc:
			print(f"[PARSER] Failed to parse statement: {exc}")
			continue

		if item is not None:
			parsed_items.append(item)

	print(f"[PARSER] Successfully parsed {len(parsed_items)} DriftItems.")
	return parsed_items


if __name__ == "__main__":

	safe_fixture = Path("drift_resolver/tests/fixtures/safe_drift.sql")
	unsafe_fixture = Path("drift_resolver/tests/fixtures/unsafe_drift.sql")

	safe_sql = safe_fixture.read_text(encoding="utf-8")
	unsafe_sql = unsafe_fixture.read_text(encoding="utf-8")
	combined_sql = f"{safe_sql}\n{unsafe_sql}"

	items = parse_drift_sql(combined_sql)

	print("\n[PARSER] Parsed DriftItems")
	for index, item in enumerate(items, start=1):
		print(f"{index}. sql={item.sql}")
		print(f"   statement_type={item.statement_type}")
		print(f"   table_name={item.table_name}")
		print(f"   column_name={item.column_name}")
		print(f"   classification={item.classification}")
		print(f"   reason={item.reason}")
		print(f"   auto_resolved={item.auto_resolved}")
		print(f"   rollback_sql={item.rollback_sql}")
