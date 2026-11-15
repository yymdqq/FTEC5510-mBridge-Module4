#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module 4 command-line entry point.

    python run_module4.py demo                       # hand-checkable S2 ranking cases
    python run_module4.py rank  --case <case.json>    # one decision event, full detail
    python run_module4.py sweep --key weight_aging --values 0,0.15,0.4,0.8
    python run_module4.py impact --run <m3 out dir> [--baseline <m3 out dir>]
    python run_module4.py integrate --module3 <path to module3 folder> [--dataset <dir>]
    python run_module4.py selftest                    # run the unit test suite

Everything prints ASCII only, so it works in a Chinese or an English console.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from m4rank import (DEFAULT_CASE_PATH, SWEEPABLE, before_after_table, case_config,  # noqa: E402
                    case_queue, case_state, compare_orders, compare_runs, format_table,
                    group_outcomes, load_case, load_run, order_table, parse_overrides,
                    rank_payments, rank_with_ranks, resolve_params, select_payable,
                    sweep, sweep_report, write_detail_csv)

STRATEGIES = ("S0", "S1", "S2", "S3", "S4")
DEFAULT_SWEEP_VALUES = "0,0.15,0.3,0.45,0.6,1.0"


# ----------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------

def cmd_demo(args) -> int:
    case = load_case(args.case)
    print("=" * 78)
    print("MODULE 4 - dynamic payment ranking (S2 / S4 ordering)")
    print("=" * 78)
    print(f"case       : {case['case_id']}")
    print(f"description: {case.get('description', '')}")
    print(f"decision t : {case['state']['t']} s")
    print(f"queue      : {len(case['queue'])} instructions")
    print()

    queue = case_queue(case)
    state = case_state(case)
    config = case_config(case)

    arrival_order = [p["payment_id"] for p in sorted(
        queue, key=lambda p: (int(p["arrival_time"]), p["payment_id"]))]
    ranked = rank_with_ranks(queue, state, config)
    params = resolve_params(config, strict=True)

    print("--- 1. scoring parameters actually used -------------------------------")
    print(f"formula      : {params.formula()}")
    print(f"priority pts : {params.points}   (normalised by {params.points_max:g})")
    print(f"normalisers  : deadline {params.deadline_normalizer_sec:g}s, "
          f"aging {params.aging_normalizer_sec:g}s")
    print(f"deadline mode: {params.deadline_mode}   aging mode: {params.aging_mode}")
    print(f"confirmation delay subtracted from slack: "
          f"{params.expected_confirmation_delay_sec:g}s")
    print()

    print("--- 2. score breakdown in rank order ----------------------------------")
    print(order_table(ranked))
    print()

    print("--- 3. arrival order (S1-like) vs dynamic order (S2) ------------------")
    print(before_after_table(compare_orders(arrival_order, ranked["order"]),
                             ranked["scores"]))
    print()

    print("--- 4. temporarily unfundable instructions (skipping, not dropping) ---")
    available = state["rmb_available"]
    for label, order in (("arrival order", arrival_order), ("score order", ranked["order"])):
        preview = select_payable(order, queue, available)
        print(f"{label:<14} available {available} -> payable now: "
              f"{len(preview['payable'])}/{len(order)}  {preview['payable']}")
        print(f"{'':<14} blocked: {len(preview['blocked'])}  "
              f"first blocked = {preview['first_blocked']}  "
              f"head-of-line blocked = {preview['head_of_line_blocked']}")
    print()

    print("--- 5. variant A: funding-demand penalty enabled (weight_funding=1.0) -")
    variant = rank_with_ranks(queue, state, case_config(case, {"weight_funding": 1.0}))
    print(order_table(variant))
    comparison = compare_orders(ranked["order"], variant["order"])
    print(f"changed positions vs default: {comparison['changed']}/{len(comparison['rows'])}")
    print(f"moved up   : {', '.join(comparison['moved_up']) or '-'}")
    print(f"moved down : {', '.join(comparison['moved_down']) or '-'}")
    print()

    print("--- 6. variant B: aging-heavy weights (0.2 / 0.2 / 0.6) ---------------")
    aging_cfg = case_config(case, {"weight_priority": 0.2, "weight_deadline": 0.2,
                                   "weight_aging": 0.6})
    aging = rank_with_ranks(queue, state, aging_cfg)
    print(order_table(aging))
    comparison = compare_orders(ranked["order"], aging["order"])
    print(f"changed positions vs default: {comparison['changed']}/{len(comparison['rows'])}")
    print(f"moved up   : {', '.join(comparison['moved_up']) or '-'}")
    print(f"moved down : {', '.join(comparison['moved_down']) or '-'}")
    print()

    if args.csv:
        out = Path(args.csv)
        for name, result in (("default", ranked), ("funding_penalty", variant),
                             ("aging_heavy", aging)):
            target = write_detail_csv(out / f"score_detail_{name}.csv", result)
            print(f"written: {target}")
    print("=" * 78)
    return 0


def cmd_rank(args) -> int:
    case = load_case(args.case)
    overrides = parse_overrides(args.set)
    config = case_config(case, overrides)
    result = rank_with_ranks(case_queue(case), case_state(case), config)
    params = resolve_params(config, strict=True)

    print(f"case    : {case['case_id']}")
    print(f"formula : {params.formula()}")
    for warning in result["warnings"]:
        print(f"[warning] {warning}")
    print()
    print(order_table(result))
    print()
    print(f"order   : {result['order']}")

    if args.csv:
        print(f"detail  : {write_detail_csv(args.csv, result)}")
    if args.json:
        payload = {
            "case_id": case["case_id"],
            "order": result["order"],
            "scores": result["scores"],
            "detail": result["detail"],
            "decision": result["decision"],
            "parameters": result["parameters"],
            "warnings": result["warnings"],
        }
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"json    : {target}")
    return 0


def cmd_sweep(args) -> int:
    case = load_case(args.case)
    values = [float(value) for value in str(args.values).split(",") if value.strip()]
    print(f"case  : {case['case_id']}")
    print(f"key   : {args.key}")
    print(f"values: {values}")
    print()
    rows = sweep(case, args.key, values)
    print(sweep_report(rows))
    print()
    for row in rows:
        print(f"{args.key} = {row['value']:g}")
        print(f"  order: {row['order']}")
    return 0


def cmd_impact(args) -> int:
    run = load_run(args.run, args.large_payment_rmb)
    print(f"run        : {run['run_id']}  (strategy {run['strategy_id']})")
    print(f"observation: {run['observation_end_sec']} s")
    print(f"large >=   : {run['large_payment_rmb']} RMB")
    print()

    outcomes = group_outcomes(run)
    headers = ["group", "n", "done", "completion", "outstanding", "mean_delay",
               "p95_delay", "mean_wait", "p95_wait", "overdue"]
    rows = [[row["group"], row["n"], row["completed"],
             "-" if row["completion_rate"] is None else f"{row['completion_rate']:.3f}",
             row["outstanding"],
             "-" if row["mean_delay_sec"] is None else f"{row['mean_delay_sec']:.1f}",
             "-" if row["p95_delay_sec"] is None else f"{row['p95_delay_sec']:.1f}",
             "-" if row["mean_submit_wait_sec"] is None else f"{row['mean_submit_wait_sec']:.1f}",
             "-" if row["p95_submit_wait_sec"] is None else f"{row['p95_submit_wait_sec']:.1f}",
             f"{row['overdue']}/{row['due']}"] for row in outcomes]
    print(format_table(headers, rows, "lrrrrrrrrr"))

    if args.baseline:
        baseline = load_run(args.baseline, args.large_payment_rmb)
        print()
        print(f"--- {run['strategy_id']} vs baseline {baseline['strategy_id']} "
              f"({baseline['run_id']}) ---")
        diffs = compare_runs(baseline, run)
        headers = ["group", "n", "done base", "done new", "mean_delay base", "mean_delay new",
                   "p95 base", "p95 new", "overdue base", "overdue new", "verdict"]
        rows = []
        for row in diffs:
            rows.append([
                row["group"], row["n"],
                row["completed_baseline"], row["completed_candidate"],
                _fmt(row["mean_delay_baseline"]), _fmt(row["mean_delay_candidate"]),
                _fmt(row["p95_delay_baseline"]), _fmt(row["p95_delay_candidate"]),
                row["overdue_baseline"], row["overdue_candidate"], row["verdict"],
            ])
        print(format_table(headers, rows, "lrrrrrrrrrl"))
        print()
        print("Reminder: this is a Module 4 diagnostic. Module 6 owns metrics.csv.")
    return 0


def cmd_integrate(args) -> int:
    module3 = _locate_module3(args.module3)
    dataset_dir = Path(args.dataset) if args.dataset else module3 / "fixtures" / "fixed_demo"
    if not dataset_dir.is_dir():
        print(f"[error] dataset directory not found: {dataset_dir}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(module3))
    os.environ["M3_MODULE4_MODULE"] = "module4_rank"
    try:
        from m3engine import load_dataset, run_dataset, write_outputs
    except ImportError as exc:
        print(f"[error] cannot import m3engine from {module3}: {exc}", file=sys.stderr)
        return 1

    dataset = load_dataset(dataset_dir)
    strategies = ([s.strip().upper() for s in args.strategies.split(",") if s.strip()]
                  if args.strategies else list(STRATEGIES))
    out_root = Path(args.out) if args.out else HERE / "outputs" / dataset.dataset_id

    print(f"module3  : {module3}")
    print(f"dataset  : {dataset.dataset_id}  ({len(dataset.payments)} payments, "
          f"{len(dataset.inflows)} inflows)")
    print(f"scenario : {dataset.config.get('scenario_id')}  seed = {dataset.config.get('seed')}")
    print(f"outputs  : {out_root}")
    print()
    header = (f"{'strat':<7}{'settled':>8}{'pending':>8}{'queued':>7}{'FX':>4}"
              f"{'FX cost':>12}  module4     module5")
    print(header)
    print("-" * len(header))

    problems = []
    for strategy in strategies:
        result = run_dataset(dataset, strategy)
        summary = result.summary
        m4 = _module_label(strategy, "module4", summary["using_fallback_module4"])
        m5 = _module_label(strategy, "module5", summary["using_fallback_module5"])
        print(f"{strategy:<7}{summary['settled']:>8}{summary['pending']:>8}"
              f"{summary['queued']:>7}{summary['fx_initiated']:>4}"
              f"{float(summary['fx_cost_rmb']):>12,.2f}  {m4:<11} {m5}")
        target = out_root / result.run_id
        write_outputs(result, target)
        with (target / "run_summary.json").open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, ensure_ascii=False)
        if strategy in ("S2", "S4") and summary["using_fallback_module4"]:
            problems.append(strategy)

    print()
    if problems:
        print(f"[FAIL] {problems} still used the Module 3 fallback ranking: "
              f"module4_rank is not importable from PYTHONPATH={os.environ.get('PYTHONPATH')}")
        return 1
    print("[OK] S2/S4 ran on the real Module 4 ranking function (no fallback).")

    if "S1" in strategies and "S2" in strategies:
        print()
        print("--- Module 4 diagnostic: S2 vs S1 by priority and payment size ---")
        baseline = load_run(out_root / f"{dataset.dataset_id}_S1")
        candidate = load_run(out_root / f"{dataset.dataset_id}_S2")
        diffs = compare_runs(baseline, candidate)
        headers = ["group", "n", "done S1", "done S2", "mean_delay S1", "mean_delay S2",
                   "p95 S1", "p95 S2", "overdue S1", "overdue S2", "verdict"]
        rows = [[row["group"], row["n"], row["completed_baseline"], row["completed_candidate"],
                 _fmt(row["mean_delay_baseline"]), _fmt(row["mean_delay_candidate"]),
                 _fmt(row["p95_delay_baseline"]), _fmt(row["p95_delay_candidate"]),
                 row["overdue_baseline"], row["overdue_candidate"], row["verdict"]]
                for row in diffs]
        print(format_table(headers, rows, "lrrrrrrrrrl"))
        print("Module 6 owns the official metric set; these numbers only sanity-check Module 4.")
    return 0


def cmd_selftest(args) -> int:
    tests = HERE / "tests"
    command = [sys.executable, "-m", "unittest", "discover", "-s", str(tests),
               "-t", str(HERE), "-v"]
    print("$ " + " ".join(command))
    return subprocess.call(command, cwd=str(HERE))


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _fmt(value) -> str:
    return "-" if value is None else f"{value:.1f}"


#: Which strategies actually call Module 4 / Module 5 (proposal table 4.3).
_USES = {
    "module4": ("S2", "S4"),
    "module5": ("S3", "S4"),
}


def _module_label(strategy: str, module: str, used_fallback: bool) -> str:
    if strategy not in _USES[module]:
        return "not used"
    return "FALLBACK" if used_fallback else ("M4 real" if module == "module4" else "M5 real")


def _locate_module3(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates += [
        HERE.parent / "第三模块" / "module3",
        HERE.parent / "module3",
        HERE / "module3",
        HERE.parent.parent / "第三模块" / "module3",
    ]
    for candidate in candidates:
        if (candidate / "m3engine" / "__init__.py").is_file():
            return candidate.resolve()
    raise SystemExit(
        "[error] Module 3 not found. Pass --module3 <folder containing m3engine/>, e.g.\n"
        "        python run_module4.py integrate --module3 "
        "\"C:\\Users\\<you>\\Desktop\\第三模块\\module3\"")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="print the hand-checkable ranking cases")
    demo.add_argument("--case", default=str(DEFAULT_CASE_PATH))
    demo.add_argument("--csv", default=None, metavar="DIR",
                      help="also write score_detail_*.csv into DIR")
    demo.set_defaults(func=cmd_demo)

    rank = sub.add_parser("rank", help="rank one decision event")
    rank.add_argument("--case", default=str(DEFAULT_CASE_PATH))
    rank.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                      help="override a ranking parameter, e.g. --set weight_aging=0.4")
    rank.add_argument("--csv", default=None)
    rank.add_argument("--json", default=None)
    rank.set_defaults(func=cmd_rank)

    sweep_cmd = sub.add_parser("sweep", help="sensitivity sweep of one parameter")
    sweep_cmd.add_argument("--case", default=str(DEFAULT_CASE_PATH))
    sweep_cmd.add_argument("--key", default="weight_aging", choices=list(SWEEPABLE))
    sweep_cmd.add_argument("--values", default=DEFAULT_SWEEP_VALUES)
    sweep_cmd.set_defaults(func=cmd_sweep)

    impact = sub.add_parser("impact", help="priority / large-payment diagnostic")
    impact.add_argument("--run", required=True,
                        help="Module 3 output directory (payment_results.csv)")
    impact.add_argument("--baseline", default=None,
                        help="baseline Module 3 output directory, e.g. the S1 run")
    impact.add_argument("--large-payment-rmb", default=None)
    impact.set_defaults(func=cmd_impact)

    integrate = sub.add_parser("integrate", help="run Module 3 S0-S4 with this ranking")
    integrate.add_argument("--module3", default=None,
                           help="folder that contains m3engine/ (auto-detected if omitted)")
    integrate.add_argument("--dataset", default=None,
                           help="Module 2 dataset directory (default: module3 fixtures/fixed_demo)")
    integrate.add_argument("--strategies", default=None,
                           help="comma separated, e.g. S1,S2")
    integrate.add_argument("--out", default=None)
    integrate.set_defaults(func=cmd_integrate)

    selftest = sub.add_parser("selftest", help="run the unit tests")
    selftest.set_defaults(func=cmd_selftest)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
