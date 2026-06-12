# Public module exports for drift-resolver processing modules.

from .acquisition import AcquisitionResult, get_prisma_drift
from .approval import ApprovalResult, check_approval
from .classifier import classify_drift_items
from .executor import ExecutionResult, execute_migration, verify_migration_applied
from .generator import MigrationFile, generate_migration, get_migration_preview
from .parser import parse_drift_sql
from .reporter import DriftReport, generate_report, post_result_comment
from .validator import ValidationResult, validate_safe_items

__all__ = [
	"AcquisitionResult",
	"get_prisma_drift",
	"ApprovalResult",
	"check_approval",
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
	"post_result_comment",
]
