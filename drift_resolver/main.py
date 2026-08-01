from __future__ import annotations

import os
import sys
from pathlib import Path

import click

try:
    from drift_resolver.modules.acquisition import get_prisma_drift
    from drift_resolver.modules.classifier import classify_drift_items
    from drift_resolver.modules.config_loader import load_config
    from drift_resolver.modules.executor import ExecutionResult, execute_migration, verify_migration_applied
    from drift_resolver.modules.generator import MigrationFile, generate_migration
    from drift_resolver.modules.parser import parse_drift_sql
    from drift_resolver.modules.reporter import DriftReport, generate_report
    from drift_resolver.modules.validator import ValidationResult, validate_safe_items
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from drift_resolver.modules.acquisition import get_prisma_drift
    from drift_resolver.modules.classifier import classify_drift_items
    from drift_resolver.modules.config_loader import load_config
    from drift_resolver.modules.executor import ExecutionResult, execute_migration, verify_migration_applied
    from drift_resolver.modules.generator import MigrationFile, generate_migration
    from drift_resolver.modules.parser import parse_drift_sql
    from drift_resolver.modules.reporter import DriftReport, generate_report
    from drift_resolver.modules.validator import ValidationResult, validate_safe_items


<<<<<<< HEAD
def _post_final_comment(report: DriftReport) -> None:
    """Post the final summary comment when PR metadata is available."""

    pr_number = os.environ.get("PR_NUMBER", "")
    if pr_number:
        post_result_comment(report, pr_number)


def _resolve_migrations_dir(config: dict | None) -> str:
    """Choose the migrations directory, preferring CI overrides when present."""

    if os.environ.get("DRIFT_MIGRATIONS_DIR"):
        return os.environ["DRIFT_MIGRATIONS_DIR"]

    if config and config.get("settings", {}).get("migrations_dir"):
        return config["settings"]["migrations_dir"]

    return "./prisma/migrations"


def _ensure_directory(path: str) -> None:
    """Create a directory if it does not already exist."""

    Path(path).mkdir(parents=True, exist_ok=True)


=======
>>>>>>> 946b42b (refactor: remove approval gate, connect to GitHub Actions)
@click.command()
@click.option("--schema", "schema_path", default="./prisma/schema.prisma", show_default=True, help="Path to schema.prisma")
@click.option("--db-url", "db_url", default=None, envvar="DATABASE_URL", help="Database URL")
@click.option("--report-path", "report_path", default=".", show_default=True, help="Directory for report artifacts")
@click.option("--dry-run", is_flag=True, default=False, help="Detect and classify drift without applying changes")
def main(schema_path: str, db_url: str | None, report_path: str, dry_run: bool) -> None:
    """Run the full drift-resolver pipeline (fully automatic for safe changes)."""

    items: list = []
    validation: ValidationResult | None = None
    migration_file: MigrationFile | None = None
    execution: ExecutionResult | None = None
    report: DriftReport | None = None
    config: dict | None = None

    try:
        # STEP 1 — Load config
        print("[MAIN] STEP 1 — Load config")
        config = load_config()
        print("[MAIN] Config loaded.")

        resolved_db_url = db_url or os.environ.get("DATABASE_URL", "")
        if not resolved_db_url:
            raise ValueError("Database URL is required. Set DATABASE_URL or pass --db-url.")

        # STEP 2 — Acquisition
        print("[MAIN] STEP 2 — Acquisition")
        acquisition_result = get_prisma_drift(schema_path=schema_path, db_url=resolved_db_url)
        if acquisition_result.error:
            print(f"[MAIN] Acquisition failed: {acquisition_result.error}")
            report = generate_report([], report_dir=report_path)
            sys.exit(3)

        if not acquisition_result.has_drift:
            report = generate_report([], report_dir=report_path)
            print("[MAIN] No drift detected. Database is in sync.")
            sys.exit(0)

        # STEP 3 — Parse
        print("[MAIN] STEP 3 — Parse")
        items = parse_drift_sql(acquisition_result.raw_sql)

        # STEP 4 — Classify
        print("[MAIN] STEP 4 — Classify")
        items = classify_drift_items(items)
        safe_items = [item for item in items if item.classification.value == "SAFE"]
        unsafe_items = [item for item in items if item.classification.value == "UNSAFE"]

        # STEP 5 — Log unsafe items clearly
        print("[MAIN] STEP 5 — Log unsafe items clearly")
        if unsafe_items:
            print(f"[MAIN] {len(unsafe_items)} unsafe change(s) detected:")
            for item in unsafe_items:
                print(f"  ✗ {item.table_name}: {item.reason}")
                print(f"    SQL: {item.sql}")

        # STEP 6 — If ALL items are unsafe and none are safe: report + exit(1)
        print("[MAIN] STEP 6 — Check for unsafe-only scenario")
        if not safe_items and unsafe_items:
            print("[MAIN] STEP 6 — Unsafe only, no safe items.")
            report = generate_report(items, report_dir=report_path)
            print("[MAIN] Pipeline halted. Fix unsafe changes manually.")
            sys.exit(1)

        # STEP 7 — Dry run: report + exit(0)
        print("[MAIN] STEP 7 — Check dry run")
        if dry_run:
            print("[MAIN] Dry run mode. No changes will be applied.")
            report = generate_report(items, report_dir=report_path)
            sys.exit(0)

        # STEP 8 — Validate safe items (applied automatically)
        print("[MAIN] STEP 8 — Validate")
        validation = validate_safe_items(safe_items)
        if not validation.valid and not validation.validated_items:
            print("[MAIN] All safe items failed validation.")
            report = generate_report(items, validation, report_dir=report_path)
            sys.exit(1)

<<<<<<< HEAD
        print("[MAIN] STEP 10 — Generate migration file")
        migrations_dir = _resolve_migrations_dir(config)
        _ensure_directory(migrations_dir)
=======
        # STEP 9 — Generate migration file
        print("[MAIN] STEP 9 — Generate migration file")
        migrations_dir = config["settings"]["migrations_dir"] if config else "./prisma/migrations"
>>>>>>> 946b42b (refactor: remove approval gate, connect to GitHub Actions)
        migration_file = generate_migration(validation.validated_items, migrations_dir=migrations_dir)

        # STEP 10 — Execute migration
        print("[MAIN] STEP 10 — Execute migration")
        execution = execute_migration(migration_file, resolved_db_url)
        if not execution.success:
            print(f"[MAIN] Execution failed: {execution.error_message}")
            report = generate_report(items, validation, migration_file, execution, report_dir=report_path)
            sys.exit(1)

        # STEP 11 — Verify migration applied
        print("[MAIN] STEP 11 — Verify")
        verify_migration_applied(migration_file.folder_name, resolved_db_url)

        # STEP 12 — Generate final report
        print("[MAIN] STEP 12 — Generate final report")
        report = generate_report(items, validation, migration_file, execution, report_dir=report_path)

        # STEP 13 — Final exit
        print("[MAIN] STEP 13 — Final exit")
        if unsafe_items:
            print("[MAIN] Completed with unsafe items requiring manual review.")
            sys.exit(1)

        print("[MAIN] ✓ All drift resolved successfully.")
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[MAIN] Unhandled error: {exc}")
        try:
            generate_report(items, report_dir=report_path)
        except Exception as report_exc:
            print(f"[MAIN] Failed to generate recovery report: {report_exc}")
        sys.exit(3)


if __name__ == "__main__":
    main()
