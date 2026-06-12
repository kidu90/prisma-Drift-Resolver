from __future__ import annotations

import os
import sys
from pathlib import Path

import click

try:
    from drift_resolver.modules.acquisition import get_prisma_drift
    from drift_resolver.modules.approval import ApprovalResult, check_approval
    from drift_resolver.modules.classifier import classify_drift_items
    from drift_resolver.modules.config_loader import load_config
    from drift_resolver.modules.executor import ExecutionResult, execute_migration, verify_migration_applied
    from drift_resolver.modules.generator import MigrationFile, generate_migration
    from drift_resolver.modules.parser import parse_drift_sql
    from drift_resolver.modules.reporter import DriftReport, generate_report, post_result_comment
    from drift_resolver.modules.validator import ValidationResult, validate_safe_items
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from drift_resolver.modules.acquisition import get_prisma_drift
    from drift_resolver.modules.approval import ApprovalResult, check_approval
    from drift_resolver.modules.classifier import classify_drift_items
    from drift_resolver.modules.config_loader import load_config
    from drift_resolver.modules.executor import ExecutionResult, execute_migration, verify_migration_applied
    from drift_resolver.modules.generator import MigrationFile, generate_migration
    from drift_resolver.modules.parser import parse_drift_sql
    from drift_resolver.modules.reporter import DriftReport, generate_report, post_result_comment
    from drift_resolver.modules.validator import ValidationResult, validate_safe_items


def _post_final_comment(report: DriftReport) -> None:
    """Post the final summary comment when PR metadata is available."""

    pr_number = os.environ.get("PR_NUMBER", "")
    if pr_number:
        post_result_comment(report, pr_number)


@click.command()
@click.option("--schema", "schema_path", default="./prisma/schema.prisma", show_default=True, help="Path to schema.prisma")
@click.option("--db-url", "db_url", default=None, envvar="DATABASE_URL", help="Database URL")
@click.option("--report-path", "report_path", default=".", show_default=True, help="Directory for report artifacts")
@click.option("--dry-run", is_flag=True, default=False, help="Detect and classify drift without applying changes")
def main(schema_path: str, db_url: str | None, report_path: str, dry_run: bool) -> None:
    """Run the full drift-resolver pipeline."""

    items: list = []
    approval: ApprovalResult | None = None
    validation: ValidationResult | None = None
    migration_file: MigrationFile | None = None
    execution: ExecutionResult | None = None
    report: DriftReport | None = None
    config: dict | None = None

    try:
        print("[MAIN] STEP 1 — Load config")
        config = load_config()
        print("[MAIN] Config loaded.")

        resolved_db_url = db_url or os.environ.get("DATABASE_URL", "")
        if not resolved_db_url:
            raise ValueError("Database URL is required. Set DATABASE_URL or pass --db-url.")

        print("[MAIN] STEP 2 — Acquisition")
        acquisition_result = get_prisma_drift(schema_path=schema_path, db_url=resolved_db_url)
        if acquisition_result.error:
            print(f"[MAIN] Acquisition failed: {acquisition_result.error}")
            report = generate_report([], report_dir=report_path)
            _post_final_comment(report)
            sys.exit(3)

        if not acquisition_result.has_drift:
            report = generate_report([], report_dir=report_path)
            print("[MAIN] No drift detected. Database is in sync.")
            _post_final_comment(report)
            sys.exit(0)

        print("[MAIN] STEP 3 — Parse")
        items = parse_drift_sql(acquisition_result.raw_sql)

        print("[MAIN] STEP 4 — Classify")
        items = classify_drift_items(items)
        safe_items = [item for item in items if item.classification.value == "SAFE"]
        unsafe_items = [item for item in items if item.classification.value == "UNSAFE"]

        print("[MAIN] STEP 5 — Log unsafe items clearly")
        if unsafe_items:
            print(f"[MAIN] {len(unsafe_items)} unsafe change(s) detected:")
            for item in unsafe_items:
                print(f"  ✗ {item.table_name}: {item.reason}")
                print(f"    SQL: {item.sql}")

        if not safe_items and unsafe_items:
            report = generate_report(items, report_dir=report_path)
            _post_final_comment(report)
            sys.exit(1)

        if dry_run:
            print("[MAIN] Dry run mode. No changes will be applied.")
            report = generate_report(items, report_dir=report_path)
            sys.exit(0)

        print("[MAIN] STEP 8 — Approval gate")
        try:
            approval = check_approval(safe_items)
        except SystemExit as exc:
            bypass_local_approval = False
            if exc.code == 2:
                if not (os.environ.get("PR_NUMBER") or os.environ.get("GITHUB_PR_NUMBER")):
                    approval = ApprovalResult(
                        approved=True,
                        mode="local",
                        message="No PR context; continuing in local execution mode.",
                    )
                    print("[MAIN] No PR context detected. Bypassing approval gate for local execution.")
                    bypass_local_approval = True
                else:
                    approval = ApprovalResult(approved=False, mode="pending", message="Approval pending")
                    report = generate_report(items, approval_result=approval, report_dir=report_path)
                    _post_final_comment(report)
                    sys.exit(2)
            if not bypass_local_approval:
                raise

        print("[MAIN] STEP 9 — Validate")
        validation = validate_safe_items(safe_items)
        if not validation.valid and not validation.validated_items:
            print("[MAIN] All safe items failed validation.")
            report = generate_report(items, approval, validation, report_dir=report_path)
            _post_final_comment(report)
            sys.exit(1)

        print("[MAIN] STEP 10 — Generate migration file")
        migrations_dir = config["settings"]["migrations_dir"] if config else "./prisma/migrations"
        migration_file = generate_migration(validation.validated_items, migrations_dir=migrations_dir)

        print("[MAIN] STEP 11 — Execute migration")
        resolved_db_url = db_url or os.environ.get("DATABASE_URL", "")
        execution = execute_migration(migration_file, resolved_db_url)
        if not execution.success:
            print(f"[MAIN] Execution failed: {execution.error_message}")
            report = generate_report(items, approval, validation, migration_file, execution, report_dir=report_path)
            _post_final_comment(report)
            sys.exit(1)

        print("[MAIN] STEP 12 — Verify")
        verify_migration_applied(migration_file.folder_name, resolved_db_url)

        print("[MAIN] STEP 13 — Generate final report")
        report = generate_report(items, approval, validation, migration_file, execution, report_dir=report_path)

        print("[MAIN] STEP 14 — Post result comment to PR")
        _post_final_comment(report)

        print("[MAIN] STEP 15 — Final exit")
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
            report = generate_report(items, report_dir=report_path)
            _post_final_comment(report)
        except Exception as report_exc:
            print(f"[MAIN] Failed to generate recovery report: {report_exc}")
        sys.exit(3)


if __name__ == "__main__":
    main()