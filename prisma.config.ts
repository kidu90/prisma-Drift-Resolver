import { defineConfig, env } from "prisma/config";

const migrationsPath =
  (globalThis as any).process?.env?.DRIFT_MIGRATIONS_DIR ?? "prisma/migrations";

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: {
    path: migrationsPath,
  },
  engine: "classic",
  datasource: {
    url: env("DATABASE_URL"),
  },
});
