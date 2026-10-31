# Field and UI gap analysis

Audit of the existing WorkSphere app against the "Advanced Field and UI Enhancement" brief. The app is FastAPI + React (JSX) + SQLAlchemy/Alembic, so the work extends that stack instead of replacing it. Status: **Done** (implemented and tested), **Gap** (not done), **N/A** (the data model does not exist yet).

## Employee profile (this round)

| Brief field | Status | Where |
|---|---|---|
| Employee ID, name, work email, phone, designation, department, branch, work location, reporting manager, joining date | Done (before) | `users` |
| Middle name, display name | Done | `employee_profiles` |
| Employment type, employment category, job level | Done | `employee_profiles` |
| Probation end, confirmation date, notice period, last working date | Done, ordered against joining date | `employee_profiles` |
| Skills, certifications, tags | Done, de-duplicated chips | `employee_profiles` (JSON) |
| Personal email, date of birth, gender, address | Done, restricted to the person + HR/founder | `employee_profiles` |
| Emergency contact name, relationship, phone, address | Done, restricted | `employee_profiles` |
| Assigned team, team leader | Done (before), shown on the Team & projects tab | teams |
| Documents: type, upload date, expiry, verification status | Done | `employee_documents` (+4 columns) |
| Profile tabs | Done: Overview, Employment, Personal (only if authorised), Documents, Team & projects | `ProfileTabs.jsx` |
| Tabs Attendance, Leave, Performance, Payroll, Activity History | Gap (attendance/leave exist as pages; no performance or payroll data model) | |

## Not started (highest value first)

1. Department budget (restricted) needs a finance model first. Branch timezone and working days must still be wired into attendance and leave.
2. Team fields: code, assistant leader, capacity, skills, start/end dates.
3. Tasks: backlog and cancelled statuses, nested subtasks, comments, status history. Projects: budget (restricted, needs a finance model), milestone-based progress rule, risks and issues log.
4. Company settings: legal name, registration number, industry, size, currency, financial-year start.
5. Leave type configuration (accrual, carry-forward, notice period) and holiday categories/applicability.
6. Payroll, performance and recruitment: no data model exists; each needs a design before any UI.
7. Reusable searchable select, date-range picker, currency input and column-visibility menu.

## Access rules for the new data

- Employment and identity fields: anyone who can view the employee reads them.
- Restricted fields are not sent at all to managers, peers or board members. They go only to the person and to HR/founders in scope.
- Employment fields are written only by those who administer the account; the person edits their own identity and restricted fields; a manager needs `employees.manage`.
- The audit log records field names, never values.
- People cannot verify their own documents.

## Shared UI additions

`FormSection`, `Skeleton`/`TableSkeleton`, `TagInput`; `Table` gains sortable headers (`aria-sort`, server-side sort) and keyboard-operable rows; `Tabs` gains arrow-key navigation. The employee list sorts on the server (`sort`, `order`; whitelisted columns).
