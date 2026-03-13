ALTER TABLE "users" DROP COLUMN "password";
DROP TABLE "sessions";
ALTER TABLE "users" RENAME COLUMN "name" TO "full_name";
ALTER TABLE "users" ALTER COLUMN "age" TYPE VARCHAR(10);
ALTER TABLE "users" ADD COLUMN "verified" BOOLEAN NOT NULL;