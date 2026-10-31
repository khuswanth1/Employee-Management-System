#!/bin/sh
# Runs once on first start of the postgres container.
# - worksphere_platform: owns ONLY the central registry database
# - worksphere_provisioner: can create tenant databases/roles but is NOT a superuser
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE worksphere_platform LOGIN PASSWORD '${PLATFORM_DB_PASSWORD}';
CREATE DATABASE worksphere_platform OWNER worksphere_platform;
REVOKE ALL ON DATABASE worksphere_platform FROM PUBLIC;
CREATE ROLE worksphere_provisioner LOGIN CREATEDB CREATEROLE PASSWORD '${PROVISIONER_DB_PASSWORD}';
SQL
