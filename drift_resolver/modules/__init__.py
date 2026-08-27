# Public module exports for drift-resolver processing modules.

from .acquisition import AcquisitionResult, get_prisma_drift
from .classifier import classify_drift_items
from .executor import ExecutionResult, execute_migration, verify_migration_applied
from .generator import MigrationFile, generate_migration, get_migration_preview
from .notifier import NotificationResult, check_email_config, send_failure_notification
from .parser import parse_drift_sql
from .reporter import DriftReport, generate_report
from .validator import ValidationResult, validate_safe_items

__all__ = [
	"AcquisitionResult",
	"get_prisma_drift",
	"ValidationResult",
	"validate_safe_items",
	"MigrationFile",
	"generate_migration",
	"get_migration_preview",
	"parse_drift_sql",
	"classify_drift_items",
	"ExecutionResult",
	"execute_migration",
	"verify_migration_applied",
	"DriftReport",
	"generate_report",
	"NotificationResult",
	"send_failure_notification",
	"check_email_config",
]
