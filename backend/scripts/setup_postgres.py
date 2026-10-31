"""Helper script to create PostgreSQL main database, sub database (company1), and configure .env.

Usage:
    python scripts/setup_postgres.py
    python scripts/setup_postgres.py --sub-db company1 --company-name "Company 1"
"""
import argparse
import sys
from pathlib import Path
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
venv_site = BACKEND_DIR / ".venv" / "Lib" / "site-packages"
if venv_site.exists():
    sys.path.insert(0, str(venv_site))

PG_USER = "postgres"
PG_PASS = "2205"
PG_HOST = "localhost"
PG_PORT = 5432
DB_NAME = "employee_management"
DEFAULT_SUB_DB = "company1"

ADMIN_URL = f"postgresql+psycopg://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/postgres"
TARGET_URL = f"postgresql+psycopg://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{DB_NAME}"


def main():
    parser = argparse.ArgumentParser(description="Set up PostgreSQL platform database and tenant sub-database.")
    parser.ArgumentParser(description="Setup PostgreSQL") if False else None
    parser.add_argument("--sub-db", default=DEFAULT_SUB_DB, help="Sub-database name/slug (default: company1)")
    parser.add_argument("--company-name", default="Company 1", help="Company display name (default: Company 1)")
    parser.add_argument("--founder-email", default="founder@company1.com", help="Founder email")
    parser.add_argument("--founder-password", default="Admin@2205", help="Founder password")
    parser.add_argument("--no-env", action="store_true", help="Do not overwrite .env file")
    args = parser.parse_args()

    sub_db_name = args.sub_db.lower().strip()
    target_sub_url = f"postgresql+psycopg://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{sub_db_name}"

    print(f"Connecting to PostgreSQL at {PG_HOST}:{PG_PORT}...")
    try:
        admin_eng = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin_eng.connect() as conn:
            # 1. Main platform database
            res = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"),
                {"d": DB_NAME},
            ).scalar()
            if not res:
                print(f"Creating platform database '{DB_NAME}'...")
                conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
                print(f"Platform database '{DB_NAME}' created successfully.")
            else:
                print(f"Platform database '{DB_NAME}' already exists.")

            # 2. Sub database (tenant database, company1 format)
            sub_res = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"),
                {"d": sub_db_name},
            ).scalar()
            if not sub_res:
                print(f"Creating sub database '{sub_db_name}'...")
                conn.execute(text(f'CREATE DATABASE "{sub_db_name}"'))
                print(f"Sub database '{sub_db_name}' created successfully.")
            else:
                print(f"Sub database '{sub_db_name}' already exists.")

        admin_eng.dispose()
    except Exception as e:
        print(f"\n[ERROR] Failed to connect to PostgreSQL: {e}")
        print("\nPlease make sure PostgreSQL service is running:")
        print("  1. Press Win + R, type 'services.msc', and press Enter.")
        print("  2. Locate 'postgresql-x64-18' (or your installed PostgreSQL service).")
        print("  3. Right-click and choose 'Start'.")
        print("  4. Or in an Administrator PowerShell run: Start-Service postgresql-x64-18")
        sys.exit(1)

    # Update .env if requested
    if not args.no_env:
        env_file = BACKEND_DIR / ".env"
        if env_file.exists():
            content = env_file.read_text(encoding="utf-8")
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("PLATFORM_DATABASE_URL="):
                    new_lines.append(f"PLATFORM_DATABASE_URL={TARGET_URL}")
                elif line.startswith("TENANT_DB_MODE="):
                    new_lines.append("TENANT_DB_MODE=postgres")
                elif line.startswith("POSTGRES_ADMIN_URL="):
                    new_lines.append(f"POSTGRES_ADMIN_URL={ADMIN_URL}")
                elif line.startswith("TENANT_DB_HOST="):
                    new_lines.append(f"TENANT_DB_HOST={PG_HOST}")
                elif line.startswith("TENANT_DB_PORT="):
                    new_lines.append(f"TENANT_DB_PORT={PG_PORT}")
                else:
                    new_lines.append(line)
            env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            print("Updated .env with PostgreSQL settings:")
            print(f"  PLATFORM_DATABASE_URL={TARGET_URL}")
            print(f"  TENANT_DB_MODE=postgres")
            print(f"  POSTGRES_ADMIN_URL={ADMIN_URL}")

    # Run platform migrations
    print(f"\nRunning platform migrations on '{DB_NAME}'...")
    from app.tenancy.manager import migrate_platform, migrate_tenant
    platform_eng = create_engine(TARGET_URL)
    migrate_platform(platform_eng)
    print("Platform migrations applied successfully!")

    # Run tenant migrations on sub database
    print(f"\nRunning tenant migrations on sub database '{sub_db_name}'...")
    sub_eng = create_engine(target_sub_url)
    migrate_tenant(sub_eng)
    print(f"Tenant migrations applied on '{sub_db_name}' successfully!")

    # Seed platform admin and register sub-database company
    from app.core.security import encrypt, hash_password
    from app.db.platform_models import Company, PlatformUser
    from app.tenancy.seed import seed_tenant

    with Session(platform_eng) as pdb:
        # Bootstrap admin
        admin = pdb.scalar(select(PlatformUser).where(PlatformUser.email == "admin@worksphere.dev"))
        if not admin:
            admin = PlatformUser(
                email="admin@worksphere.dev",
                full_name="Platform Administrator",
                password_hash=hash_password("Admin@123"),
                is_active=True,
            )
            pdb.add(admin)
            print("Created platform admin 'admin@worksphere.dev'")

        # Register company in platform DB
        company = pdb.scalar(select(Company).where(Company.slug == sub_db_name))
        if not company:
            company = Company(
                slug=sub_db_name,
                name=args.company_name,
                status="active",
                db_name=sub_db_name,
                db_url_encrypted=encrypt(target_sub_url),
                max_users=500,
            )
            pdb.add(company)
            print(f"Registered company '{sub_db_name}' in platform database")
        pdb.commit()

    # Seed tenant founder in sub database
    with Session(sub_eng) as tdb:
        from app.db.tenant_models import User
        founder = tdb.scalar(select(User).where(User.email == args.founder_email.lower()))
        if not founder:
            seed_tenant(
                tdb,
                founder_email=args.founder_email,
                founder_name=args.company_name + " Founder",
                founder_password=args.founder_password,
            )
            tdb.commit()
            print(f"Seeded founder '{args.founder_email}' in sub database '{sub_db_name}'")

    platform_eng.dispose()
    sub_eng.dispose()

    print("\n" + "=" * 60)
    print("Setup complete!")
    print(f"  Platform DB: {DB_NAME}")
    print(f"  Sub DB:      {sub_db_name} (Format: company1)")
    print(f"  Company:     {args.company_name} (slug: {sub_db_name})")
    print(f"  Founder:     {args.founder_email} / {args.founder_password}")
    print(f"  Superadmin:  admin@worksphere.dev / Admin@123")
    print("=" * 60)
    print("\nYou can now run:")
    print("  python -m uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
