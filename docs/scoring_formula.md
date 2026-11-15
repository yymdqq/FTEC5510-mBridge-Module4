# Module 4 — scoring formula, parameters and score detail

Hand-over document for **Module 1** (rules/interface spec) and **Module 6** (results
and figures). Everything below is implemented in `m4rank/scoring.py` and
`m4rank/params.py` and is reproduced by `python run_module4.py demo`.

---

## 1. Formula

For each queued payment *i* at decision time *t*:

```
score_i = w_P · P_i + w_D · D_i + w_A · A_i − w_L · L_i
```

with the weights summing to 1 in the baseline (0.45 + 0.40 + 0.15 + 0.00). The
funding-demand term is a **penalty** (minus sign), so a larger funding demand lowers
the score, which is the mechanism proposal §4.2.1 introduces to test "small payments
first" behaviour.

### 1.1 Priority component `P`

```
P_i = priority_points[priority_i] / max(priority_points)
```

`URGENT → 1.000`, `HIGH → 0.667`, `NORMAL → 0.333` with the configured 3/2/1 points.
Dividing by the maximum puts `P` on the same [0, 1] scale as the other components.
Using a ratio (not `points/max·100` or a raw 3/2/1) keeps the component bounded even
if the group later changes the point values.

### 1.2 Deadline component `D`

```
slack_i    = deadline_time_i − t − expected_confirmation_delay − deadline_guard
D_i        = 1 − min(1, max(0, slack_i) / deadline_normalizer)        # linear (default)
D_i        = min(1, exp(−slack_i / deadline_normalizer))              # exponential
```

* `slack ≤ 0` ⇒ `D = 1.0` (the payment is already late or cannot confirm in time).
* `D` is **non-increasing in slack**: a smaller remaining time can never produce a
  lower deadline score. This is the property proposal §4.2.1 asks for and it is
  asserted in `tests/test_module4.py::FormulaTests`.
* The expected confirmation delay is subtracted because a payment submitted exactly at
  its deadline settles *after* the deadline; Module 3's 10 s baseline is read from
  `config.engine_parameters.payment_confirmation_delay_sec`.
* `deadline_normalizer_sec = 7200` means a payment more than two hours from its
  deadline contributes `D ≈ 0`. The raw slack is never used as a positive score.

### 1.3 Aging component `A`

```
waiting_i = t − arrival_time_i
A_i       = min(1, max(0, waiting_i) / aging_normalizer)              # linear (default)
A_i       = 1 − exp(−waiting_i / aging_normalizer)                    # exponential
```

`A` is **non-decreasing in waiting time**, so an ordinary payment climbs the queue the
longer it waits. The linear form reaches 1.0 after `aging_normalizer_sec` (7200 s);
the exponential form never reaches 1.0 and discriminates better among short waits.

### 1.4 Funding-demand component `L`

```
L_i = amount_rmb_i / funding_demand_reference_rmb          # ratio (default)
L_i = (amount_i − min amount in queue) / (max − min)       # queue_range
```

The reference is `config.data_generation.payment_amount_max_rmb` when present, so the
scale is **identical at every decision event and in every strategy** — as proposal
§4.2.1 requires ("the funding-demand factor uses the same amount scale throughout each
comparison"). Only when no reference exists does the code fall back to the largest
amount in the current queue, and that fallback is flagged in `parameters.warnings`.

---

## 2. Parameter table

| Key in `config.ranking_parameters` | Type | Default | Unit | Effect |
|---|---|---|---|---|
| `priority_points` | object | `{URGENT:3, HIGH:2, NORMAL:1}` | points | numerator of `P` |
| `weight_priority` | float ≥ 0 | 0.45 | ratio | `w_P` |
| `weight_deadline` | float ≥ 0 | 0.40 | ratio | `w_D` |
| `weight_aging` | float ≥ 0 | 0.15 | ratio | `w_A` |
| `weight_funding` | float ≥ 0 | 0.00 | ratio | `w_L`; 0 = factor off |
| `deadline_normalizer_sec` | float > 0 | 7200 | s | scale of `D` |
| `aging_normalizer_sec` | float > 0 | 7200 | s | scale of `A` |
| `deadline_mode` | enum | `linear` | — | `linear` / `exponential` |
| `aging_mode` | enum | `linear` | — | `linear` / `exponential` |
| `deadline_guard_sec` | float ≥ 0 | 0 | s | extra safety margin in the slack |
| `funding_demand_mode` | enum | `ratio` | — | `ratio` / `queue_range` / `off` |
| `funding_demand_reference_rmb` | float > 0 | *unset* | RMB | scale of `L` |
| `expected_confirmation_delay_sec` | float ≥ 0 | 10 | s | subtracted from the slack |
| `score_round_dp` | int 0–15 | 9 | decimals | score equality / tie definition |

Validation is strict where a mistake would silently change the ordering:

* a negative weight, a zero-total weight set, or a non-positive normaliser is an error;
* an unknown priority name or a missing `URGENT`/`HIGH`/`NORMAL` point is an error;
* an unknown key inside `ranking_parameters` (e.g. `weight_agings`) is an error in
  `strict=True` (CLI, tests) and a recorded warning inside the engine;
* `weight_funding > 0` together with `funding_demand_mode = "off"` is an error rather
  than a silently ignored weight.

---

## 3. Ordering and ties

```
sort key = ( −round(score, score_round_dp),  arrival_time,  payment_id )
```

Score first (highest), then arrival time (earliest), then `payment_id` (ascending),
exactly as proposal §4.2.2 states. Comparing rounded scores means an exact tie is
detected reliably; two payments with mathematically equal scores cannot be separated
by a 1e-16 floating-point difference.

Temporarily unfundable instructions are **ranked normally**, flagged with
`fundable_now` / `funding_gap_rmb`, and never removed. Skipping them is the engine's
job (S1–S4); `select_payable(order, queue, available_rmb)` previews that pass as a
pure function and reports `first_blocked` and `head_of_line_blocked`.

---

## 4. Worked example (audit trail)

`P000003`, HIGH, 75 000 RMB, deadline 2 040 s, arrival 240 s, decision time 1 800 s:

```
slack   = 2040 − 1800 − 10 = 230 s
D       = 1 − min(1, 230/7200)          = 0.968056
P       = 2.0 / 3.0                     = 0.666667
waiting = 1800 − 240 = 1560 s
A       = min(1, 1560/7200)             = 0.216667
L       = 75000 / 2000000               = 0.037500

score   = 0.45·0.666667 + 0.40·0.968056 + 0.15·0.216667 − 0.00·0.0375
        = 0.300000      + 0.387222      + 0.032500      − 0.000000
        = 0.719722
```

The same calculation is produced for every payment and every decision event:

* row of `result["detail"]` — all terms, including `explanation`
  (`P=0.667x0.45=0.3000 + D=0.968x0.40=0.3872 + A=0.217x0.15=0.0325 - L=0.037x0.00=0.0000 => 0.7197`);
* `result["scores"][payment_id]` — the compact contract entry;
* `run_module4.py rank --csv detail.csv` — the full table, ready to paste into the report.

### CSV columns

`rank, payment_id, priority, amount_rmb, arrival_time, deadline_time, waiting_sec,
slack_sec, p_component, d_component, a_component, l_component, w_p, w_d, w_a, w_l,
score, fundable_now, funding_gap_rmb, overdue, at_risk, explanation`

### Mapping to proposal §4.2.1

| Proposal column | Implementation | Note |
|---|---|---|
| `P` — URGENT 3 / HIGH 2 / NORMAL 1 | `priority_points` | normalised by the maximum |
| `D` — normalised deadline urgency | `deadline_component` | slack after time and confirmation delay |
| `A` — waiting time / common time scale | `aging_component` | `aging_normalizer_sec` is that scale |
| `L` — funding demand | `funding_component` | penalty term, weight 0 in the initial experiment |
| `w` — preset weights in the config | `weight_*` | validated, echoed in `result["parameters"]` |
