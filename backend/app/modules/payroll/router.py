"""Payroll API.

Who may do what (enforced here, never in the UI):
* founder: everything.  HR without a branch: everything except the pay of founders / board members / other HR.
* HR with a branch: pay structures and payslips of employees and managers in their own branch only; cannot create or process runs.
* managers, board members, employees: no access to anyone's pay. Everyone can read their OWN payslips once a run is approved.
* a run is created and submitted by one person and approved by a different one. Approved payslips are frozen.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, select

from app.access import user_scope
from app.common import PageParams, audit, get_setting, paginate, to_csv
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.db.base import utcnow
from app.db.tenant_models import (Compensation, CompensationLine, Department, Payslip, PayslipLine, PayrollRun, SalaryComponent, User)
from app.deps import Ctx, get_ctx, require_roles
from app.modules.notifications.service import notify
from app.modules.payroll import engine as eng
from app.modules.payroll import service as svc

router = APIRouter(prefix="/payroll", tags=["payroll"])
staff = require_roles("hr", "founder")
CALCS = ("fixed", "percent_of_basic", "percent_of_gross")


def run_manager(ctx: Ctx = Depends(staff)) -> Ctx:
    """Creating, calculating and approving a company-wide run: the founder, or HR who is not tied to one branch."""
    if ctx.role == "hr" and ctx.user.branch_id is not None:
        raise Forbidden("Payroll runs are managed by company-level HR or a founder")
    return ctx


# ---------------------------------------------------------------- money helpers

def to_amount(value: float | int | str, field: str = "amount") -> Decimal:
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise AppError(f"{field} is not a number", status_code=422) from None
    if d != d.quantize(eng.CENT):
        raise AppError(f"{field} can have at most two decimals", status_code=422)
    return d


def value_to_stored(calc: str, value: float | int | str) -> int:
    """fixed: money -> minor units; percentage: percent -> basis points."""
    d = to_amount(value, "value")
    if d < 0:
        raise AppError("Values cannot be negative", status_code=422)
    if calc == "fixed":
        return eng.to_minor(d)
    if d > 100:
        raise AppError("A percentage cannot exceed 100", status_code=422)
    return int((d * 100).to_integral_value())


def stored_to_value(calc: str, v: int) -> float:
    return float(eng.from_minor(v)) if calc == "fixed" else float(Decimal(v) / 100)


def m(minor: int) -> float:
    return float(eng.from_minor(minor))


# ---------------------------------------------------------------- scope

def visible_people(ctx: Ctx):
    """SQL condition over User: whose pay this caller may see."""
    if ctx.role == "founder":
        return and_(User.role.in_(svc.PAID_ROLES))
    return and_(User.role.in_(("employee", "manager")), user_scope(ctx))


def pay_user(ctx: Ctx, user_id: int) -> User:
    u = ctx.db.scalar(select(User).where(User.id == user_id, visible_people(ctx)))
    if u is None or u.id == ctx.user.id and ctx.role != "founder":
        raise NotFound("Employee not found")
    return u


# ================================================================== components

class ComponentIn(BaseModel):
    code: str = Field(min_length=2, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["earning", "deduction"]
    calc: Literal["fixed", "percent_of_basic", "percent_of_gross"] = "fixed"
    default_value: float = Field(0, ge=0)
    prorate: bool = True
    cap: float | None = Field(None, ge=0)
    note: str | None = Field(None, max_length=300)
    is_active: bool = True

    @model_validator(mode="after")
    def _rules(self):
        if self.kind == "earning" and self.calc == "percent_of_gross":
            raise ValueError("An earning cannot be a percentage of gross pay (gross is made of earnings)")
        return self


def ser_component(c: SalaryComponent) -> dict:
    return {"id": c.id, "code": c.code, "name": c.name, "kind": c.kind, "calc": c.calc, "default_value": stored_to_value(c.calc, c.default_value),
            "prorate": c.prorate, "cap": m(c.cap_minor) if c.cap_minor is not None else None, "note": c.note, "is_active": c.is_active}


@router.get("/components")
def components(ctx: Ctx = Depends(staff)):
    return {"items": [ser_component(c) for c in ctx.db.scalars(select(SalaryComponent).order_by(SalaryComponent.kind.desc(), SalaryComponent.name))]}


@router.post("/components", status_code=201)
def create_component(body: ComponentIn, ctx: Ctx = Depends(run_manager)):
    code = body.code.upper()
    if ctx.db.scalar(select(SalaryComponent.id).where((SalaryComponent.code == code) | (func.lower(SalaryComponent.name) == body.name.lower()))) or code in ("BASIC", "OVERTIME", "ADJ"):
        raise Conflict("A component with this code or name already exists")
    c = SalaryComponent(code=code, name=body.name.strip(), kind=body.kind, calc=body.calc, default_value=value_to_stored(body.calc, body.default_value),
                        prorate=body.prorate, cap_minor=eng.to_minor(to_amount(body.cap, "cap")) if body.cap is not None else None, note=body.note, is_active=body.is_active)
    ctx.db.add(c)
    ctx.db.flush()
    audit(ctx, "payroll.component_created", "salary_component", c.id, {"code": c.code, "kind": c.kind, "calc": c.calc})
    ctx.db.commit()
    return ser_component(c)


@router.patch("/components/{cid}")
def update_component(cid: int, body: ComponentIn, ctx: Ctx = Depends(run_manager)):
    c = ctx.db.get(SalaryComponent, cid)
    if c is None:
        raise NotFound()
    used = ctx.db.scalar(select(CompensationLine.id).where(CompensationLine.component_id == cid))
    if used and (body.kind != c.kind or body.calc != c.calc or body.code.upper() != c.code):
        raise Conflict("This component is already in use; its type and code cannot change. Deactivate it and create a new one.")
    if ctx.db.scalar(select(SalaryComponent.id).where(SalaryComponent.id != cid, (SalaryComponent.code == body.code.upper()) | (func.lower(SalaryComponent.name) == body.name.lower()))):
        raise Conflict("A component with this code or name already exists")
    c.code, c.name, c.kind, c.calc = body.code.upper(), body.name.strip(), body.kind, body.calc
    c.default_value, c.prorate, c.note, c.is_active = value_to_stored(body.calc, body.default_value), body.prorate, body.note, body.is_active
    c.cap_minor = eng.to_minor(to_amount(body.cap, "cap")) if body.cap is not None else None
    audit(ctx, "payroll.component_updated", "salary_component", c.id)  # issued payslips keep the figures they were issued with
    ctx.db.commit()
    return ser_component(c)


# ================================================================== pay structures (versioned)

class LineIn(BaseModel):
    component_id: int
    value: float = Field(ge=0)


class CompensationIn(BaseModel):
    effective_from: date
    basic: float = Field(gt=0, le=1_000_000_000)
    currency: str | None = Field(None, min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    note: str | None = Field(None, max_length=300)
    lines: list[LineIn] = Field(default_factory=list, max_length=40)


def ser_comp(c: Compensation, comps: dict[int, SalaryComponent]) -> dict:
    return {"id": c.id, "user_id": c.user_id, "effective_from": c.effective_from, "basic": m(c.basic_minor), "currency": c.currency, "note": c.note,
            "created_at": c.created_at, "lines": [{"component_id": ln.component_id, "code": comps[ln.component_id].code, "name": comps[ln.component_id].name,
                                                   "kind": comps[ln.component_id].kind, "calc": comps[ln.component_id].calc,
                                                   "value": stored_to_value(comps[ln.component_id].calc, ln.value)} for ln in c.lines if ln.component_id in comps]}


@router.get("/compensation")
def compensation_overview(params: PageParams = Depends(), q: str | None = None, ctx: Ctx = Depends(staff)):
    """Everyone whose pay you may manage, with their current structure (or none)."""
    stmt = select(User).where(visible_people(ctx), User.is_active.is_(True)).order_by(User.full_name)
    if q:
        stmt = stmt.where(func.lower(User.full_name).like(f"%{q.lower()}%"))
    today = utcnow().date()

    def row(u: User) -> dict:
        c = svc.current_compensation(ctx.db, u.id, today)
        return {"user_id": u.id, "name": u.full_name, "role": u.role, "designation": u.designation, "employee_code": u.employee_code,
                "effective_from": c.effective_from if c else None, "basic": m(c.basic_minor) if c else None, "currency": c.currency if c else None}
    return paginate(ctx.db, stmt, params, row)


@router.get("/compensation/{user_id}")
def compensation_history(user_id: int, ctx: Ctx = Depends(staff)):
    u = pay_user(ctx, user_id)
    comps = {c.id: c for c in ctx.db.scalars(select(SalaryComponent))}
    rows = ctx.db.scalars(select(Compensation).where(Compensation.user_id == u.id).order_by(Compensation.effective_from.desc()))
    audit(ctx, "payroll.compensation_viewed", "user", u.id)
    ctx.db.commit()
    return {"user": {"id": u.id, "name": u.full_name, "role": u.role}, "items": [ser_comp(c, comps) for c in rows]}


@router.post("/compensation/{user_id}", status_code=201)
def set_compensation(user_id: int, body: CompensationIn, ctx: Ctx = Depends(staff)):
    """Add a new version of someone's pay. Earlier versions are kept, and payslips already issued never change."""
    u = pay_user(ctx, user_id)
    if ctx.db.scalar(select(Compensation.id).where(Compensation.user_id == u.id, Compensation.effective_from == body.effective_from)):
        raise Conflict("There is already a pay structure starting on this date")
    closed = ctx.db.scalar(select(func.count(PayrollRun.id)).where(PayrollRun.status.in_(("approved", "paid")), PayrollRun.period_end >= body.effective_from,
                                                                    PayrollRun.period_start <= body.effective_from))
    if closed:
        raise AppError("That date falls in a month whose payroll is already approved. Choose a later date; issued payslips cannot change.")
    comps = {c.id: c for c in ctx.db.scalars(select(SalaryComponent))}
    seen: set[int] = set()
    new = Compensation(user_id=u.id, effective_from=body.effective_from, basic_minor=eng.to_minor(to_amount(body.basic, "basic")),
                       currency=(body.currency or svc.policy(ctx.db)["currency"]).upper(), note=body.note, created_by=ctx.user.id)
    for ln in body.lines:
        c = comps.get(ln.component_id)
        if c is None or not c.is_active:
            raise AppError("Unknown or inactive salary component")
        if ln.component_id in seen:
            raise AppError(f"{c.name} appears twice")
        seen.add(ln.component_id)
        new.lines.append(CompensationLine(component_id=c.id, value=value_to_stored(c.calc, ln.value)))
    ctx.db.add(new)
    ctx.db.flush()
    audit(ctx, "payroll.compensation_set", "user", u.id, {"effective_from": str(body.effective_from), "lines": len(new.lines)})  # amounts stay out of the log
    ctx.db.commit()
    return ser_comp(new, comps)


# ================================================================== runs

class RunIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    note: str | None = Field(None, max_length=300)


def _slips_q(ctx: Ctx, run_id: int):
    q = select(Payslip).where(Payslip.run_id == run_id).order_by(Payslip.employee_name)
    return q.join(User, User.id == Payslip.user_id).where(visible_people(ctx))


def ser_slip(s: Payslip, detail: bool = False) -> dict:
    out = {"id": s.id, "run_id": s.run_id, "user_id": s.user_id, "employee": s.employee_name, "employee_code": s.employee_code, "currency": s.currency,
           "basic": m(s.basic_minor), "gross": m(s.gross_minor), "deductions": m(s.deductions_minor), "net": m(s.net_minor), "warnings": s.warnings or []}
    if detail:
        out |= {"designation": s.designation, "facts": s.facts,
                "lines": [{"id": ln.id, "code": ln.code, "name": ln.name, "kind": ln.kind, "amount": m(ln.amount_minor), "basis": ln.basis, "adjustment": ln.is_adjustment}
                          for ln in s.lines]}
    return out


def ser_run(ctx: Ctx, r: PayrollRun, with_totals: bool = True) -> dict:
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User))}
    out = {"id": r.id, "year": r.year, "month": r.month, "period_start": r.period_start, "period_end": r.period_end, "status": r.status, "note": r.note,
           "created_by": names.get(r.created_by), "processed_by": names.get(r.processed_by), "processed_at": r.processed_at, "approved_by": names.get(r.approved_by),
           "approved_at": r.approved_at, "paid_at": r.paid_at, "payment_reference": r.payment_reference, "policy": r.settings, "skipped": r.skipped or []}
    if with_totals:
        rows = ctx.db.execute(select(func.count(Payslip.id), func.coalesce(func.sum(Payslip.gross_minor), 0), func.coalesce(func.sum(Payslip.deductions_minor), 0),
                                     func.coalesce(func.sum(Payslip.net_minor), 0)).select_from(Payslip).join(User, User.id == Payslip.user_id)
                              .where(Payslip.run_id == r.id, visible_people(ctx))).one()
        out["totals"] = {"payslips": rows[0], "gross": m(rows[1]), "deductions": m(rows[2]), "net": m(rows[3])}
    return out


def _run(ctx: Ctx, rid: int) -> PayrollRun:
    r = ctx.db.get(PayrollRun, rid)
    if r is None:
        raise NotFound("Payroll run not found")
    return r


@router.get("/runs")
def list_runs(ctx: Ctx = Depends(staff)):
    return {"items": [ser_run(ctx, r) for r in ctx.db.scalars(select(PayrollRun).order_by(PayrollRun.year.desc(), PayrollRun.month.desc(), PayrollRun.id.desc()))]}


@router.post("/runs", status_code=201)
def create_run(body: RunIn, ctx: Ctx = Depends(run_manager)):
    start, end = svc.period_of(body.year, body.month)
    if start > utcnow().date():
        raise AppError("Payroll cannot be run for a month that has not started")
    if ctx.db.scalar(select(PayrollRun.id).where(PayrollRun.year == body.year, PayrollRun.month == body.month, PayrollRun.status != "cancelled")):
        raise Conflict("There is already a payroll run for this month")
    r = PayrollRun(year=body.year, month=body.month, period_start=start, period_end=end, note=body.note, created_by=ctx.user.id)
    ctx.db.add(r)
    ctx.db.flush()
    result = svc.calculate_run(ctx.db, r)
    audit(ctx, "payroll.run_created", "payroll_run", r.id, {"period": f"{body.year}-{body.month:02d}", **result})
    ctx.db.commit()
    return ser_run(ctx, r)


@router.get("/runs/{rid}")
def get_run(rid: int, ctx: Ctx = Depends(staff)):
    r = _run(ctx, rid)
    slips = ctx.db.scalars(_slips_q(ctx, rid)).all()
    depts = {d.id: d.name for d in ctx.db.scalars(select(Department))}
    by_dept: dict[str, dict] = {}
    for s in slips:
        u = ctx.db.get(User, s.user_id)
        d = by_dept.setdefault(depts.get(u.department_id, "No department"), {"department": depts.get(u.department_id, "No department"), "people": 0, "gross": 0, "net": 0})
        d["people"] += 1
        d["gross"] += s.gross_minor
        d["net"] += s.net_minor
    return {**ser_run(ctx, r), "payslips": [ser_slip(s) for s in slips],
            "by_department": [{**d, "gross": m(d["gross"]), "net": m(d["net"])} for d in sorted(by_dept.values(), key=lambda x: x["department"])]}


def _draft(r: PayrollRun) -> None:
    if r.status != "draft":
        raise Conflict(f"This run is {r.status}; only a draft can be changed")


@router.post("/runs/{rid}/recalculate")
def recalculate(rid: int, ctx: Ctx = Depends(run_manager)):
    """Rebuild every payslip of a draft from today's pay structures, leave, attendance and settings (one-off adjustments are kept)."""
    r = _run(ctx, rid)
    _draft(r)
    result = svc.calculate_run(ctx.db, r)
    audit(ctx, "payroll.run_recalculated", "payroll_run", r.id, result)
    ctx.db.commit()
    return ser_run(ctx, r)


@router.post("/runs/{rid}/submit")
def submit(rid: int, ctx: Ctx = Depends(run_manager)):
    r = _run(ctx, rid)
    _draft(r)
    if not ctx.db.scalar(select(Payslip.id).where(Payslip.run_id == rid)):
        raise AppError("There are no payslips in this run")
    r.status, r.processed_by, r.processed_at = "processed", ctx.user.id, utcnow()
    audit(ctx, "payroll.run_submitted", "payroll_run", r.id)
    approvers = [u.id for u in ctx.db.scalars(select(User).where(User.is_active.is_(True), User.id != ctx.user.id,
                                                                  (User.role == "founder") | ((User.role == "hr") & User.branch_id.is_(None))))]
    notify(ctx.db, approvers, "Payroll awaiting approval", f"{r.year}-{r.month:02d} was submitted by {ctx.user.full_name}", "payroll", f"/payroll/runs/{r.id}")
    ctx.db.commit()
    return ser_run(ctx, r)


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=300)


@router.post("/runs/{rid}/return")
def send_back(rid: int, body: RejectIn, ctx: Ctx = Depends(run_manager)):
    """The approver sends a submitted run back to draft with a reason."""
    r = _run(ctx, rid)
    if r.status != "processed":
        raise Conflict("Only a submitted run can be sent back")
    if r.processed_by == ctx.user.id:
        raise Forbidden("Someone other than the person who submitted it reviews a run")
    r.status = "draft"
    audit(ctx, "payroll.run_returned", "payroll_run", r.id, {"note": body.note})
    notify(ctx.db, [r.processed_by] if r.processed_by else [], "Payroll sent back", body.note, "payroll", f"/payroll/runs/{r.id}")
    ctx.db.commit()
    return ser_run(ctx, r)


@router.post("/runs/{rid}/approve")
def approve(rid: int, ctx: Ctx = Depends(run_manager)):
    r = _run(ctx, rid)
    if r.status != "processed":
        raise Conflict("Only a submitted run can be approved")
    if r.processed_by == ctx.user.id:
        raise Forbidden("A run must be approved by someone other than the person who submitted it")
    blocked = ctx.db.scalar(select(func.count(Payslip.id)).where(Payslip.run_id == rid, Payslip.net_minor < 0)) or 0
    if blocked:
        raise AppError(f"{blocked} payslip(s) have deductions larger than pay. Fix them (pay structure or an adjustment) and recalculate.", code="payslip_blocked")
    r.status, r.approved_by, r.approved_at = "approved", ctx.user.id, utcnow()
    audit(ctx, "payroll.run_approved", "payroll_run", r.id)
    notify(ctx.db, [s.user_id for s in ctx.db.scalars(select(Payslip).where(Payslip.run_id == rid))], "Your payslip is available",
           f"Payslip for {r.year}-{r.month:02d}", "payroll", "/payslips")
    ctx.db.commit()
    return ser_run(ctx, r)


class PaidIn(BaseModel):
    reference: str | None = Field(None, max_length=120)


@router.post("/runs/{rid}/mark-paid")
def mark_paid(rid: int, body: PaidIn, ctx: Ctx = Depends(run_manager)):
    """Record that the money was sent (this system does not move money)."""
    r = _run(ctx, rid)
    if r.status != "approved":
        raise Conflict("Only an approved run can be marked as paid")
    r.status, r.paid_at, r.payment_reference = "paid", utcnow(), body.reference
    audit(ctx, "payroll.run_paid", "payroll_run", r.id)
    ctx.db.commit()
    return ser_run(ctx, r)


@router.post("/runs/{rid}/cancel")
def cancel(rid: int, ctx: Ctx = Depends(run_manager)):
    r = _run(ctx, rid)
    if r.status not in ("draft", "processed"):
        raise Conflict("An approved run cannot be cancelled")
    r.status = "cancelled"
    audit(ctx, "payroll.run_cancelled", "payroll_run", r.id)
    ctx.db.commit()
    return ser_run(ctx, r)


@router.get("/runs/{rid}/export.csv")
def export_run(rid: int, ctx: Ctx = Depends(staff)):
    r = _run(ctx, rid)
    rows = [[s.employee_code or "", s.employee_name, s.currency, m(s.basic_minor), m(s.gross_minor), m(s.deductions_minor), m(s.net_minor), ", ".join(s.warnings or [])]
            for s in ctx.db.scalars(_slips_q(ctx, rid))]
    audit(ctx, "payroll.run_exported", "payroll_run", r.id, {"rows": len(rows)})
    ctx.db.commit()
    body = to_csv(["Employee code", "Employee", "Currency", "Basic", "Gross", "Deductions", "Net", "Warnings"], rows)
    return Response(body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="payroll-{r.year}-{r.month:02d}.csv"'})


# ================================================================== payslips

class AdjustmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["earning", "deduction"]
    amount: float = Field(gt=0, le=1_000_000_000)


def _slip_of(ctx: Ctx, sid: int, *, manage: bool = False) -> Payslip:
    """A payslip you may open: your own (once approved), or, as payroll staff, one in your scope. Anything else does not exist."""
    s = ctx.db.get(Payslip, sid)
    if s is None:
        raise NotFound("Payslip not found")
    run = ctx.db.get(PayrollRun, s.run_id)
    if s.user_id == ctx.user.id and not manage:
        if run.status in ("approved", "paid"):
            return s
        raise NotFound("Payslip not found")
    if ctx.role not in ("hr", "founder") or not ctx.db.scalar(select(User.id).where(User.id == s.user_id, visible_people(ctx))):
        raise NotFound("Payslip not found")
    return s


@router.get("/payslips/{sid}")
def get_payslip(sid: int, ctx: Ctx = Depends(get_ctx)):
    s = _slip_of(ctx, sid)
    run = ctx.db.get(PayrollRun, s.run_id)
    if s.user_id != ctx.user.id:
        audit(ctx, "payroll.payslip_viewed", "payslip", s.id, {"user_id": s.user_id})
        ctx.db.commit()
    return {**ser_slip(s, detail=True), "period": {"year": run.year, "month": run.month, "start": run.period_start, "end": run.period_end}, "run_status": run.status}


@router.post("/payslips/{sid}/adjustments")
def add_adjustment(sid: int, body: AdjustmentIn, ctx: Ctx = Depends(run_manager)):
    """A one-off bonus, correction or recovery on a draft payslip."""
    s = _slip_of(ctx, sid, manage=True)
    _draft(ctx.db.get(PayrollRun, s.run_id))
    adj = [(ln.name, ln.kind, ln.amount_minor) for ln in s.lines if ln.is_adjustment]
    adj.append((body.name.strip(), body.kind, eng.to_minor(to_amount(body.amount))))
    svc.rebuild_slip(ctx.db, s, adj)
    audit(ctx, "payroll.adjustment_added", "payslip", s.id, {"kind": body.kind})
    ctx.db.commit()
    return ser_slip(s, detail=True)


@router.delete("/payslips/{sid}/adjustments/{line_id}")
def remove_adjustment(sid: int, line_id: int, ctx: Ctx = Depends(run_manager)):
    s = _slip_of(ctx, sid, manage=True)
    _draft(ctx.db.get(PayrollRun, s.run_id))
    target = next((ln for ln in s.lines if ln.id == line_id and ln.is_adjustment), None)
    if target is None:
        raise NotFound("Adjustment not found")
    adj = [(ln.name, ln.kind, ln.amount_minor) for ln in s.lines if ln.is_adjustment and ln.id != line_id]
    svc.rebuild_slip(ctx.db, s, adj)
    audit(ctx, "payroll.adjustment_removed", "payslip", s.id)
    ctx.db.commit()
    return ser_slip(s, detail=True)


@router.get("/my-payslips")
def my_payslips(ctx: Ctx = Depends(get_ctx)):
    """Your own payslips from approved runs, newest first."""
    q = (select(Payslip, PayrollRun).join(PayrollRun, PayrollRun.id == Payslip.run_id)
         .where(Payslip.user_id == ctx.user.id, PayrollRun.status.in_(("approved", "paid"))).order_by(PayrollRun.year.desc(), PayrollRun.month.desc()))
    return {"items": [{**ser_slip(s), "year": r.year, "month": r.month, "status": r.status} for s, r in ctx.db.execute(q)]}


@router.get("/employees/{user_id}/payslips")
def payroll_history(user_id: int, ctx: Ctx = Depends(staff)):
    """One person's payslips over time (payroll staff in scope)."""
    u = pay_user(ctx, user_id)
    q = (select(Payslip, PayrollRun).join(PayrollRun, PayrollRun.id == Payslip.run_id)
         .where(Payslip.user_id == u.id, PayrollRun.status != "cancelled").order_by(PayrollRun.year.desc(), PayrollRun.month.desc()))
    audit(ctx, "payroll.history_viewed", "user", u.id)
    ctx.db.commit()
    return {"items": [{**ser_slip(s), "year": r.year, "month": r.month, "status": r.status} for s, r in ctx.db.execute(q)]}


# ================================================================== reports

@router.get("/reports/summary")
def summary(year: int | None = None, ctx: Ctx = Depends(staff)):
    """Totals per month for approved and paid runs."""
    year = year or utcnow().date().year
    out = []
    for r in ctx.db.scalars(select(PayrollRun).where(PayrollRun.year == year, PayrollRun.status.in_(("approved", "paid"))).order_by(PayrollRun.month)):
        t = ser_run(ctx, r)["totals"]
        out.append({"run_id": r.id, "month": r.month, "status": r.status, **t})
    return {"year": year, "months": out, "totals": {k: round(sum(x[k] for x in out), 2) for k in ("payslips", "gross", "deductions", "net")}}
