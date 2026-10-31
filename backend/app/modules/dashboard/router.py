from datetime import date, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import case, func, select

from app.common import to_csv
from app.db.base import utcnow
from app.db.tenant_models import (
    Attendance, DailyUpdate, Department, Holiday, LeaveRequest, LeaveType, Notification, Project, Task, User,
)
from app.access import require_permission, user_scope
from app.deps import Ctx, get_ctx, require_roles
from app.modules.attendance.router import metrics, scoped_attendance, _std
from app.modules.projects.router import ser_project

router = APIRouter(tags=["dashboard"])
OPEN = ("todo", "in_progress", "review", "changes_requested")


def _count(ctx: Ctx, stmt) -> int:
    return ctx.db.scalar(stmt) or 0


def _task_status_counts(ctx: Ctx, where) -> dict:
    rows = ctx.db.execute(select(Task.status, func.count(Task.id)).where(where).group_by(Task.status)).all()
    out = {"todo": 0, "in_progress": 0, "review": 0, "changes_requested": 0, "done": 0}
    out.update(dict(rows))
    return out


def _workload(ctx: Ctx, user_filter=None) -> list[dict]:
    today = utcnow().date()
    stmt = (
        select(User.id, User.full_name, func.count(Task.id),
               func.sum(case((Task.due_date < today, 1), else_=0)))
        .join(Task, Task.assignee_id == User.id)
        .where(Task.status != "done", User.is_active.is_(True))
        .group_by(User.id, User.full_name)
        .order_by(func.count(Task.id).desc())
    )
    if user_filter is not None:
        stmt = stmt.where(user_filter)
    return [{"user_id": r[0], "user_name": r[1], "open_tasks": r[2], "overdue_tasks": int(r[3] or 0)} for r in ctx.db.execute(stmt)]


def _attendance_today(ctx: Ctx, user_ids: list[int] | None = None) -> dict:
    today = utcnow().date()
    base_users = select(User.id).where(User.is_active.is_(True))
    if user_ids is not None:
        base_users = base_users.where(User.id.in_(user_ids))
    total = _count(ctx, select(func.count()).select_from(base_users.subquery()))
    present = _count(ctx, select(func.count(Attendance.id)).where(Attendance.work_date == today, Attendance.user_id.in_(base_users)))
    on_leave = _count(ctx, select(func.count(LeaveRequest.id)).where(
        LeaveRequest.status == "approved", LeaveRequest.start_date <= today, LeaveRequest.end_date >= today, LeaveRequest.user_id.in_(base_users)))
    return {"total": total, "present": present, "on_leave": on_leave, "absent": max(0, total - present - on_leave)}


@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(get_ctx)):
    today = utcnow().date()
    me = ctx.user.id
    data: dict = {"role": ctx.role}
    data["unread_notifications"] = _count(ctx, select(func.count(Notification.id)).where(Notification.user_id == me, Notification.is_read.is_(False)))

    # personal widgets are shown for every role
    mine = Task.assignee_id == me
    data["my_tasks"] = _task_status_counts(ctx, mine)
    data["my_overdue_tasks"] = _count(ctx, select(func.count(Task.id)).where(mine, Task.status != "done", Task.due_date < today))
    upcoming = ctx.db.scalars(select(Task).where(mine, Task.status != "done").order_by(Task.due_date.is_(None), Task.due_date).limit(5))
    data["my_upcoming_tasks"] = [{"id": t.id, "title": t.title, "due_date": t.due_date, "priority": t.priority, "status": t.status} for t in upcoming]
    data["submitted_update_today"] = bool(ctx.db.scalar(select(DailyUpdate.id).where(DailyUpdate.user_id == me, DailyUpdate.work_date == today)))
    data["pending_leave_requests"] = _count(ctx, select(func.count(LeaveRequest.id)).where(LeaveRequest.user_id == me, LeaveRequest.status == "pending"))

    if ctx.role == "manager":
        owned = Project.owner_id == me
        projects = ctx.db.scalars(select(Project).where(owned).order_by(Project.id.desc()).limit(8)).all()
        pids = select(Project.id).where(owned)
        data["projects"] = [ser_project(ctx, p) for p in projects]
        data["team_task_status"] = _task_status_counts(ctx, Task.project_id.in_(pids))
        data["overdue_tasks"] = _count(ctx, select(func.count(Task.id)).where(Task.project_id.in_(pids), Task.status != "done", Task.due_date < today))
        data["awaiting_review"] = _count(ctx, select(func.count(Task.id)).where(Task.project_id.in_(pids), Task.status == "review"))
        reports = [r for r in ctx.db.scalars(select(User.id).where(User.manager_id == me, User.is_active.is_(True)))]
        data["pending_leave_approvals"] = _count(ctx, select(func.count(LeaveRequest.id)).where(LeaveRequest.status == "pending", LeaveRequest.user_id.in_(reports)))
        data["updates_to_review"] = _count(ctx, select(func.count(DailyUpdate.id)).where(DailyUpdate.review_status == "pending", DailyUpdate.user_id.in_(reports)))
        data["workload"] = _workload(ctx, Task.project_id.in_(pids))
        data["team_attendance"] = _attendance_today(ctx, reports)

    if ctx.role in ("hr", "founder"):
        scope = user_scope(ctx)  # HR assigned to a branch only sees that branch
        scoped_ids = list(ctx.db.scalars(select(User.id).where(scope, User.is_active.is_(True))))
        data["headcount"] = _count(ctx, select(func.count(User.id)).where(User.is_active.is_(True), scope))
        data["onboarding"] = _count(ctx, select(func.count(User.id)).where(User.status == "onboarding", User.is_active.is_(True), scope))
        data["by_department"] = [
            {"department": name or "Unassigned", "count": n}
            for name, n in ctx.db.execute(
                select(Department.name, func.count(User.id)).select_from(User).outerjoin(Department, Department.id == User.department_id)
                .where(User.is_active.is_(True), scope).group_by(Department.name))
        ]
        data["attendance_today"] = _attendance_today(ctx, scoped_ids)
        data["pending_leave_approvals"] = _count(ctx, select(func.count(LeaveRequest.id)).where(LeaveRequest.status == "pending", LeaveRequest.user_id.in_(scoped_ids)))
        data["upcoming_holidays"] = [{"name": h.name, "date": h.date} for h in ctx.db.scalars(select(Holiday).where(Holiday.date >= today).order_by(Holiday.date).limit(5))]

    if ctx.role == "founder":
        data["project_status"] = dict(ctx.db.execute(select(Project.status, func.count(Project.id)).group_by(Project.status)).all())
        data["company_task_status"] = _task_status_counts(ctx, Task.id.is_not(None))
        data["overdue_tasks"] = _count(ctx, select(func.count(Task.id)).where(Task.status != "done", Task.due_date < today))
        data["projects"] = [ser_project(ctx, p) for p in ctx.db.scalars(select(Project).order_by(Project.id.desc()).limit(8))]
        data["workload"] = _workload(ctx)[:10]
        week = today - timedelta(days=6)
        data["updates_this_week"] = _count(ctx, select(func.count(DailyUpdate.id)).where(DailyUpdate.work_date >= week))
        data["blockers_open"] = _count(ctx, select(func.count(DailyUpdate.id)).where(DailyUpdate.work_date >= week, DailyUpdate.blockers.is_not(None), DailyUpdate.blockers != ""))
    return data


def _csv_response(name: str, headers: list[str], rows: list[list]) -> Response:
    return Response(to_csv(headers, rows), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/reports/attendance.csv")
def report_attendance(start: date | None = None, end: date | None = None, ctx: Ctx = Depends(require_permission("reports.view", "hr", "founder", "manager"))):
    end = end or utcnow().date()
    start = start or end - timedelta(days=30)
    from app.modules.attendance import service as att_svc
    users = {u.id: u for u in ctx.db.scalars(select(User))}
    res = att_svc.Resolver(ctx.db)
    rows = []
    for a in ctx.db.scalars(scoped_attendance(ctx, start, end)):
        v = att_svc.view(a, users.get(a.user_id), res)
        rows.append([users[a.user_id].full_name if a.user_id in users else None, a.work_date, a.check_in.isoformat(), a.check_out.isoformat() if a.check_out else "",
                     v["worked_hours"], v["break_minutes"], v["overtime_hours"], v["late_minutes"], v["early_minutes"], v["status"] or "", v["day_type"] or "",
                     a.work_mode, "yes" if a.auto_closed else ""])
    return _csv_response("attendance.csv", ["Employee", "Date", "Check in", "Check out", "Worked hours", "Break minutes", "Overtime hours", "Late minutes",
                                            "Early departure minutes", "Status", "Day type", "Work mode", "Auto-closed"], rows)


@router.get("/reports/tasks.csv")
def report_tasks(ctx: Ctx = Depends(require_permission("reports.view", "hr", "founder", "manager"))):
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User))}
    pnames = {p.id: p.name for p in ctx.db.scalars(select(Project))}
    stmt = select(Task).order_by(Task.project_id, Task.id)
    if ctx.role == "manager":
        stmt = stmt.where(Task.project_id.in_(select(Project.id).where(Project.owner_id == ctx.user.id)))
    elif ctx.role == "hr":
        stmt = stmt.where(Task.project_id.in_(select(Project.id).where(Project.owner_id.in_(select(User.id).where(user_scope(ctx))))))
    rows = [[pnames.get(t.project_id), t.title, t.status, t.priority, names.get(t.assignee_id, ""), t.due_date or "", t.progress] for t in ctx.db.scalars(stmt)]
    return _csv_response("tasks.csv", ["Project", "Task", "Status", "Priority", "Assignee", "Due date", "Progress %"], rows)


@router.get("/reports/leave.csv")
def report_leave(ctx: Ctx = Depends(require_roles("hr", "founder"))):
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User))}
    types_ = {t.id: t.name for t in ctx.db.scalars(select(LeaveType))}
    stmt = select(LeaveRequest).order_by(LeaveRequest.id)
    if ctx.role == "hr":
        stmt = stmt.where(LeaveRequest.user_id.in_(select(User.id).where(user_scope(ctx))))
    rows = [[names.get(r.user_id), types_.get(r.leave_type_id), r.start_date, r.end_date, r.days, r.status] for r in ctx.db.scalars(stmt)]
    return _csv_response("leave.csv", ["Employee", "Type", "Start", "End", "Days", "Status"], rows)
