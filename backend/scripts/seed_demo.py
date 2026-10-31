"""Seed a demo company through the public API (dev only).

    python scripts/seed_demo.py --api http://localhost:8000 --admin-email admin@worksphere.dev --admin-password '...'

Every account gets the same demo password, printed at the end. Never run against production.
"""
import argparse
import sys
from datetime import date, timedelta

import httpx

DEMO_PW = "Admin@2205"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--admin-email", required=True)
    ap.add_argument("--admin-password", required=True)
    ap.add_argument("--slug", default="acme")
    ap.add_argument("--org-only", action="store_true", help="only add branches/board data to an already seeded company")
    a = ap.parse_args()
    c = httpx.Client(base_url=a.api + "/api/v1", timeout=30)

    def call(method, url, token=None, **kw):
        r = c.request(method, url, headers={"Authorization": f"Bearer {token}"} if token else None, **kw)
        if r.status_code >= 400:
            sys.exit(f"{method} {url} -> {r.status_code}: {r.text}")
        return r.json() if r.content else None

    login = lambda email: call("POST", "/auth/login", json={"email": email, "password": DEMO_PW})["access_token"]
    if a.org_only:
        seed_org(call, login, a.slug)
        return 0
    admin = call("POST", "/auth/login", json={"email": a.admin_email, "password": a.admin_password})["access_token"]
    call("POST", "/platform/companies", admin, json={
        "name": "Acme Corporation", "slug": a.slug, "founder_name": "Fiona Founder",
        "founder_email": f"founder@{a.slug}.com", "founder_password": DEMO_PW})
    f = login(f"founder@{a.slug}.com")
    eng = call("POST", "/departments", f, json={"name": "Engineering", "description": "Product engineering"})
    ops = call("POST", "/departments", f, json={"name": "People & Ops"})
    users = {}
    for key, name, role, dept, mgr in [
        ("hr", "Hannah HR", "hr", ops["id"], None), ("mgr", "Marcus Manager", "manager", eng["id"], None),
        ("e1", "Elena Engineer", "employee", eng["id"], "mgr"), ("e2", "Ethan Engineer", "employee", eng["id"], "mgr"),
        ("e3", "Priya Designer", "employee", eng["id"], "mgr")]:
        users[key] = call("POST", "/employees", f, json={
            "email": f"{key}@{a.slug}.com", "full_name": name, "password": DEMO_PW, "role": role, "department_id": dept,
            "manager_id": users[mgr]["id"] if mgr else None, "designation": role.title()})
    m = login(f"mgr@{a.slug}.com")
    today = date.today()
    p = call("POST", "/projects", m, json={"name": "Customer Portal Redesign", "description": "New self-service portal", "status": "active",
                                          "start_date": str(today - timedelta(days=14)), "due_date": str(today + timedelta(days=45)),
                                          "member_ids": [users[k]["id"] for k in ("e1", "e2", "e3")]})
    call("POST", f"/projects/{p['id']}/milestones", m, json={"title": "Design sign-off", "due_date": str(today + timedelta(days=10))})
    tasks = []
    for title, who, prio, due in [("Wireframes", "e3", "high", 3), ("Design system tokens", "e3", "medium", 9), ("Auth flow", "e1", "urgent", -2),
                                  ("API integration", "e2", "high", 12), ("QA test plan", "e1", "low", 20)]:
        tasks.append(call("POST", f"/projects/{p['id']}/tasks", m, json={"title": title, "assignee_id": users[who]["id"], "priority": prio, "due_date": str(today + timedelta(days=due))}))
    call("PUT", f"/tasks/{tasks[3]['id']}/dependencies", m, json={"depends_on": [tasks[2]["id"]]})
    e1 = login(f"e1@{a.slug}.com")
    call("PATCH", f"/tasks/{tasks[2]['id']}", e1, json={"status": "in_progress", "progress": 60})
    call("POST", "/attendance/check-in", e1)
    call("POST", "/daily-updates", e1, json={"work_date": str(today), "completed": "Implemented login form and token refresh", "hours_worked": 7.5, "blockers": "Waiting on SSO test tenant", "next_plan": "Finish auth flow"})
    # --- HR / founder data: holidays, leave, attendance, updates, a new hire in onboarding ---
    hr, fo = login(f"hr@{a.slug}.com"), f
    lt = call("GET", "/leave/types", f)["items"]
    annual = lt[0] if lt else call("POST", "/leave/types", hr, json={"name": "Annual Leave", "annual_quota": 20, "paid": True})
    weekday = lambda d: d + timedelta(days=(7 - d.weekday()) % 7 if d.weekday() >= 5 else 0)  # holidays must be Mon-Fri
    for name, d in [("Company Offsite", weekday(today + timedelta(days=21))), ("Founders Day", weekday(today + timedelta(days=35)))]:
        call("POST", "/leave/holidays", hr, json={"name": name, "date": str(d)})
    e2, e3 = login(f"e2@{a.slug}.com"), login(f"e3@{a.slug}.com")
    pending = call("POST", "/leave/requests", e2, json={"leave_type_id": annual["id"], "start_date": str(today + timedelta(days=7)), "end_date": str(today + timedelta(days=9)), "reason": "Family trip"})
    approved = call("POST", "/leave/requests", e3, json={"leave_type_id": annual["id"], "start_date": str(today + timedelta(days=14)), "end_date": str(today + timedelta(days=15)), "reason": "Personal"})
    call("POST", f"/leave/requests/{approved['id']}/decision", hr, json={"approved": True, "note": "Enjoy"})
    call("POST", "/leave/requests", hr, json={"leave_type_id": annual["id"], "start_date": str(today + timedelta(days=30)), "end_date": str(today + timedelta(days=31)), "reason": "HR planned leave"})
    for tok in (hr, fo, e2):
        call("POST", "/attendance/check-in", tok)
    call("POST", "/daily-updates", hr, json={"work_date": str(today), "completed": "Reviewed onboarding checklist and leave policy", "hours_worked": 8, "next_plan": "Interview candidates"})
    call("POST", "/daily-updates", fo, json={"work_date": str(today), "completed": "Quarterly planning with managers", "hours_worked": 8, "blockers": "Hiring budget approval", "next_plan": "Investor update"})
    call("POST", "/employees", hr, json={"email": f"newhire@{a.slug}.com", "full_name": "Nina NewHire", "password": DEMO_PW, "role": "employee",
                                         "department_id": eng["id"], "manager_id": users["mgr"]["id"], "designation": "Junior Engineer"})
    seed_org(call, login, a.slug)
    print(f"Seeded. Company slug: {a.slug}\nLogins (password {DEMO_PW}):")
    for e in ["founder"] + list(users) + ["board"]:
        print(f"  {e}@{a.slug}.com")
    return 0


def seed_org(call, login, slug) -> None:
    """Branches, branch assignment, a board member and one direct-line exception (idempotent enough for reruns)."""
    f = login(f"founder@{slug}.com")
    existing = {b["code"]: b for b in call("GET", "/branches", f)["items"]}
    mk = lambda name, code, city, country: existing.get(code) or call("POST", "/branches", f, json={"name": name, "code": code, "city": city, "country": country})
    hq, east = mk("Head Office", "HQ", "London", "UK"), mk("East Branch", "EAST", "Manchester", "UK")
    people = {e["email"].split("@")[0]: e for e in call("GET", "/employees?page_size=100", f)["items"]}
    for key, branch in (("hr", hq), ("mgr", hq), ("e1", hq), ("e2", hq), ("e3", east)):
        if key in people and people[key]["branch_id"] is None:
            call("POST", f"/branches/{branch['id']}/members", f, json={"user_ids": [people[key]["id"]]})
    if not any(m["email"] == f"board@{slug}.com" for m in call("GET", "/board/members", f)["items"]):
        call("POST", "/board/members", f, json={"email": f"board@{slug}.com", "full_name": "Beatrice Board", "password": DEMO_PW, "designation": "Board Chair",
                                                 "responsibilities": "Strategy and governance oversight", "term_start": str(date.today())})


if __name__ == "__main__":
    raise SystemExit(main())
