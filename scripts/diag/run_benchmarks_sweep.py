import os
import sys
import time
import json
import argparse
import statistics
from typing import List, Dict, Any

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.diag.run_diag_experiment import run_single_experiment

CONCURRENCY_LEVELS = [10, 25, 50, 75, 100, 150]

def format_row(level: int, res: Dict[str, Any]) -> str:
    # res has: median_rps, min_rps, max_rps, median_p50, min_p50, max_p50, combined_statuses
    # runs: list of 3 runs
    runs = res.get("runs", [])
    rps_runs = [f"{r['rps']:.1f}" for r in runs]
    p50_runs = [f"{r['p50']:.1f}" for r in runs]
    p95_runs = [f"{r['p95']:.1f}" for r in runs]
    p99_runs = [f"{r['p99']:.1f}" for r in runs]

    statuses_str = json.dumps(res.get("combined_statuses", {}), sort_keys=True)
    med_rps = f"{res['median_rps']:.1f} ({res['min_rps']:.1f}-{res['max_rps']:.1f})"
    med_p50 = f"{res['median_p50']:.1f} ({res['min_p50']:.1f}-{res['max_p50']:.1f})"
    med_p95 = f"{res['median_p95']:.1f} ({res['min_p95']:.1f}-{res['max_p95']:.1f})"
    med_p99 = f"{res['median_p99']:.1f} ({res['min_p99']:.1f}-{res['max_p99']:.1f})"

    return f"| {level:<7} | {med_rps:<17} | {med_p50:<25} | {med_p95:<25} | {med_p99:<25} | {statuses_str:<30} |"

def run_sweep(
    label: str,
    levels: List[int] = CONCURRENCY_LEVELS,
    duration: int = 30,
    repeats: int = 3,
    variants: List[str] = ["a", "b"],
    port: int = 8142,
    output_path: str = None
):
    header = """=======================================================================================================================================
Clients | Throughput RPS    | p50 (ms)                  | p95 (ms)                  | p99 (ms)                  | Statuses                      
---------------------------------------------------------------------------------------------------------------------------------------"""
    footer = """======================================================================================================================================="""

    report_lines = []
    report_lines.append(f"# Benchmark Run: {label}")
    report_lines.append(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Levels: {levels}")
    report_lines.append(f"Duration per run: {duration}s, Repeats: {repeats}")
    report_lines.append(f"Rate Limiter: OFF (RATE_LIMIT_PER_MINUTE=1000000)")
    report_lines.append(f"Think Time: T=0 ms (closed-loop)\n")

    for var in variants:
        var_desc = "Variant (a) [normal seed, ~456 unassigned]" if var == "a" else "Variant (b) [triage-heavy, 5000 unassigned]"
        report_lines.append(f"\n### {var_desc}\n")
        report_lines.append(header)
        print(f"\n--- Running Sweep for {var_desc} ---")

        for c in levels:
            print(f"\n>>> Running level: {c} concurrent clients (30s x {repeats}) on Variant {var}...")
            # Fresh server + fresh temp DB for each level
            res = run_single_experiment(
                variant=var,
                cache_enabled=True,
                clients=c,
                duration=duration,
                repeats=repeats,
                think_time_ms=0,
                enable_dump=False,
                enable_rate_limit=False,
                port=port,
                label=f"{label}_var{var}_c{c}"
            )
            row = format_row(c, res)
            report_lines.append(row)
            print(row)

        report_lines.append(footer)

    full_report = "\n".join(report_lines) + "\n"
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_report)
        print(f"\n[Saved full raw report to {output_path}]")

    return full_report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", type=str, required=True)
    parser.add_argument("--output", type=str, required=True)
    parser.add_argument("--levels", type=str, default="10,25,50,75,100,150")
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--variants", type=str, default="a,b")
    parser.add_argument("--port", type=int, default=8142)
    args = parser.parse_args()

    levels = [int(x.strip()) for x in args.levels.split(",") if x.strip()]
    variants = [x.strip() for x in args.variants.split(",") if x.strip()]

    run_sweep(
        label=args.label,
        levels=levels,
        duration=args.duration,
        repeats=args.repeats,
        variants=variants,
        port=args.port,
        output_path=args.output
    )
