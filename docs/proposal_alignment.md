# Do the results match what the proposal expected?

This document tests proposal §5.1 ("Expected Findings") and the research question
against the formal fixture set: **7 scenarios × 30 seeds**, paired by seed, with 95%
confidence intervals — the design proposal §4.5 asks for. S3/S4 are excluded because
Module 5 is still a fallback, so only S0/S1/S2 are compared.

Reproduce with:

```bash
python analysis/check_alignment.py paired      # 630 runs, ~1 min
python analysis/check_alignment.py weights     # 360 runs, ~1 min
```

Short answer: **the proposal's central mechanism is strongly confirmed, one of its
hedged predictions is only marginally true, and its headline economic claim — reducing
prefunding and FX top-up needs — cannot be supported with the current data.** The
proposal itself wrote the warning that the data now confirms: better urgent service is
not protection for all payments.

---

## 1. Scoreboard

| Proposal §5.1 statement | Evidence (7 scenarios × 30 paired seeds) | Verdict |
|---|---|---|
| "Comparing S2 with S1 will test whether Priority + Deadline + Aging **better protects urgent** … payments" | URGENT mean delay lower in **7/7** scenarios, URGENT P95 lower in **7/7**, every CI excludes 0 | **confirmed** |
| … "or **near-deadline** payments" | HIGH mean delay lower in 7/7 (6/7 significant); URGENT overdue rate −20.7 pp / −18.6 pp in the two stress scenarios | **confirmed** |
| "**Aging may reduce excessive waiting** for ordinary payments" | NORMAL mean delay lower in 7/7 by direction, but only −1.5 s to −5.2 s in the mild scenarios; NORMAL P95 is *worse* in 2 scenarios (n.s.) | **only marginally, not material** |
| §4.3: "improved urgent service is **not** to be interpreted as protection for all payments" | NORMAL completion **falls** −4.8 pp (`payment_surge`) and −6.2 pp (`large_payments`); NORMAL overdue rate **rises** +3.4 pp / +5.9 pp | **confirmed — and this is the cost side** |
| Research question: "reduce … prefunded liquidity and **FX top-up needs**" | FX trades lower in 5/7 by direction (2/7 significant); FX economic cost lower in only 2/7, and **significantly higher** (+303 RMB) in `large_payments` | **not supported** |
| §4.4.1: "identify the **lowest tested opening RMB** meeting both service targets" (scan 10–40 m) | not run; the scan grid is incompatible with the delivered baseline (see §5) | **not yet testable** |
| "S0 vs S1 tests whether bypassing **alleviates head-of-line blocking**" | S0 needs **+2.2 to +8.0 more FX trades** in 7/7 scenarios; completion up to −10.9 pp in `large_payments` | **confirmed** |
| "The study will **not assume one strategy is universally optimal**" | S2 wins on delay everywhere but loses on NORMAL completion in 2/7; weights shift the trade-off (see §4) | **confirmed** |

---

## 2. What is strongly supported

**Urgent and near-deadline payments are protected, in every scenario.** Paired
differences S2 − S1, mean [95% CI], seconds:

| scenario | URGENT mean delay | URGENT P95 delay |
|---|---|---|
| baseline | −11.1 [−15.9, −6.4] | −44.0 [−65.0, −22.9] |
| low_rmb_liquidity | −24.1 [−30.3, −17.9] | −85.4 [−109.5, −61.2] |
| payment_surge | **−380.7** [−540.9, −220.4] | **−2305.4** [−3143.3, −1467.6] |
| large_payments | **−727.9** [−1190.7, −265.1] | **−1985.9** [−3150.6, −821.2] |
| tight_deadlines | −11.8 [−16.3, −7.2] | −45.8 [−65.9, −25.8] |
| delayed_inflows | −10.8 [−15.5, −6.2] | −54.5 [−77.2, −31.8] |
| fx_capacity_shock | −60.4 [−118.1, −2.7] | −292.4 [−576.4, −8.5] |

The effect is largest exactly where the proposal expects it — concentrated arrivals and
large payments — and the deadline side is confirmed by the overdue rate:
URGENT overdue falls by **20.7 pp** (`payment_surge`), **18.6 pp** (`large_payments`),
2.6 pp (`tight_deadlines`) and 2.2 pp (`fx_capacity_shock`).

**Head-of-line blocking is real.** S0 (strict FIFO) versus S1 (skippable FIFO), same 30
seeds: S0 needs 2.2–8.0 more FX trades in 7/7 scenarios (`payment_surge` +8.0,
`fx_capacity_shock` +5.4) and loses up to **10.9 pp** completion in `large_payments`.
Bypassing a stuck queue head saves liquidity, as proposal §5.1 predicts.

**Total service improves where it is binding.** Overall completion is +2.03 pp
(`payment_surge`) and +1.72 pp (`large_payments`), overall mean delay is lower in 7/7
(7/7 significant).

---

## 3. What is not supported: the ordinary-payment cost

This is the finding that must go into the report with its own table, because
proposal §4.3 explicitly demands it ("Results also report ordinary-payment waiting
outcomes so that improved urgent service is not interpreted as protection for all
payments").

Completion rate by priority, S1 → S2 (mean of 30 seeds, `*` = paired CI excludes 0):

| scenario | URGENT | HIGH | NORMAL |
|---|---|---|---|
| baseline | 0.995 → 0.995 | 0.997 → 0.997 | 0.998 → 0.998 |
| low_rmb_liquidity | 0.984 → 0.987 | 0.992 → 0.994 | 0.991 → 0.991 |
| **payment_surge** | 0.670 → **0.907\*** | 0.691 → **0.804\*** | 0.682 → **0.634\*** |
| **large_payments** | 0.565 → **0.836\*** | 0.548 → **0.671\*** | 0.567 → **0.505\*** |
| tight_deadlines | 0.995 → 0.995 | 0.997 → 0.997 | 0.998 → 0.998 |
| delayed_inflows | 0.997 → 0.997 | 1.000 → 1.000 | 0.998 → 0.999 |
| fx_capacity_shock | 0.979 → 0.989\* | 0.978 → 0.991 | 0.980 → 0.986 |

Outstanding ordinary payments left at the observation endpoint:

| scenario | NORMAL outstanding S1 → S2 | NORMAL overdue rate S1 → S2 |
|---|---|---|
| payment_surge | 49.6 → **57.2** | 7.76 % → **11.12 %** (+3.36 pp\*) |
| large_payments | 33.8 → **38.7** | 24.69 % → **30.63 %** (+5.94 pp\*) |

So in the two scenarios where liquidity actually binds, S2 buys a 23.7 pp / 27.1 pp
gain for urgent payments **by taking about 5 pp of completion from ordinary ones**.
Total completion still rises, which is exactly why reporting the overall number alone
would be misleading.

A single seed hinted at this through P95 delay; the 30-seed test shows the real
manifestation is a **completion-rate** effect, and it is *larger* than delay statistics
suggest. Conversely, the P95-delay story from one seed does **not** hold up
(NORMAL P95 is −0.5 s in `baseline`, +7.1 s in `low_rmb_liquidity`, neither
significant). Cite this document, not the single-seed demo, in the report.

---

## 4. Can the scoring weights fix it?

`aging` cannot. Re-running S2 on the 30 seeds of each stress scenario with different
weights (`python analysis/check_alignment.py weights`):

**payment_surge**

| weights | ALL compl. | URGENT | HIGH | NORMAL | NORMAL overdue | URGENT delay | FX |
|---|---|---|---|---|---|---|---|
| S1 reference | 0.683 | 0.670 | 0.691 | **0.682** | 7.76 % | 938 s | 60.8 |
| default .45/.40/.15, w_L=0 | 0.703 | 0.907 | 0.804 | **0.634** | 11.12 % | 557 s | 57.8 |
| aging+ .40/.35/.25 | 0.699 | 0.878 | 0.789 | 0.637 | 10.94 % | 632 s | 57.8 |
| aging++ .35/.30/.35 | 0.698 | 0.844 | 0.778 | 0.646 | 10.40 % | 664 s | 57.6 |
| aging+++ .30/.25/.45 | 0.695 | 0.813 | 0.767 | 0.649 | 9.80 % | 776 s | 57.8 |
| **funding .45/.40/.15, w_L=1** | **0.725** | 0.897 | 0.815 | 0.665 | 9.17 % | **502 s** | 59.6 |
| **mixed .35/.30/.35, w_L=1** | 0.723 | 0.861 | 0.789 | **0.676** | **7.73 %** | 575 s | 59.6 |

Three conclusions the group can use:

1. **Raising `weight_aging` to 0.45 recovers only 1.5 pp of NORMAL completion** while
   costing 9.4 pp of URGENT completion and 219 s of URGENT delay. Aging is not the
   fairness lever — which is the same structural fact as Module 4's documented weight
   analysis: `w_A·A ≤ 0.15` against a 0.30 gap between URGENT and NORMAL `w_P·P`.
2. **The funding-demand factor `L` is the effective lever.** With `w_L = 1`,
   NORMAL completion rises to 0.665 *and* URGENT delay improves to 502 s — better than
   the default on both dimensions simultaneously.
3. **Combining aging and `L` nearly restores S1's fairness** (NORMAL 0.676 vs 0.682,
   overdue 7.73 % vs 7.76 %) while keeping most of the urgent gain (URGENT 0.861 vs
   0.670). No setting is Pareto-dominant: this is the "no universally optimal policy"
   that proposal §5.1 anticipates.

`L` is switched **off** (`weight_funding = 0`) in the initial experiment exactly as
proposal §4.2.1 specifies. The evidence above means the "test the effect of the
funding-demand factor separately" run is no longer optional for the report — it is the
run that answers the fairness question.

**large_payments** shows the same ranking of levers (default NORMAL 0.505 →
`w_L=1` 0.541 → mixed 0.550; S1 reference 0.567), with URGENT delay moving the other
way (1117 s → 1012 s → 1109 s).

---

## 5. Why the headline claim cannot be tested with the current data

The research question has two halves. "…without excessive settlement delays" is
answered (delay falls in 7/7 scenarios). "…**reduce prefunded liquidity and FX top-up
needs**" is not, for a structural reason: **liquidity barely binds in five of the seven
scenarios.**

| scenario | completion | overdue | P95 delay | service targets met |
|---|---|---|---|---|
| baseline | 0.998–0.998 | 0.000–0.000 | 191–226 s | yes |
| low_rmb_liquidity | 0.980–0.991 | 0.001–0.004 | 256–278 s | yes |
| payment_surge | 0.630–0.703 | 0.142–0.235 | 3518–6340 s | **NO** |
| large_payments | 0.453–0.579 | 0.336–0.463 | 6169–10590 s | **NO** |
| tight_deadlines | 0.998–0.998 | 0.001–0.004 | 186–226 s | yes |
| delayed_inflows | 0.999–0.999 | 0.000–0.000 | 207–233 s | yes |
| fx_capacity_shock | 0.978–0.988 | 0.002–0.009 | 269–691 s | yes |

Opening RMB is 6 m in the baseline and 1.8 m in `low_rmb_liquidity`, yet completion is
still 98–99 %. The bank is heavily over-funded because HKD 15 m (≈ 13.5 m RMB of FX
capacity) plus RMB inflows of roughly 10 m per run keep every gap fundable. FX is
therefore never really unavailable, so "prefunding" is not the binding constraint and
cannot be shown to fall.

Two consequences:

* **The 10 m – 40 m scan grid from proposal §5.1 is unusable here.** Every point of it
  is above the current baseline, so every strategy passes and the "lowest feasible
  opening balance" is simply the grid floor — no information. The grid must be
  re-derived *below* the baseline (roughly 0.5 m – 6 m) and frozen before formal runs.
* **The two scenarios that do bind (surge, large) violate the service targets for every
  strategy**, including S2 (completion 0.63–0.70 vs a 0.95 target). They are useful for
  comparing strategies, but they cannot be used to claim "targets met".

---

## 6. Parameters and scenarios that deviate from the proposal

These are Module 2 decisions, not Module 4 bugs, but the report must state them, because
several "expected vs actual" comparisons change meaning under them.

| proposal | delivered fixtures |
|---|---|
| opening RMB 20 m | **6 m** (1.8 m in the liquidity stress) |
| fixed reserve 5 m | **0.8 m** |
| opening HKD 100 m | **15 m** |
| `fx_rate` 0.92 | **0.90** |
| proportional fee 3 bps | **15 bps** (5×) |
| FX completion 20 s, 60/120 s only in stress | **120 s in every scenario** |
| counterparty capacity 50 m (10 m constrained) | **5 m per trade** (1 m constrained) |
| priority shares 10 / 30 / 60 | **10 / 25 / 65** |
| baseline payment size fixed 5 m | **lognormal, median 0.12 m** |
| initial-funding scan grid 10–40 m | **incompatible**, see §5 |

And of the six stress scenarios in proposal §4.4.2, **two are missing** from the
delivered set:

* **No. 3 "Urgent-payment shock"** — priority shares are 0.10 / 0.25 / 0.65 in *all
  seven* fixtures. This is the scenario the proposal designed precisely to test
  "prolonged delays for ordinary payments", i.e. the fairness question of §3. It should
  be added (e.g. URGENT share 0.4) before the interim report claims anything about
  fairness across priority mixes.
* **No. 5 "Higher FX fees or delays"** — spread is 15 bps and delay 120 s in every
  fixture, so the "is top-up still worthwhile?" comparison cannot be made. This is also
  the scenario that makes waiting-versus-top-up (S3/S4) interesting.

`fx_counterparty_capacity_mode` is `per_trade`, so a counterparty can never run out of
RMB over a run — "FX not executable" (proposal §4.1.3, §4.2.3) never actually happens.
Switching to `cumulative` (Module 3 supports it) is the cheapest way to create the
scenario S3/S4 need.

---

## 7. What to change before the interim defence

1. **Rewrite the S2 sentence.** Not "dynamic scheduling improves service", but
   "dynamic scheduling reallocates service from ordinary to urgent payments: urgent
   completion +23.7 pp, ordinary completion −4.8 pp in the surge scenario, total
   completion +2.0 pp". Report the per-priority table of §3 next to any headline number.
2. **Promote the `w_L` sensitivity run from "optional" to required.** It is the only
   setting that improves fairness *and* urgent delay at the same time (§4).
3. **Drop the 10–40 m funding scan or re-derive it** below the current baseline;
   otherwise the "minimum feasible prefunding" deliverable is vacuous.
4. **Add the two missing stress scenarios** (urgent-payment shock, higher FX
   fees/delays) or state in the report that six scenarios were reduced to five effective
   axes and why.
5. **Switch counterparty capacity to `cumulative`** (or cut HKD) for at least one
   scenario, so "FX cannot be executed" is observable — otherwise the S3/S4 story has no
   stage.
6. **Declare the parameter deviations of §6** in the parameter table, and stop quoting
   the proposal's 20 m / 100 m / 3 bps / 20 s as if they were the simulation settings.
7. Keep S3/S4 out until Module 5 lands; every number here is S0/S1/S2 only.

---

## 8. Where the numbers come from

```
python analysis/check_alignment.py paired     -> tables A-E of this document
python analysis/check_alignment.py weights    -> section 4 tables
```

Both need Module 3 next to this folder (or `--module3 <path>`). They run 630 and 360
simulations respectively, write nothing, and are deterministic: the same fixtures and
seeds reproduce every number exactly.
