ALTER TABLE "users" ADD COLUMN "bio" TEXT;
ALTER TABLE "users" ADD COLUMN "age" INTEGER DEFAULT 0;
ALTER TABLE "users" ALTER COLUMN "status" SET DEFAULT 'active';
CREATE INDEX "idx_users_email" ON "users"("email");
CREATE TABLE "audit_logs" ("id" SERIAL PRIMARY KEY, "action" TEXT, "created_at" TIMESTAMP);