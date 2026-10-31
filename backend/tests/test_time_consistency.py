"""One clock: the server's local date must never leak into business rules (it differs from UTC for hours every day on a non-UTC host)."""
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parent.parent / "app"


def test_no_module_uses_the_servers_local_date():
    offenders = [f"{p.relative_to(APP)}:{i}" for p in APP.rglob("*.py") for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if re.search(r"\bdate\.today\(\)|\bdatetime\.now\(\)|\bdatetime\.today\(\)", line) and "#" not in line.split("date")[0]]
    assert offenders == [], "use utcnow().date() (or the branch timezone via the attendance calendar) instead"
