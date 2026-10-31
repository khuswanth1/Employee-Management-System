# WorkSphere — Multi-Tenant Backend API

A production-ready, multi-tenant Employee & Project Management backend API built with **FastAPI**, **SQLAlchemy 2.0**, and **PostgreSQL / SQLite**.

---

## 🌟 Key Architecture & Features

* **Strict Multi-Tenancy (Database-per-Tenant)**:
  * Each company/tenant receives its own isolated database.
  * Tenant identification is resolved **strictly from cryptographic JWT claims** (no spoofable HTTP headers or query parameters).
  * Tenant database credentials are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256).
* **Dual Database Modes**:
  * **SQLite Mode**: Zero-configuration, zero-dependency local development and hermetic automated test suites.
  * **PostgreSQL Mode**: Production-grade multi-tenancy with dynamic role and database provisioning (`CREATE ROLE` & `CREATE DATABASE`).
* **Role-Based Access Control (RBAC)**:
  * `platform_admin`: Superadmin managing tenants, platform health, and backups.
  * `founder`: Tenant creator with company-wide administrative authority.
  * `hr`: Team management, departments, and leave approvals.
  * `manager`: Project milestones, task delegations, and direct-report attendance.
  * `employee`: Standup updates, tasks, leave submissions, and attendance tracking.
* **Real-Time Meetings & WebRTC**:
  * Built-in WebSocket room signaling (`/api/v1/meetings/ws/{room_id}`).
  * Automated STUN / TURN ICE credential distribution (`/api/v1/meetings/ice-config`).
* **Background Worker & Webhooks**:
  * In-process async background delivery engine with retry backoff for tenant webhooks.
* **Transactional Email**:
  * Standard SMTP with `STARTTLS` support (tested with Gmail and Brevo).

---

## 📁 Project Structure

```text
backend/
├── app/
│   ├── core/               # App configuration, security, Fernet encryption, errors, logging
│   ├── db/                 # Platform database models and platform session factories
│   ├── modules/            # Domain features (FastAPI APIRouters & Services)
│   │   ├── admin/          # Tenant administration & audit policies
│   │   ├── attendance/     # Clock-in / clock-out & attendance records
│   │   ├── auth/           # Platform & tenant authentication, JWT tokens
│   │   ├── dashboard/      # Tenant metrics & aggregate statistics
│   │   ├── employees/      # Employee directory, profiles & departments
│   │   ├── leave/          # Leave requests & balance approvals
│   │   ├── meetings/       # WebRTC meetings, ICE configuration & WebSockets
│   │   ├── notifications/  # In-app alerts & SMTP email notifications
│   │   ├── platform/       # Company provisioning & platform management
│   │   ├── projects/       # Projects, milestones, tasks & dependencies
│   │   ├── updates/        # Daily asynchronous team standup updates
│   │   └── webhooks/       # Webhook subscriptions & delivery worker
│   └── tenancy/            # Dynamic tenant connection pools & migration managers
├── alembic_platform/       # Database migrations for the shared platform database
├── alembic_tenant/         # Database migrations applied across every tenant database
├── data/                   # Default local SQLite databases, uploads & backups
├── scripts/
│   ├── new_migration.py    # Autogenerate Alembic revisions against isolated scratch DB
│   └── seed_demo.py        # Populates a full demo company with projects and employees
├── tests/                  # Complete Pytest test suite with tenant isolation tests
├── Dockerfile              # Production multi-stage Docker build
├── requirements.txt        # Production dependencies
└── .env                    # Active environment configuration (git-ignored)
```

---

## 🚀 Quickstart Guide

### 1. Prerequisites
* **Python 3.12+** installed on your system.
* *(Optional)* **PostgreSQL** running locally if using PostgreSQL tenant mode (port `5432`).

### 2. Environment Setup
Create a virtual environment and install dependencies:

```powershell
# In Windows PowerShell:
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configure Environment Variables
If setting up for the first time, copy `.env.example` to `.env`:
```powershell
# Only if you don't already have a .env file:
cp .env.example .env
```

Ensure the following primary variables are defined in `.env`:
```env
ENVIRONMENT=development
SECRET_KEY=<your-secret-key-at-least-32-chars>
ENCRYPTION_KEY=<fernet-32-byte-base64-key>

# Platform & Tenant Database Settings
PLATFORM_DATABASE_URL=sqlite:///./data/platform.db
TENANT_DB_MODE=postgres
POSTGRES_ADMIN_URL=postgresql+psycopg://postgres:<your-password>@localhost:5432/postgres
TENANT_DB_HOST=localhost
TENANT_DB_PORT=5432

# Initial Superadmin
BOOTSTRAP_ADMIN_EMAIL=admin@worksphere.dev
BOOTSTRAP_ADMIN_PASSWORD=Dev-Admin-Pass-1

# Optional Email (Gmail SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_16_char_app_password
SMTP_FROM=your_email@gmail.com

# WebRTC STUN Server
STUN_URLS=stun:stun.l.google.com:19302,stun:stun.cloudflare.com:3478
```

### 4. Start the Application
Run the Uvicorn development server with live reload:

```powershell
python -m uvicorn app.main:app --reload
```

The server will automatically:
1. Run platform migrations (`alembic_platform`).
2. Bootstrap the default Platform Admin if no platform user exists.
3. Start the background webhook worker task.

---

## 📖 API Documentation & Endpoints

Once the backend is running, access the interactive OpenAPI documentation:

| Resource | URL | Description |
| :--- | :--- | :--- |
| **Swagger UI** | [http://localhost:8000/api/docs](http://localhost:8000/api/docs) | Interactive API exploration & testing |
| **ReDoc** | [http://localhost:8000/api/redoc](http://localhost:8000/api/redoc) | Clean, readable reference documentation |
| **OpenAPI JSON** | [http://localhost:8000/api/openapi.json](http://localhost:8000/api/openapi.json) | Raw OpenAPI v3 specification |
| **Health Check** | [http://localhost:8000/api/health](http://localhost:8000/api/health) | Returns `{"status": "ok"}` |

> **Note**: All functional business endpoints are routed under the `/api/v1` prefix.

---

## 🌱 Seeding Demo Data

To populate a complete demo company (`Acme Corporation`) with an initial department structure, projects, tasks, milestones, and sample employees:

```powershell
python scripts/seed_demo.py --api http://localhost:8000 --admin-email admin@worksphere.dev --admin-password Dev-Admin-Pass-1 --slug acme
```

* All generated demo accounts share the password: `Demo-Passw0rd!`
* Accounts created: `founder@acme.com`, `hr@acme.com`, `mgr@acme.com`, `e1@acme.com`, `e2@acme.com`.

---

## 🔄 Database Migrations

This project maintains two separate Alembic migration trees:
1. **Platform schema** (`alembic_platform/`): Companies, platform users, system configurations.
2. **Tenant schema** (`alembic_tenant/`): Employees, projects, attendance, leave, tasks.

### Running Migrations:
* **Automatic**: The backend automatically runs platform migrations on startup (`bootstrap_platform()`) and tenant migrations whenever a new company is provisioned.
* **Manual CLI (Platform)**:
  ```powershell
  alembic upgrade head
  ```
* **Check current revision**:
  ```powershell
  alembic current
  ```

### Creating New Migrations:
To autogenerate a new migration from model changes without affecting your production databases:

```powershell
# For tenant schema changes:
python scripts/new_migration.py tenant "add column description to tasks"

# For platform schema changes:
python scripts/new_migration.py platform "add subscription tier to company"
```

---

## 🧪 Running Automated Tests

Run the complete test suite using `pytest`:

```powershell
pytest
```

* Tests run against isolated, temporary SQLite databases by default.
* To test tenant provisioning with PostgreSQL, set `TEST_POSTGRES_ADMIN_URL`:
  ```powershell
  $env:TEST_POSTGRES_ADMIN_URL="postgresql+psycopg://postgres:password@localhost:5432/postgres"
  pytest tests/test_tenant_isolation.py
  ```

---

## 🐳 Docker Deployment & Scaling

### Running with Docker

Build and run the containerized backend:

```powershell
# Build image
docker build -t worksphere-backend .

# Run container
docker run -d -p 8000:8000 --env-file .env --name worksphere-api worksphere-backend
```

### Scaling Architecture
* **Single Worker Deployment**: The default configuration runs a single worker process because WebSocket room fan-out, memory rate-limiting, and webhook processing are managed in-process.
* **Horizontal Scaling**: To scale across multiple instances or containers, connect an external Pub/Sub layer (such as Redis) for WebSocket fan-out and run the webhook background task as a dedicated worker.
