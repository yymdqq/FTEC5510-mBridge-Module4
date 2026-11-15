# Module 4 — Dynamic Payment Ranking (S2 / S4 ordering)

FTEC5510 Advanced Financial Infrastructure · Group 12 ·
*Liquidity-Aware HKD/RMB Cross-Border Settlement: An mBridge-Based Simulation*

This module implements the scheduling half of the proposed liquidity-aware settlement
engine: it scores every queued RMB payment on **business priority**, **deadline
urgency**, **aging**, and (optionally) **funding demand**, and returns a deterministic
settlement order. That order turns skippable FIFO (S1) into dynamic scheduling (S2),
and is reused unchanged by the combined policy (S4).

Python **standard library only** — no third-party packages.

---

## 1. Quick start

```bash
cd 第四模块

# 1. hand-checkable ranking cases (score table + before/after + variants)
python run_module4.py demo

# 2. rank one decision event, with a CSV / JSON audit trail
python run_module4.py rank --case examples/demo_case.json --csv out/detail.csv --json out/rank.json

# 3. sensitivity of the ranking to a weight
python run_module4.py sweep --key weight_aging --values 0,0.15,0.3,0.6,1.0

# 4. run Module 3 S0-S4 with this ranking wired in, then compare S2 against S1
python run_module4.py integrate --module3 ../module3 \
    --dataset ../module3/fixtures/pilot/low_rmb_liquidity/seed_1001

# 5. the unit test suite
python run_module4.py selftest
# or: python -m unittest discover -s tests -t . -v
```

On Windows use the same commands; `python` means the interpreter you run the other
modules with (Python 3.10+; only `dataclasses`/`typing` syntax from 3.10 is used).

---

## 2. What is delivered

| Deliverable (分工.docx, module 4) | Where it lives |
|---|---|
| `rank_payments` and a call example | `module4_rank.py`, `m4rank/ranking.py`, §5 below |
| Scoring formula, parameter table and score detail | `docs/scoring_formula.md`; the `rank --csv` detail table |
| Small before/after sorting cases | `run_module4.py demo`, `examples/demo_case.json` |
| S2 / S4 ranking implementation notes | `docs/s2_s4_integration.md` |
| Check whether ordinary / large payments are hurt | `python run_module4.py impact --run <dir> --baseline <dir>` |
| 30-seed check against the proposal's expected findings | `python analysis/check_alignment.py paired`, [`docs/proposal_alignment.md`](docs/proposal_alignment.md) |

Verification evidence (commands + real console output) is in
[`docs/verification.md`](docs/verification.md); whether the results match the
proposal's §5.1 expectations is answered in
[`docs/proposal_alignment.md`](docs/proposal_alignment.md).

```
/
├── run_module4.py            command-line entry point (demo / rank / sweep / impact / integrate)
├── module4_rank.py           the file Module 3 imports (exposes rank_payments)
├── m4rank/
│   ├── params.py             resolve + validate config.ranking_parameters
│   ├── scoring.py            the four score components P, D, A, L
│   ├── ranking.py            rank_payments, tie-breaking, select_payable
│   ├── report.py             score tables, before/after table, detail CSV
│   ├── cases.py              load the frozen decision-event cases
│   ├── sensitivity.py        weight / normaliser sweep
│   └── impact.py             priority and large-payment diagnostic
├── analysis/check_alignment.py   paired 30-seed test of the proposal's expectations
├── examples/demo_case.json   11 queued instructions at t = 1800 s
├── tests/test_module4.py     59 tests
└── docs/                     formula, S2/S4 notes, Module 3 hand-over, verification,
                              proposal_alignment (does the result match the proposal?)
```

---

## 3. The score

```
score_i = w_P·P_i + w_D·D_i + w_A·A_i − w_L·L_i
```

| Component | Definition | Range | Meaning |
|---|---|---|---|
| `P` | `priority_points[priority] / max(priority_points)` | (0, 1] | URGENT 1.000, HIGH 0.667, NORMAL 0.333 |
| `D` | `1 − min(1, slack / deadline_normalizer)` (linear) or `exp(−slack / deadline_normalizer)` | [0, 1] | smaller slack ⇒ higher urgency |
| `A` | `min(1, waiting / aging_normalizer)` (linear) or `1 − exp(−waiting / aging_normalizer)` | [0, 1] | longer wait ⇒ higher score |
| `L` | `amount / funding_demand_reference` | [0, 1] | **penalty**: large payments score lower |

where `slack = deadline_time − t − expected_confirmation_delay − deadline_guard` and
`waiting = t − arrival_time`.

Ordering is **score descending**, then **arrival_time ascending**, then
**payment_id ascending** (proposal 4.2.2). Scores are compared after rounding to
`score_round_dp` decimals (default 9), so two mathematically equal scores tie
exactly and the tie-break rules — not floating-point noise — decide the order.

Two properties are enforced by tests, not just by intent:

* **deadline monotonicity** — less remaining time never lowers `D`;
* **aging monotonicity** — a longer wait never lowers `A`;
* **no dropping** — every queued `payment_id` is returned exactly once, including
  instructions that cannot be funded right now. Skipping is an engine action (S1–S4),
  not a ranking action; `select_payable()` previews that skip pass purely.

The function is **pure**: it never locks funds, never changes a balance, never
mutates `queue`/`state`/`config`. Only Module 3 moves money.

### Parameters (all read from `config.json`, nothing hard-coded)

| Key (in `config.ranking_parameters`) | Default | Used by |
|---|---|---|
| `priority_points` | URGENT 3 / HIGH 2 / NORMAL 1 | `P` |
| `weight_priority` | 0.45 | `w_P` |
| `weight_deadline` | 0.40 | `w_D` |
| `weight_aging` | 0.15 | `w_A` |
| `weight_funding` | 0.00 (off in the initial experiment, per proposal 4.2.1) | `w_L` |
| `deadline_normalizer_sec` | 7200 | `D` |
| `aging_normalizer_sec` | 7200 | `A` |

Optional extensions (absent from the Module 2 config, so defaults are used):
`deadline_mode`, `aging_mode`, `deadline_guard_sec`, `funding_demand_mode`,
`funding_demand_reference_rmb`, `score_round_dp`. The resolved values, their source
key and any warning are returned in `result["parameters"]`, so every ordering can be
traced back to one configuration version.

`expected_confirmation_delay_sec` is taken from
`config.engine_parameters.payment_confirmation_delay_sec` (Module 3's 10 s baseline)
so the deadline score already knows a payment submitted at its deadline cannot settle
in time.

---

## 4. Hand-checkable case (`examples/demo_case.json`)

Eleven instructions queued at `t = 1800 s`, RMB available 600 000, default weights:

| # | payment | prio | amount | deadline | wait | slack | P | D | A | score |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | P000001 | URGENT | 100,000 | 660 | 1740 | −1150 | 1.000 | 1.000 | 0.242 | **0.8863** |
| 2 | P000004 | URGENT | 460,000 | 1230 | 1470 | −580 | 1.000 | 1.000 | 0.204 | 0.8806 |
| 3 | P000003 | HIGH | 75,000 | 2040 | 1560 | 230 | 0.667 | 0.968 | 0.217 | 0.7197 |
| 4 | P000007 | HIGH | 410,000 | 4200 | 480 | 2390 | 0.667 | 0.668 | 0.067 | 0.5772 |
| 5 | P000008 | HIGH | 210,000 | 5160 | 300 | 3350 | 0.667 | 0.535 | 0.042 | 0.5201 |
| 6 | P000002 | NORMAL | 250,000 | 4950 | 1650 | 3140 | 0.333 | 0.564 | 0.229 | 0.4099 |
| 7 | P000005 | NORMAL | 95,000 | 6540 | 1260 | 4730 | 0.333 | 0.343 | 0.175 | 0.3135 |
| 8 | P000006 | NORMAL | 68,000 | 6900 | 900 | 5090 | 0.333 | 0.293 | 0.125 | 0.2860 |
| 9 | P000010 | NORMAL | 34,000 | 6900 | 60 | 5090 | 0.333 | 0.293 | 0.008 | 0.2685 |
| 10 | P000011 | NORMAL | 34,000 | 6900 | 60 | 5090 | 0.333 | 0.293 | 0.008 | 0.2685 |
| 11 | P000009 | NORMAL | 120,000 | 8100 | 240 | 6290 | 0.333 | 0.126 | 0.033 | 0.2056 |

* `P000010` and `P000011` have **identical** scores, arrival times and amounts → the
  `payment_id` tie-break puts `P000010` first.
* 9 of 11 positions change against arrival order: `P000004` (URGENT, overdue) rises
  4→2, `P000007` 7→4, `P000008` 8→5; the two large NORMAL payments fall.
* RMB 600 000 is enough for **3** instructions in score order
  (`P000001, P000004, P000010` — 594 000) but **5** in arrival order
  (`P000001, P000002, P000003, P000005, P000006` — 588 000). Dynamic scheduling
  protects the urgent obligations and spends the scarce RMB on them; with
  `weight_funding = 1.0` the 460 000 instruction drops to rank 3 and the
  near-deadline `P000003` leads instead.

---

## 5. Interface with Module 3 (the only integration point)

```python
from module4_rank import rank_payments        # 第四模块 on PYTHONPATH

ranked = rank_payments(queue, state, config)
ranked["order"]     # ['P000001', 'P000004', ...]        contract
ranked["scores"]    # {'P000001': {'score': 0.88625, ...}} contract
ranked["detail"]    # full per-payment audit rows
ranked["parameters"]  # resolved weights, normalisers, sources, warnings
```

* `queue` — the engine's `_payment_view` list: `payment_id`, `arrival_time`,
  `amount_rmb` (Decimal), `priority`, `deadline_time`, `submit_time`, `waiting_time`.
* `state` — the engine's `_state_view`: at least `t` and `rmb_available`.
* `config` — the loaded `config.json` (Module 2 contract v1.0.0).

Wiring options (both verified):

```bash
# A. recommended: put this folder on PYTHONPATH, copy nothing
set PYTHONPATH=C:\path\to\module4
python ..\module3\run_engine.py --dataset <dataset> --strategy S2

# B. drop module4_rank.py + m4rank/ into module3/m3engine/ and set
set M3_MODULE4_MODULE=m3engine.module4_rank
```

`run_module4.py integrate` does option A automatically, checks
`run_summary.json → using_fallback_module4 == false`, and prints the S2-vs-S1
diagnostic.

---

## 6. Verification status

| Check | Result |
|---|---|
| Unit + contract tests | **59/59 pass** in ~0.3 s (`selftest`) |
| Module 3 picks up the real function | `using_fallback_module4 = false` for S2 **and** S4 |
| Determinism (same input → same order) | asserted over repeated calls |
| Tie-breaking (score → arrival → id) | asserted on an exact tie and on a synthetic pair |
| Unfundable instructions | never dropped; `select_payable` reports the blocked set |
| Purity | `queue`, `state`, `config` byte-identical before/after the call |
| Monotonicity of `D` and `A` | asserted over a slack/waiting sweep |
| End-to-end on `pilot/low_rmb_liquidity/seed_1001` | S2 vs S1: URGENT mean delay 134.5 s → 97.5 s, HIGH 68.8 s → 56.3 s, NORMAL p95 262.5 s → 302.0 s, FX trades 64 → 62 |
| Formal set, 7 scenarios × 30 seeds, paired + 95% CI | URGENT mean **and** P95 delay lower in **7/7** scenarios (CI excludes 0); NORMAL completion **lower** in `payment_surge` (−4.8 pp) and `large_payments` (−6.2 pp) — see [`docs/proposal_alignment.md`](docs/proposal_alignment.md) |

The single-seed row above is a demonstration, not evidence: it suggested a NORMAL-P95
regression that the 30-seed paired test does **not** confirm (NORMAL P95 is −0.5 s in
`baseline` and +7.1 s in `low_rmb_liquidity`, neither significant). The real, robust
fairness cost is a **completion-rate** effect in the two heaviest stress scenarios, and
it is larger than one seed could show. Cite `docs/proposal_alignment.md`, not §6, in
the report. Module 6 owns the official metric set and the confidence intervals.

---

## 7. Known limitations

1. **S3/S4 still run Module 5's fallback** (immediate FX top-up) because Module 5 has
   not been delivered yet. S4 currently differs from S2 only through that fallback;
   S3/S4 numbers must not go into the report.
2. `weight_funding` is **0** in the initial experiment, as the proposal specifies.
   The `L` component is computed and reported but does not influence the default
   order; enabling it is a separate sensitivity run (`--set weight_funding=1.0`).
3. With the default weights, `w_A · A` is small (max 0.15) against the 0.30 gap
   between URGENT and NORMAL `w_P · P`, so aging can never let a NORMAL payment
   overtake an URGENT one. That is intended: aging breaks ties *within* a priority
   class at the default weights, and starts reordering across classes only when
   `weight_aging` is raised (see `sweep`).
4. Scores are floating point but compared at 1e-9 precision; instructions whose
   scores differ by less than that are treated as tied and resolved by
   `arrival_time` / `payment_id`. Sub-second or sub-1e-9 discrimination is out of
   scope for the integer-second Module 2 contract.
5. The module ranks one decision event at a time. It keeps no memory between calls,
   so "has this payment already been skipped twice?" style learning is not modelled.
6. **Dynamic scheduling reallocates service, it does not create it.** Over the formal
   30-seed set S2 raises URGENT/HIGH completion substantially in the two heaviest
   stress scenarios but *lowers* NORMAL completion there (−4.8 pp in `payment_surge`,
   −6.2 pp in `large_payments`) and raises the NORMAL overdue rate (+3.4 pp / +5.9 pp).
   Total completion still rises. Raising `weight_aging` does not repair this; setting
   `weight_funding > 0` partly does. Details and numbers:
   [`docs/proposal_alignment.md`](docs/proposal_alignment.md).
