# Verification record — Module 4

Every block below is the **actual console output** of the command above it, produced on
Windows with Python 3.12 and the Module 2 config as delivered (weights 0.45 / 0.40 /
0.15, normalisers 7 200 s, priority points 3 / 2 / 1).

Environment used:

```
Python  3.12.14
Module 3 : C:\Users\于沈豪\Desktop\第三模块\module3
Module 4 : C:\Users\于沈豪\Desktop\第四模块
```

---

## 1. Test suite

```bash
cd 第四模块
python -m unittest discover -s tests -t .          # or: python run_module4.py selftest
```

```
...................................................sss.............
----------------------------------------------------------------------
Ran 59 tests in 0.021s

OK (skipped=3)
```

The three skipped tests are the Module 3 integration tests; they run when
`MODULE3_PATH` points at Module 3:

```bash
set MODULE3_PATH=C:\Users\于沈豪\Desktop\第三模块\module3
python -m unittest discover -s tests -t .
```

```
...........................................................
----------------------------------------------------------------------
Ran 59 tests in 0.295s

OK
```

**59/59 pass, 0 failures, 0 errors.**

What the 59 tests cover:

| Group | Tests | Assertion |
|---|---|---|
| `ContractTests` | 9 | return shape, completeness, empty queue, Decimal money, duplicate/invalid input, derived `rmb_available` |
| `FormulaTests` | 14 | `P` normalisation from config, `D` monotone in slack (linear + exponential), slack arithmetic, `A` monotone in waiting, aging overtake, `L` penalty, unit intervals, weighted-sum identity, overdue flag |
| `ConfigTests` | 9 | defaults, Module 2 values and their source keys, strict unknown-key rejection, negative weight, zero total weight, bad normaliser, bad mode, missing priority point, JSON-serialisable snapshot |
| `DeterminismTests` | 2 | repeated calls identical; float noise cannot split an exact tie |
| `TieBreakTests` | 3 | score → arrival → `payment_id`, on a synthetic pair and on the real tie |
| `UnfundableTests` | 6 | unfundable never dropped, skipping reaches a later instruction, running-balance pass, head-of-line detection, unknown balance, foreign id |
| `PurityTests` | 2 | `queue`/`state`/`config` unchanged, no money field written |
| `GoldenCaseTests` | 6 | the three hand-verified orders, three known scores, the 9 changed positions, renderers, detail CSV |
| `SensitivityTests` | 2 | sweep monotone in `weight_funding`, unknown key rejected |
| `IntegrationTests` | 3 | Module 3 uses the real function, S2 and S4 share it, S2 ≠ S1 under liquidity pressure |

---

## 2. Hand-checkable ranking case

```bash
python run_module4.py demo
```

```
==============================================================================
MODULE 4 - dynamic payment ranking (S2 / S4 ordering)
==============================================================================
case       : demo_case_t1800
description: Eleven queued instructions at t=1800s with one exact score tie (P000010/P000011); RMB available 600,000 is enough for 3 instructions in score order but only 5 in arrival order
decision t : 1800 s
queue      : 11 instructions

--- 1. scoring parameters actually used -------------------------------
formula      : score = 0.45*P + 0.4*D + 0.15*A + 0*L
priority pts : {'URGENT': 3.0, 'HIGH': 2.0, 'NORMAL': 1.0}   (normalised by 3)
normalisers  : deadline 7200s, aging 7200s
deadline mode: linear   aging mode: linear
confirmation delay subtracted from slack: 10s

--- 2. score breakdown in rank order ----------------------------------
t=1800s  queued=11  rmb_available=600000.00
 #  payment_id  prio    amount_rmb  deadline  wait_s  slack_s      P      D      A      L   score  pay_now
--  ----------  ------  ----------  --------  ------  -------  -----  -----  -----  -----  ------  -------
 1  P000001     URGENT     100,000       660    1740    -1150  1.000  1.000  0.242  0.050  0.8862      yes
 2  P000004     URGENT     460,000      1230    1470     -580  1.000  1.000  0.204  0.230  0.8806      yes
 3  P000003     HIGH        75,000      2040    1560      230  0.667  0.968  0.217  0.037  0.7197      yes
 4  P000007     HIGH       410,000      4200     480     2390  0.667  0.668  0.067  0.205  0.5772      yes
 5  P000008     HIGH       210,000      5160     300     3350  0.667  0.535  0.042  0.105  0.5201      yes
 6  P000002     NORMAL     250,000      4950    1650     3140  0.333  0.564  0.229  0.125  0.4099      yes
 7  P000005     NORMAL      95,000      6540    1260     4730  0.333  0.343  0.175  0.048  0.3135      yes
 8  P000006     NORMAL      68,000      6900     900     5090  0.333  0.293  0.125  0.034  0.2860      yes
 9  P000010     NORMAL      34,000      6900      60     5090  0.333  0.293  0.008  0.017  0.2685      yes
10  P000011     NORMAL      34,000      6900      60     5090  0.333  0.293  0.008  0.017  0.2685      yes
11  P000009     NORMAL     120,000      8100     240     6290  0.333  0.126  0.033  0.060  0.2056      yes

--- 3. arrival order (S1-like) vs dynamic order (S2) ------------------
payment_id  arrival #  score #    move  score
----------  ---------  -------  ------  ------
P000001             1        1  = same  0.8862
P000002             2        6  v down  0.4099
P000003             3        3  = same  0.7197
P000004             4        2    ^ up  0.8806
P000005             5        7  v down  0.3135
P000006             6        8  v down  0.2860
P000007             7        4    ^ up  0.5772
P000008             8        5    ^ up  0.5201
P000009             9       11  v down  0.2056
P000010            10        9    ^ up  0.2685
P000011            11       10    ^ up  0.2685
changed positions: 9/11   moved up: P000004, P000007, P000008, P000010, P000011   moved down: P000002, P000005, P000006, P000009

--- 4. temporarily unfundable instructions (skipping, not dropping) ---
arrival order  available 600000.00 -> payable now: 5/11  ['P000001', 'P000002', 'P000003', 'P000005', 'P000006']
               blocked: 6  first blocked = P000004  head-of-line blocked = False
score order    available 600000.00 -> payable now: 3/11  ['P000001', 'P000004', 'P000010']
               blocked: 8  first blocked = P000003  head-of-line blocked = False

--- 5. variant A: funding-demand penalty enabled (weight_funding=1.0) -
...  (order: P000001, P000003, P000004, P000008, P000007, P000002, P000005, P000006, P000010, P000011, P000009)
changed positions vs default: 4/11
moved up   : P000003, P000008
moved down : P000004, P000007

--- 6. variant B: aging-heavy weights (0.2 / 0.2 / 0.6) ---------------
...  (order: P000001, P000004, P000003, P000002, P000007, P000008, P000005, P000006, P000010, P000011, P000009)
changed positions vs default: 3/11
moved up   : P000002
moved down : P000007, P000008
==============================================================================
```

**Readings that a marker can check by hand:**

* `P000001` — URGENT, overdue (deadline 660 s, `t` = 1 800 s): `0.45·1.0 + 0.40·1.0 + 0.15·1740/7200 = 0.88625`. ✔
* `P000003` — HIGH, slack 230 s: `0.45·0.667 + 0.40·0.968 + 0.15·0.217 = 0.71972`. ✔ (worked in
  `docs/scoring_formula.md` §4)
* `P000010` / `P000011` — identical inputs, identical score 0.2685, ordered by `payment_id`. ✔
* Variant A: the 460 000 URGENT payment drops behind the 75 000 near-deadline HIGH payment
  once the funding-demand penalty is switched on. ✔
* Variant B: the NORMAL payment that has waited 1 650 s climbs above the HIGH payment that
  has waited 480 s. ✔

---

## 3. End-to-end run through Module 3

```bash
python run_module4.py integrate --module3 "C:\Users\于沈豪\Desktop\第三模块\module3" ^
    --dataset "C:\Users\于沈豪\Desktop\第三模块\module3\fixtures\pilot\low_rmb_liquidity\seed_1001"
```

```
module3  : C:\Users\于沈豪\Desktop\第三模块\module3
dataset  : pilot_low_rmb_liquidity_seed_1001  (120 payments, 24 inflows)
scenario : low_rmb_liquidity  seed = 1001
outputs  : ...\第四模块\outputs\pilot_low_rmb_liquidity_seed_1001

strat   settled pending queued  FX     FX cost  module4     module5
-------------------------------------------------------------------
S0          120       0      0  70   23,746.17  not used    not used
S1          120       0      0  64   23,314.17  not used    not used
S2          120       0      0  62   23,170.21  M4 real     not used
S3          120       0      0  64   23,314.17  not used    FALLBACK
S4          120       0      0  63   23,242.20  M4 real     FALLBACK

[OK] S2/S4 ran on the real Module 4 ranking function (no fallback).

--- Module 4 diagnostic: S2 vs S1 by priority and payment size ---
group     n  done S1  done S2  mean_delay S1  mean_delay S2  p95 S1  p95 S2  overdue S1  overdue S2  verdict
------  ---  -------  -------  -------------  -------------  ------  ------  ----------  ----------  -----------------------------
URGENT   13       13       13          134.5           97.5   233.6   215.6           0           0  mean delay better, p95 better
HIGH     31       31       31           68.8           56.3   194.5   171.0           0           0  mean delay better, p95 better
NORMAL   76       76       76           94.6           92.1   262.5   302.0           0           0  mean delay better, p95 worse
ALL     120      120      120           92.3           83.5   247.1   284.8           0           0  mean delay better, p95 worse
LARGE    33       33       33          121.3          109.7   227.2   250.0           0           0  mean delay better, p95 worse
SMALL    87       87       87           81.3           73.5   247.7   299.7           0           0  mean delay better, p95 worse
Module 6 owns the official metric set; these numbers only sanity-check Module 4.
```

What this proves:

1. **Integration is real.** `S2` and `S4` show `M4 real`, i.e.
   `run_summary.json → using_fallback_module4 = false`. Module 3's fallback is not used.
2. **Module 4 changes behaviour.** Same dataset, same seed, same exogenous path:
   S2 pays 2 fewer FX trades than S1 (64 → 62) and FX cost falls by 143.96 RMB.
3. **The direction is the expected one.** URGENT mean delay −37.0 s (−27.5 %), HIGH
   −12.5 s (−18.2 %). This is **one seed**; the statistical version of this table
   (7 scenarios × 30 paired seeds with 95% CIs) is in
   [`proposal_alignment.md`](proposal_alignment.md), and it both strengthens the urgent
   result (7/7 scenarios) and **overturns** the single-seed "NORMAL P95 worse" reading:
   the real ordinary-payment cost is a completion-rate loss in the two heaviest stress
   scenarios, not a delay-tail effect. Do not quote the NORMAL row above as a finding.
4. **S3/S4 are not reportable yet.** Both show `module5 FALLBACK`; only the Module 4
   half of S4 is real.

`fixed_demo` (no liquidity pressure, all 10 payments settle against a 6 m opening
balance) gives identical S0–S4 outcomes — the expected null result when nothing is
scarce, which is a useful control:

```
strat   settled pending queued  FX     FX cost  module4     module5
-------------------------------------------------------------------
S0           10       0      0   0        0.00  not used    not used
S1           10       0      0   0        0.00  not used    not used
S2           10       0      0   0        0.00  M4 real     not used
S3           10       0      0   0        0.00  not used    FALLBACK
S4           10       0      0   0        0.00  M4 real     FALLBACK
```

---

## 4. Standalone priority / large-payment diagnostic

```bash
python run_module4.py impact ^
  --run "outputs\pilot_low_rmb_liquidity_seed_1001\pilot_low_rmb_liquidity_seed_1001_S2" ^
  --baseline "outputs\pilot_low_rmb_liquidity_seed_1001\pilot_low_rmb_liquidity_seed_1001_S1"
```

```
run        : pilot_low_rmb_liquidity_seed_1001_S2  (strategy S2)
observation: 28800 s
large >=   : 250000 RMB

group     n  done  completion  outstanding  mean_delay  p95_delay  mean_wait  p95_wait  overdue
------  ---  ----  ----------  -----------  ----------  ---------  ---------  --------  -------
URGENT   13    13       1.000            0        97.5      215.6       87.5     205.6     0/13
HIGH     31    31       1.000            0        56.3      171.0       46.3     161.0     0/26
NORMAL   76    76       1.000            0        92.1      302.0       82.1     292.0     0/47
ALL     120   120       1.000            0        83.5      284.8       73.5     274.8     0/86
LARGE    33    33       1.000            0       109.7      250.0       99.7     240.0     0/27
SMALL    87    87       1.000            0        73.5      299.7       63.5     289.7     0/59
```

Large payments (`>= 250 000 RMB`) are **not** worse off in mean delay (109.7 s vs
121.3 s for S1) and their P95 grows by 22.8 s; the ordinary tail carries the cost. That
is the "funding-demand factor" question proposal §4.2.1 raises, and it is answered by
the `weight_funding` sweep rather than by an assumption.

---

## 5. Reproducing all of the above

```bat
cd 第四模块
set MODULE3_PATH=C:\Users\于沈豪\Desktop\第三模块\module3

python -m unittest discover -s tests -t . -v
python run_module4.py demo
python run_module4.py sweep --key weight_funding --values 0,0.25,0.5,1.0
python run_module4.py integrate --module3 "%MODULE3_PATH%" ^
    --dataset "%MODULE3_PATH%\fixtures\pilot\low_rmb_liquidity\seed_1001"
```

Runs are deterministic: the same dataset and seed always produce the same order, the
same FX count and the same metric table.
