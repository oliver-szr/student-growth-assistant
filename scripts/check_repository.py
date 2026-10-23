"""Dependency-free checks of publishable links, project paths and CI configuration.

ci.yml intentionally uses YAML 1.2's JSON subset so its syntax and selected
invariants can be checked with Python's standard library on Windows and Linux.
This is not a replacement for an actual GitHub-hosted workflow run.
"""
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def check():
    names = set(subprocess.check_output(["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")) - {""}
    errors = []
    for name in sorted(names):
        if not name.endswith(".md") or not (ROOT/name).is_file():
            continue
        source = re.sub(r"```.*?```", "", (ROOT/name).read_text(encoding="utf-8-sig"), flags=re.S)
        for raw in re.findall(r"\[[^\]]*\]\(([^)]+)\)", source):
            target = unquote(raw.strip().strip("<>"))
            if not target or target.startswith("#") or urlsplit(target).scheme:
                continue
            path = ((ROOT/name).parent/target.split("#")[0]).resolve()
            if not path.is_relative_to(ROOT) or path.relative_to(ROOT).as_posix() not in names:
                errors.append(f"{name}: unpublished link {target}")
    workflow = json.loads((ROOT/".github/workflows/ci.yml").read_text(encoding="utf-8"))
    assert set(workflow["on"]) == {"pull_request", "push"}
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    backend = workflow["jobs"]["backend"]
    frontend = workflow["jobs"]["frontend"]
    assert backend["runs-on"] == frontend["runs-on"] == "ubuntu-latest"
    assert 0 < backend["timeout-minutes"] <= 20 and 0 < frontend["timeout-minutes"] <= 20
    assert backend["steps"][1]["with"]["python-version"] == "3.11"
    assert frontend["steps"][1]["with"]["node-version"] == "22"
    all_steps = backend["steps"] + frontend["steps"]
    commands = [s["run"] for s in all_steps if "run" in s]
    assert "python -m pip install -r backend/requirements.txt -c backend/constraints.txt" in commands
    assert "npm --prefix frontend ci" in commands
    assert "npm --prefix frontend test" in commands and "npm --prefix frontend run build" in commands
    assert any(s.get("working-directory") == "backend" and "python -m pytest" in s.get("run", "") for s in all_steps)
    assert not any(token in json.dumps(workflow) for token in ("secrets.", "pull_request_target", "conda", "C:\\", "E:\\"))
    for path in ("backend/requirements.txt", "backend/constraints.txt", "backend/tests/conftest.py", "frontend/package-lock.json"):
        assert path in names, path
    if errors:
        raise RuntimeError("\n".join(errors))
    print(f"Repository checks passed: {len(names)} files; CI syntax is valid JSON/YAML 1.2; paths and local links verified.")


if __name__ == "__main__":
    check()
