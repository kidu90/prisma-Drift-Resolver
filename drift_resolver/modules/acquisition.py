

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class AcquisitionResult:

	raw_sql: str
	has_drift: bool
	error: Optional[str]
	exit_code: int


def is_empty_diff(sql_output: str) -> bool:
	"""Return True when the SQL output has no executable statements."""

	for line in sql_output.splitlines():
		stripped = line.strip()
		if stripped and not stripped.startswith("--"):
			return False
	return True


def get_prisma_drift(
	schema_path: str = "./prisma/schema.prisma",
	db_url: str = "",
) -> AcquisitionResult:
	"""Run `prisma migrate diff --script` and return raw SQL output.

	
	"""

	cli_command = "npx.cmd" if sys.platform.startswith("win") else "npx"
	command = [
		cli_command,
		"prisma",
		"migrate",
		"diff",
		"--from-url",
		db_url,
		"--to-schema-datamodel",
		schema_path,
		"--script",
	]

	print("[ACQUISITION] Running prisma migrate diff...")

	try:
		completed = subprocess.run(
			command,
			capture_output=True,
			text=True,
			timeout=60,
			check=False,
		)
	except FileNotFoundError:
		error_message = "Prisma CLI not found. Make sure npx and prisma are installed."
		print(f"[ACQUISITION] ERROR: {error_message}")
		return AcquisitionResult(raw_sql="", has_drift=False, error=error_message, exit_code=127)
	except subprocess.TimeoutExpired:
		error_message = "Prisma diff timed out after 60 seconds."
		print(f"[ACQUISITION] ERROR: {error_message}")
		return AcquisitionResult(raw_sql="", has_drift=False, error=error_message, exit_code=124)
	except Exception as exc:  # Defensive fallback for unexpected runtime failures.
		error_message = f"Unexpected acquisition error: {exc}"
		print(f"[ACQUISITION] ERROR: {error_message}")
		return AcquisitionResult(raw_sql="", has_drift=False, error=error_message, exit_code=1)

	raw_sql = (completed.stdout or "").strip()
	stderr = (completed.stderr or "").strip()

	if completed.returncode != 0:
		# Prisma reports DB connectivity and CLI/runtime issues in stderr.
		details = stderr if stderr else "Prisma migrate diff failed without stderr output."
		error_message = f"Prisma migrate diff failed (exit code {completed.returncode}): {details}"
		print(f"[ACQUISITION] ERROR: {error_message}")
		return AcquisitionResult(
			raw_sql=raw_sql,
			has_drift=False,
			error=error_message,
			exit_code=completed.returncode,
		)

	has_drift = not is_empty_diff(raw_sql)

	if has_drift:
		statement_count = sum(
			1
			for line in raw_sql.splitlines()
			if line.strip() and not line.strip().startswith("--")
		)
		print(f"[ACQUISITION] Drift detected: {statement_count} statements found.")
	else:
		print("[ACQUISITION] No drift detected. Database is in sync.")

	return AcquisitionResult(
		raw_sql=raw_sql,
		has_drift=has_drift,
		error=None,
		exit_code=completed.returncode,
	)


if __name__ == "__main__":
	"""Allow direct module execution for quick local smoke testing."""

	import os

	from dotenv import load_dotenv

	# Load local environment variables so DATABASE_URL can be provided via .env.
	load_dotenv()
	database_url = os.getenv("DATABASE_URL", "")

	result = get_prisma_drift(schema_path="./prisma/schema.prisma", db_url=database_url)

	# Print all fields explicitly so CI logs remain easy to scan.
	print("\n[ACQUISITION] Result")
	print(f"  raw_sql:\n{result.raw_sql}")
	print(f"  has_drift: {result.has_drift}")
	print(f"  error: {result.error}")
	print(f"  exit_code: {result.exit_code}")
