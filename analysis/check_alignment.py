#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Does the simulation actually deliver what the proposal expects?

Two commands, both read-only:

    python analysis/check_alignment.py paired
        Runs S0/S1/S2 on the formal fixture set (7 scenarios x 30 seeds) and
        reports per-seed paired differences S2-S1 and S0-S1 with 95% CIs, plus
        per-priority completion (the proposal warns that better urgent service
        must not be sold as protection for all payments).

    python analysis/check_alignment.py weights
        Re-runs S2 under several score-weight settings on the two scenarios
        where the default weights hurt ordinary payments, to check whether the
        scoring weights can fix it (proposal 4.4.1 sensitivity requirement).

S3/S4 are excluded on purpose: Module 5 is still a fallback, so their numbers
say nothing about the proposal's policies. Nothing is written to disk; the
summarised conclusions live in docs/proposal_alignment.md.

Paths are auto-detected; override with --module3 / --module4.
"""

from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT_DIR = HERE.parent

SCENARIOS = ["baseline", "low_rmb_liquidity", "payment_surge", "large_payments",
             "tight_deadlines", "delayed_inflows", "fx_capacity_shock"]
SEEDS = list(range(20001, 20031))
STRATS = ("S0", "S1", "S2")
PRIORITIES = ("URGENT", "HIGH", "NORMAL")

#: label, weight_priority, weight_deadline, weight_aging, weight_funding
WEIGHT_VARIANTS = [
    ("default   .45/.40/.15  wL=0", 0.45, 0.40, 0.15, 0.0),
    ("aging+    .40/.35/.25  wL=0", 0.40, 0.35, 0.25, 0.0),
    ("aging++   .35/.30/.35  wL=0", 0.35, 0.30, 0.35, 0.0),
    ("aging+++  .30/.25/.45  wL=0", 0.30, 0.25, 0.45, 0.0),
    ("funding   .45/.40/.15  wL=1", 0.45, 0.40, 0.15, 1.0),
    ("mixed     .35/.30/.35  wL=1", 0.35, 0.30, 0.35, 1.0),
]


# ----------------------------------------------------------------------
# statistics helpers
# ----------------------------------------------------------------------

def pct(values, q):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def ci95(diffs):
    n = len(diffs)
    mean = sum(diffs) / n
    if n < 2:
        return mean, mean, mean
    half = 1.96 * statistics.stdev(diffs) / math.sqrt(n)
    return mean, mean - half, mean + half


def opt_int(value):
    return None if value in (None, "") else int(value)


def table(headers, rows, aligns):
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))

    def line(cells):
        parts = []
        for index, cell in enumerate(cells):
            text = str(cell)
            align = aligns[index] if index < len(aligns) else "l"
            parts.append(text.rjust(widths[index]) if align == "r"
                         else text.center(widths[index]) if align == "c"
                         else text.ljust(widths[index]))
        return "  ".join(parts).rstrip()

    return "\n".join([line(headers), "  ".join("-" * w for w in widths)]
                     + [line(row) for row in rows])


# ----------------------------------------------------------------------
# measurement
# ----------------------------------------------------------------------

def measure(result):
    obs = int(result.summary["observation_end_sec"])
    rows = result.payments
    out = {}

    def block(subset):
        settled = [r for r in subset if r["final_status"] == "SETTLED"]
        delays = [opt_int(r["settle_time"]) - r["arrival_time"] for r in settled]
        due = [r for r in subset if r["deadline_time"] <= obs]
        overdue = [r for r in due
                   if r["final_status"] != "SETTLED"
                   or opt_int(r["settle_time"]) > r["deadline_time"]]
        # waiting time on submitted payments only: not censored by outstanding ones
        waits = [opt_int(r["submit_time"]) - r["arrival_time"] for r in subset
                 if opt_int(r["submit_time"]) is not None]
        return {
            "n": len(subset),
            "settled": len(settled),
            "completion": len(settled) / len(subset) if subset else 0.0,
            "outstanding": len(subset) - len(settled),
            "mean_delay": sum(delays) / len(delays) if delays else None,
            "p95_delay": pct(delays, 0.95),
            "due": len(due),
            "overdue": len(overdue),
            "overdue_rate": len(overdue) / len(due) if due else 0.0,
            "mean_wait_submitted": sum(waits) / len(waits) if waits else None,
        }

    out["ALL"] = block(rows)
    for label in PRIORITIES:
        out[label] = block([r for r in rows if r["priority"] == label])
    out["fx_count"] = int(result.summary["fx_initiated"])
    out["fx_cost"] = float(result.summary["fx_cost_rmb"])
    return out


def resolve(metrics, path):
    head, _, tail = path.partition(".")
    value = metrics.get(head)
    return value.get(tail) if tail and isinstance(value, dict) else value


# ----------------------------------------------------------------------
# command: paired
# ----------------------------------------------------------------------

def run_paired(load_dataset, run_dataset, fixtures):
    print(f"formal fixture set: {fixtures}")
    print(f"running {len(SCENARIOS)} scenarios x {len(SEEDS)} seeds x {len(STRATS)} strategies")
    data = {}
    for scenario in SCENARIOS:
        per_seed = {}
        for seed in SEEDS:
            dataset = load_dataset(fixtures / scenario / f"seed_{seed}")
            per_seed[seed] = {s: measure(run_dataset(dataset, s)) for s in STRATS}
        data[scenario] = per_seed
    print(f"completed {sum(len(r) * len(STRATS) for r in data.values())} simulation runs\n")

    def paired(scenario, path, a="S2", b="S1"):
        diffs = []
        for runs in data[scenario].values():
            av, bv = resolve(runs[a], path), resolve(runs[b], path)
            if av is not None and bv is not None:
                diffs.append(av - bv)
        return diffs or None

    # -- per-priority completion ---------------------------------------
    print("=" * 100)
    print("TABLE A  completion rate by priority, S1 -> S2 (mean over 30 seeds)")
    print("=" * 100)
    rows = []
    for scenario in SCENARIOS:
        row = [scenario]
        for label in PRIORITIES:
            c1 = statistics.mean(data[scenario][s]["S1"][label]["completion"]
                                 for s in data[scenario])
            c2 = statistics.mean(data[scenario][s]["S2"][label]["completion"]
                                 for s in data[scenario])
            d = paired(scenario, f"{label}.completion")
            mean, low, high = ci95(d) if d else (0, 0, 0)
            star = "*" if (low > 0 or high < 0) else " "
            row.append(f"{c1:.3f}->{c2:.3f}{star}")
        rows.append(row)
    print(table(["scenario", "URGENT", "HIGH", "NORMAL"], rows, "lccc"))
    print("  * = 95% CI of the paired difference excludes 0")

    # -- outstanding counts ---------------------------------------------
    print()
    print("=" * 100)
    print("TABLE B  outstanding payments at the observation endpoint")
    print("=" * 100)
    rows = []
    for scenario in SCENARIOS:
        def mean_out(strategy, label):
            return statistics.mean(
                data[scenario][s][strategy][label]["outstanding"] for s in data[scenario])
        rows.append([scenario,
                     f"{mean_out('S1', 'ALL'):.1f}", f"{mean_out('S2', 'ALL'):.1f}",
                     f"{mean_out('S1', 'NORMAL'):.1f} -> {mean_out('S2', 'NORMAL'):.1f}"])
    print(table(["scenario", "ALL S1", "ALL S2", "NORMAL S1 -> S2"], rows, "lrrl"))

    # -- main paired table ----------------------------------------------
    print()
    print("=" * 100)
    print("TABLE C  S2 vs S1, paired by seed, mean difference [95% CI]")
    print("=" * 100)
    metrics = [
        ("URGENT mean delay (s)", "URGENT.mean_delay", False, 1),
        ("URGENT P95 delay (s)", "URGENT.p95_delay", False, 1),
        ("HIGH mean delay (s)", "HIGH.mean_delay", False, 1),
        ("NORMAL mean delay (s)", "NORMAL.mean_delay", False, 1),
        ("NORMAL P95 delay (s)", "NORMAL.p95_delay", False, 1),
        ("ALL mean delay (s)", "ALL.mean_delay", False, 1),
        ("ALL P95 delay (s)", "ALL.p95_delay", False, 1),
        ("ALL completion rate (pp)", "ALL.completion", True, 100),
        ("URGENT completion (pp)", "URGENT.completion", True, 100),
        ("NORMAL completion (pp)", "NORMAL.completion", True, 100),
        ("URGENT overdue rate (pp)", "URGENT.overdue_rate", False, 100),
        ("NORMAL overdue rate (pp)", "NORMAL.overdue_rate", False, 100),
        ("FX trades", "fx_count", False, 1),
        ("FX cost (RMB)", "fx_cost", False, 1),
    ]
    for label, path, higher_is_better, scale in metrics:
        rows = []
        for scenario in SCENARIOS:
            diffs = paired(scenario, path)
            if not diffs:
                rows.append([scenario, "-", "-", "-"])
                continue
            mean, low, high = ci95(diffs)
            if scale == 100:
                cell, ci = f"{mean * 100:+.2f}pp", f"[{low * 100:+.2f}, {high * 100:+.2f}]pp"
            else:
                cell = f"{mean:+.2f}" if abs(mean) < 10 else f"{mean:+.1f}"
                ci = (f"[{low:+.2f}, {high:+.2f}]" if abs(low) < 10
                      else f"[{low:+.1f}, {high:+.1f}]")
            better = (mean > 0) if higher_is_better else (mean < 0)
            rows.append([scenario, cell + ("*" if (low > 0 or high < 0) else " "), ci,
                         "S2 better" if better else "S1 better" if mean != 0 else "equal"])
        print(f"\n-- {label} --")
        print(table(["scenario", "S2-S1", "95% CI", "direction"], rows, "lrrl"))

    # -- S0 vs S1 -------------------------------------------------------
    print()
    print("=" * 100)
    print("TABLE D  S0 vs S1 (head-of-line blocking), paired by seed")
    print("=" * 100)
    rows = []
    for scenario in SCENARIOS:
        row = [scenario]
        for path, scale in (("ALL.mean_delay", 1), ("ALL.completion", 100),
                            ("fx_count", 1), ("fx_cost", 1)):
            diffs = paired(scenario, path, "S0", "S1")
            if not diffs:
                row.append("-")
                continue
            mean, low, high = ci95(diffs)
            star = "*" if (low > 0 or high < 0) else " "
            row.append(f"{mean * 100:+.2f}pp{star}" if scale == 100
                       else f"{mean:+.1f}{star}")
        rows.append(row)
    print(table(["scenario", "delay S0-S1", "completion S0-S1", "FX S0-S1", "FX cost S0-S1"],
                rows, "lrrrr"))
    print("  positive = S1 better = bypassing head-of-line blocking pays off")

    # -- service targets ------------------------------------------------
    print()
    print("=" * 100)
    print("TABLE E  are the service targets binding? (0.95 completion / 3600s P95 / 5% overdue)")
    print("=" * 100)
    rows = []
    for scenario in SCENARIOS:
        comps, overdue, p95s = [], [], []
        for strategy in STRATS:
            comps.append(statistics.mean(data[scenario][s][strategy]["ALL"]["completion"]
                                         for s in data[scenario]))
            overdue.append(statistics.mean(data[scenario][s][strategy]["ALL"]["overdue_rate"]
                                           for s in data[scenario]))
            p95s.append(statistics.mean(data[scenario][s][strategy]["ALL"]["p95_delay"]
                                        for s in data[scenario]))
        met = max(comps) >= 0.95 and min(p95s) <= 3600 and min(overdue) <= 0.05
        rows.append([scenario, f"{min(comps):.3f}-{max(comps):.3f}",
                     f"{min(overdue):.3f}-{max(overdue):.3f}",
                     f"{min(p95s):.0f}-{max(p95s):.0f}", "yes" if met else "NO"])
    print(table(["scenario", "completion", "overdue", "P95 delay", "targets met"],
                rows, "lrrrc"))
    return 0


# ----------------------------------------------------------------------
# command: weights
# ----------------------------------------------------------------------

def run_weights(load_dataset, run_dataset, fixtures, scenarios):
    for scenario in scenarios:
        print("=" * 108)
        print(f"scenario: {scenario}   (30 seeds, S2 under different score weights)")
        print("=" * 108)
        rows = []
        for label, wp, wd, wa, wl in WEIGHT_VARIANTS:
            buckets = {key: [] for key in
                       ("all", "urgent", "high", "normal", "normal_od", "urgent_delay", "fx")}
            for seed in SEEDS:
                dataset = load_dataset(fixtures / scenario / f"seed_{seed}")
                ranking = dataset.config.setdefault("ranking_parameters", {})
                ranking["weight_priority"] = wp
                ranking["weight_deadline"] = wd
                ranking["weight_aging"] = wa
                ranking["weight_funding"] = wl
                m = measure(run_dataset(dataset, "S2"))
                buckets["all"].append(m["ALL"]["completion"])
                buckets["urgent"].append(m["URGENT"]["completion"])
                buckets["high"].append(m["HIGH"]["completion"])
                buckets["normal"].append(m["NORMAL"]["completion"])
                buckets["normal_od"].append(m["NORMAL"]["overdue_rate"])
                buckets["urgent_delay"].append(m["URGENT"]["mean_delay"])
                buckets["fx"].append(m["fx_count"])
            rows.append([label,
                         f"{statistics.mean(buckets['all']):.3f}",
                         f"{statistics.mean(buckets['urgent']):.3f}",
                         f"{statistics.mean(buckets['high']):.3f}",
                         f"{statistics.mean(buckets['normal']):.3f}",
                         f"{statistics.mean(buckets['normal_od']) * 100:.2f}%",
                         f"{statistics.mean(buckets['urgent_delay']):.0f}",
                         f"{statistics.mean(buckets['fx']):.1f}"])
        print(table(["weights", "ALL compl", "URGENT", "HIGH", "NORMAL",
                     "NORMAL overdue", "URGENT delay", "FX"], rows, "lrrrrrrr"))
        print()

    print("=" * 108)
    print("reference: S1 (skippable FIFO) on the same 30 seeds, unmodified config")
    print("=" * 108)
    rows = []
    for scenario in scenarios:
        measures = [measure(run_dataset(load_dataset(
            fixtures / scenario / f"seed_{seed}"), "S1")) for seed in SEEDS]
        rows.append([
            scenario,
            f"{statistics.mean(m['ALL']['completion'] for m in measures):.3f}",
            f"{statistics.mean(m['URGENT']['completion'] for m in measures):.3f}",
            f"{statistics.mean(m['HIGH']['completion'] for m in measures):.3f}",
            f"{statistics.mean(m['NORMAL']['completion'] for m in measures):.3f}",
            f"{statistics.mean(m['NORMAL']['overdue_rate'] for m in measures) * 100:.2f}%",
            f"{statistics.mean(m['URGENT']['mean_delay'] for m in measures):.0f}",
            f"{statistics.mean(m['fx_count'] for m in measures):.1f}",
        ])
    print(table(["scenario", "ALL compl", "URGENT", "HIGH", "NORMAL",
                 "NORMAL overdue", "URGENT delay", "FX"], rows, "lrrrrrrr"))
    return 0


# ----------------------------------------------------------------------
# path discovery
# ----------------------------------------------------------------------

def locate(explicit, candidates, marker):
    options = [Path(explicit)] if explicit else []
    options += [Path(c) for c in candidates]
    for option in options:
        if (option / marker).exists():
            return option.resolve()
    raise SystemExit(f"not found: {marker} (searched {[str(o) for o in options]})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("paired", "weights"))
    parser.add_argument("--module3", default=None)
    parser.add_argument("--module4", default=None)
    parser.add_argument("--scenarios", default="payment_surge,large_payments",
                        help="for 'weights': comma separated scenario ids")
    args = parser.parse_args(argv)

    module3 = locate(args.module3,
                     [ROOT_DIR.parent / "第三模块" / "module3",
                      ROOT_DIR.parent / "module3",
                      ROOT_DIR / "module3"],
                     Path("m3engine") / "__init__.py")
    module4 = locate(args.module4, [ROOT_DIR], Path("module4_rank.py"))

    sys.path.insert(0, str(module4))
    sys.path.insert(0, str(module3))
    os.environ["M3_MODULE4_MODULE"] = "module4_rank"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    from m3engine import load_dataset, run_dataset  # noqa: PLC0415

    fixtures = module3 / "fixtures" / "formal"
    if not fixtures.is_dir():
        raise SystemExit(f"formal fixture set not found: {fixtures}")
    print(f"module3 : {module3}")
    print(f"module4 : {module4}\n")

    if args.command == "paired":
        return run_paired(load_dataset, run_dataset, fixtures)
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    return run_weights(load_dataset, run_dataset, fixtures, scenarios)


if __name__ == "__main__":
    raise SystemExit(main())
