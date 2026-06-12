from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import os
import re
import subprocess
import sys

try:
	from drift_resolver.modules.generator import MigrationFile
except ModuleNotFoundError:
	project_root = Path(__file__).resolve().parents[2]
	if str(project_root) not in sys.path:
		sys.path.insert(0, str(project_root))
	from drift_resolver.modules.generator import MigrationFile


@dataclass
class ExecutionResult:
	"""Represent the outcome of applying the generated migration."""

	success: bool
	error_message: Optional[str]
	applied_items: Optional[int] = None
	migration_name: Optional[str] = None
	executed_at: Optional[str] = None
	stdout: str = ""
	stderr: str = ""
	return_code: Optional[int] = None


def execute_migration(migration_file: MigrationFile, db_url: str) -> ExecutionResult:
	"""Apply the generated Prisma migration to the target database."""

	print(f"[EXECUTOR] Applying migration: {migration_file.folder_name}")
	with open(migration_file.sql_path, "r", encoding="utf-8") as file_handle:
		content = file_handle.read()
	print("[EXECUTOR] Migration SQL to be applied:")
	print(content)
	print("[EXECUTOR] Verifying table names look correct...")
	unquoted = re.findall(r'(?<!")\busers\b(?!")', content, re.IGNORECASE)
	if unquoted:
		print(f"[EXECUTOR] WARNING: Found potentially unquoted table reference: {unquoted}")
		print('[EXECUTOR] Expected quoted form: "User"')
	command = [_npx_command(), "prisma", "migrate", "deploy"]
	env = os.environ.copy()
	env["DATABASE_URL"] = db_url

	try:
		completed = subprocess.run(
			command,
			capture_output=True,
			text=True,
			check=False,
			timeout=120,
			env=env,
		)
	except FileNotFoundError:
		error_message = "Prisma CLI not found. Make sure npx and prisma are installed."
		print(f"[EXECUTOR] ERROR: {error_message}")
		return ExecutionResult(
			success=False,
			error_message=error_message,
			applied_items=0,
			migration_name=migration_file.folder_name,
			executed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
			return_code=127,
		)
	except subprocess.TimeoutExpired:
		error_message = "Prisma migrate deploy timed out after 120 seconds."
		print(f"[EXECUTOR] ERROR: {error_message}")
		return ExecutionResult(
			success=False,
			error_message=error_message,
			applied_items=0,
			migration_name=migration_file.folder_name,
			executed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
			return_code=124,
		)
	except Exception as exc:
		error_message = f"Unexpected execution error: {exc}"
		print(f"[EXECUTOR] ERROR: {error_message}")
		return ExecutionResult(
			success=False,
			error_message=error_message,
			applied_items=0,
			migration_name=migration_file.folder_name,
			executed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
			return_code=1,
		)

	stdout = (completed.stdout or "").strip()
	stderr = (completed.stderr or "").strip()
	if stdout:
		print(stdout)
	if stderr:
		print(stderr)

	executed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
	if completed.returncode != 0:
		error_details = stderr or "Prisma migrate deploy failed without stderr output."
		error_message = f"Prisma migrate deploy failed (exit code {completed.returncode}): {error_details}"
		print(f"[EXECUTOR] ERROR: {error_message}")
		return ExecutionResult(
			success=False,
			error_message=error_message,
			applied_items=0,
			migration_name=migration_file.folder_name,
			executed_at=executed_at,
			stdout=stdout,
			stderr=stderr,
			return_code=completed.returncode,
		)

	print(f"[EXECUTOR] Migration applied successfully: {migration_file.folder_name}")
	return ExecutionResult(
		success=True,
		error_message=None,
		applied_items=migration_file.item_count,
		migration_name=migration_file.folder_name,
		executed_at=executed_at,
		stdout=stdout,
		stderr=stderr,
		return_code=completed.returncode,
	)


def verify_migration_applied(migration_name: str, db_url: str, schema_path: str = "./prisma/schema.prisma") -> None:
	"""Confirm that Prisma reports the database as up to date after deployment."""

	print(f"[EXECUTOR] Verifying migration: {migration_name}")
	command = [_npx_command(), "prisma", "migrate", "status", "--schema", schema_path]
	env = os.environ.copy()
	env["DATABASE_URL"] = db_url
	completed = subprocess.run(
		command,
		capture_output=True,
		text=True,
		check=False,
		timeout=120,
		env=env,
	)
	stdout = completed.stdout or ""
	stderr = completed.stderr or ""
	if completed.returncode != 0:
		raise RuntimeError(
			f"Migration verification failed (exit code {completed.returncode}): {stderr.strip() or stdout.strip()}"
		)

	status_output = f"{stdout}\n{stderr}".lower()
	if "up to date" not in status_output and "not in sync" in status_output:
		raise RuntimeError(f"Migration verification did not confirm success for {migration_name}.")

	print(f"[EXECUTOR] Verification passed for {migration_name}")


def _npx_command() -> str:
	"""Return the platform-appropriate npx executable name."""

	return "npx.cmd" if sys.platform.startswith("win") else "npx"


if __name__ == "__main__":
	print("[EXECUTOR] This module is intended to be called from drift_resolver.main.")
