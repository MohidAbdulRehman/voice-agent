-- Runs once, when the docker compose volume is first created.
-- The test suite owns this database (TEST_DATABASE_URL) and resets it on every run.
CREATE DATABASE intake_test;
