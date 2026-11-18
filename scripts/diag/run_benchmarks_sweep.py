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
    total_reqs = res.get("total_requests", 0)
    count_2xx = res.get("combined_2xx", 0)
    goodput_str = f"{res.get('median_goodput', 0.0):.1f} ({res.get('min_goodput', 0.0):.1f}-{res.get('max_goodput', 0.0):.1f})"
    shed_str = f"{res.get('shed_rate_503', 0.0):.1f}%"
    err_str = f"{res.get('error_rate_599', 0.0):.1f}%"
    c429 = res.get("combined_statuses", {}).get(429, 0)
    c409 = res.get("combined_statuses", {}).get(409, 0)
    c429_409 = f"{c429}/{c409}"
    
    if res.get("has_2xx", False):
        p50_2xx_str = f"{res['median_p50_2xx']:.1f} ({res['min_p50_2xx']:.1f}-{res['max_p50_2xx']:.1f})"
        p95_2xx_str = f"{res['median_p95_2xx']:.1f} ({res['min_p95_2xx']:.1f}-{res['max_p95_2xx']:.1f})"
        p99_2xx_str = f"{res['median_p99_2xx']:.1f} ({res['min_p99_2xx']:.1f}-{res['max_p99_2xx']:.1f})"
    else:
        p50_2xx_str = "N/A (0 2xx)"
        p95_2xx_str = "N/A (0 2xx)"
        p99_2xx_str = "N/A (0 2xx)"

    p50_all_str = f"{res.get('median_p50_all', 0.0):.1f} ({res.get('min_p50_all', 0.0):.1f}-{res.get('max_p50_all', 0.0):.1f})"

    return f"| {level:<7} | {total_reqs:<10} | {count_2xx:<9} | {goodput_str:<17} | {shed_str:<9} | {err_str:<8} | {c429_409:<7} | {p50_2xx_str:<23} | {p95_2xx_str:<23} | {p99_2xx_str:<23} | {p50_all_str:<27} |"

def run_sweep(
    label: str,
    levels: List[int] = CONCURRENCY_LEVELS,
    duration: int = 30,
    repeats: int = 3,
    variants: List[str] = ["a", "b"],
    port: int = 8142,
    output_path: str = None
):
    header = """=================================================================================================================================================================================================================
Clients | Total Reqs | 2xx Count | Goodput (2xx/s)   | Shed 503% | Err 599% | 429/409 | 2xx p50 (ms)            | 2xx p95 (ms)            | 2xx p99 (ms)            | All p50 (incl. fast 503s)   
-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------"""
    footer = """================================================================================================================================================================================================================="""

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
