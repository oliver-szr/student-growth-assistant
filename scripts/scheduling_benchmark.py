"""Fixed anonymous scheduler benchmarks, isolated in deadline-limited processes.

No database or AI is used. Run with app_env from the repository root. Raw output
defaults to ignored scripts/.local; stress cases are deliberately outside CI.
"""
import argparse
import cProfile
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services import assistant_scheduler as scheduler
from app.services.scoped_replanning import constrained_tasks, identify_scope, movement_metrics
from app.services.scheduling_types import SHANGHAI, TimeRuleInput

WEEK = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 7, 50, tzinfo=SHANGHAI)
CASES = ("ample10", "courses30", "stress100", "deadlines", "split", "locked_history", "local_one", "new_course", "two_weeks", "impossible")


def scenario(name):
    count = {"ample10": 10, "courses30": 30, "stress100": 100}.get(name, 4)
    tasks = [dict(ref=f"task:{i+1}", title=f"Anonymous task {i+1}", duration_minutes=30,
                  deadline="2026-10-25T22:00:00+08:00", priority="normal", profile={}) for i in range(count)]
    rules, previous, actions = [], [], []
    feasible = "known_feasible"  # A construction exists, not a solver guarantee.
    if name in ("courses30", "stress100"):
        rules = [TimeRuleInput(i, "course", f"Course {i}", "weekly", time(9), time(12), weekday=i) for i in range(1, 6)]
    if name == "deadlines":
        for task in tasks:
            task["deadline"] = "2026-10-12T10:00:00+08:00"
    if name == "split":
        tasks[0]["duration_minutes"] = 90
        tasks[0]["profile"] = {"splittable": True, "min_block_minutes": 30, "max_segments": 3,
                               "allowed_windows": [{"start_at": f"2026-10-{d:02}T08:00:00+08:00", "end_at": f"2026-10-{d:02}T08:30:00+08:00"} for d in (12, 13, 14)]}
    if name in ("locked_history", "local_one", "new_course"):
        previous = [scheduler.item_for(task, NOW.replace(hour=9+i, minute=0)) for i, task in enumerate(tasks)]
        if name == "locked_history":
            tasks[0]["profile"] = {"locked": True}
            # Already-ended history is retained outside the remaining-work input.
            previous.append(dict(ref="task:past", title="History", start_at="2026-10-12T06:00:00+08:00", end_at="2026-10-12T07:00:00+08:00"))
        elif name == "local_one":
            tasks[0]["duration_minutes"] = 45
            actions = [{"op": "update", "target": "task:1", "fields": {"duration_minutes": 45}}]
        else:
            rules = [TimeRuleInput(1, "course", "New course", "once", time(9), time(11), date=WEEK)]
    if name == "two_weeks":
        for i, task in enumerate(tasks):
            day = 12 if i < 2 else 19
            task["profile"] = {"allowed_windows": [{"start_at": f"2026-10-{day}T08:00:00+08:00", "end_at": f"2026-10-{day}T12:00:00+08:00"}]}
    if name == "impossible":
        tasks[0]["duration_minutes"] = 180
        tasks[0]["deadline"] = "2026-10-12T09:00:00+08:00"
        feasible = "known_infeasible_duration_exceeds_window"
    scope = None
    if name in ("local_one", "new_course"):
        scope, _ = identify_scope(WEEK, NOW, tasks, rules, previous, actions)
        tasks = constrained_tasks(tasks, scope)
    return tasks, rules, previous, scope, feasible


def run_case(name, profile_path=None):
    tasks, rules, previous, scope, feasibility = scenario(name)
    canonical = dict(tasks=tasks, rules=[asdict(r) for r in rules], previous=previous, now=NOW.isoformat(), week=WEEK.isoformat())
    input_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode()).hexdigest()
    strategy_runs = []
    original = scheduler._arrange_single

    def timed(*args, **kwargs):
        started = perf_counter()
        result = original(*args, **kwargs)
        strategy = kwargs.get("strategy", args[7] if len(args) > 7 else "balanced")
        strategy_runs.append(dict(strategy=strategy, seconds=perf_counter()-started, status=result["status"],
                                  diagnostic_codes=[d["code"] for d in result["diagnostics"]],
                                  limits=[{k: d.get(k) for k in ("budget_kind", "expansions", "phase")} for d in result["diagnostics"] if d["code"] == "SEARCH_LIMIT"]))
        return result

    scheduler._arrange_single = timed
    scheduler.dt.cache_clear()
    profiler = cProfile.Profile() if profile_path else None
    if profiler:
        profiler.enable()
    started = perf_counter()
    try:
        result = scheduler.arrange(WEEK, NOW, tasks, rules, previous, False, include_strategies=True)
    finally:
        elapsed = perf_counter()-started
        scheduler._arrange_single = original
        if profiler:
            profiler.disable()
            profiler.dump_stats(profile_path)
    options = result.get("candidate_options", [])
    violations = [scheduler.validate_assistant(WEEK, NOW, tasks, rules, o["items"], previous) for o in options]
    if any(violations):
        raise AssertionError(violations)
    if result["status"] != "ready" and result["items"]:
        raise AssertionError("Failed search must not expose a partial schedule")
    workload = sum(t["duration_minutes"] for t in tasks)
    scheduled = sum(int((scheduler.interval(x)[1]-scheduler.interval(x)[0]).total_seconds()/60) for x in result["items"])
    output = dict(status=result["status"], items=result["items"], candidate_options=options,
                  diagnostics=result.get("diagnostics", []), search_diagnostics=result.get("search_diagnostics", []))
    return dict(case=name, input_sha256=input_hash, task_count=len(tasks), expected_feasibility=feasibility,
                seconds=elapsed, strategy_runs=strategy_runs, valid_candidates=len(options),
                budget_hits=sum("SEARCH_LIMIT" in r["diagnostic_codes"] for r in strategy_runs), expansions=None,
                status=result["status"], workload_minutes=workload, scheduled_minutes=scheduled,
                unscheduled_minutes=workload-scheduled, independent_validation_errors=violations,
                movement=movement_metrics(result["items"], previous), scope=scope, query_count=0, output=output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--timeout", type=float, default=110, help="Per worker process, seconds; never disables solver budgets")
    parser.add_argument("--output", type=Path, default=ROOT/"scripts/.local/scheduling-benchmark.json")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--worker", choices=CASES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(run_case(args.worker, args.profile), ensure_ascii=False))
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = dict(revision=revision, scheduler_sha256=hashlib.sha256(Path(scheduler.__file__).read_bytes()).hexdigest(),
                  python=sys.version, platform=platform.platform(), processor=platform.processor(), cpu_count=os.cpu_count(),
                  methodology="Fresh process per run; elapsed covers all strategies including preprocessing and validation. No DB/AI. Timeout is NOT a legal result. P95 omitted for small samples.",
                  budgets=dict(seconds_per_strategy=20, expansions_per_strategy=50000, beam_states=64), runs=[], summaries={})
    for name in args.cases:
        for index in range(1 if name == "stress100" else args.repeats):
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", name]
            if args.profile:
                command += ["--profile", str(args.profile)]
            try:
                completed = subprocess.run(command, timeout=args.timeout, capture_output=True, text=True, encoding="utf-8",
                                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                if completed.returncode:
                    row = dict(case=name, worker_error=completed.stderr, returncode=completed.returncode)
                else:
                    row = json.loads(completed.stdout)
            except subprocess.TimeoutExpired:
                row = dict(case=name, process_timeout_seconds=args.timeout, status="process_timeout", scheduled_minutes=None, expansions=None)
            report["runs"].append(row)
            valid = [r["seconds"] for r in report["runs"] if r["case"] == name and "seconds" in r]
            report["summaries"][name] = dict(completed_runs=len(valid), median_seconds=statistics.median(valid) if valid else None)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{name} {index+1}: {row.get('status', 'error')} {row.get('seconds')}s", flush=True)
    return int(any("worker_error" in r or "process_timeout_seconds" in r for r in report["runs"]))


if __name__ == "__main__":
    raise SystemExit(main())
