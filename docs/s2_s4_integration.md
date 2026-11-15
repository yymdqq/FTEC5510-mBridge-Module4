# S2 and S4 — how the ranking is used

Hand-over document for **Module 5** (S4 must share this implementation) and
**Module 6** (interpretation of the results).

---

## 1. What S2 and S4 change, and what they do not

| Strategy | Payment order | Waiting / top-up |
|---|---|---|
| S0 strict FIFO | arrival order, **no** skipping | immediate FX |
| S1 skippable FIFO | arrival order, skipping allowed | immediate FX |
| **S2 dynamic** | **score order**, skipping allowed | immediate FX |
| S3 waiting | arrival order, skipping allowed | wait or FX |
| **S4 combined** | **score order**, skipping allowed | wait or FX |

Module 4 owns exactly one thing: **the order**. It returns no money, no decision and
no side effect. S2 and S4 therefore call the *same* `rank_payments` function — there
is no second copy of the scoring logic anywhere, which is the requirement in
分工.docx ("S4 组合调用模块 4 的动态排序与模块 5 的等待／换汇决策函数，共用实现，避免复制另一套逻辑").

```
S2 = S1 + rank_payments                     (Module 4 only)
S4 = S1 + rank_payments + decide_funding    (Module 4 + Module 5)
```

So the S2-vs-S1 comparison isolates the scheduling effect, and S4-vs-S2 isolates the
waiting/top-up effect added on top of it.

## 2. Engine call path (Module 3, verified)

`Simulation._ordered_queue()`:

```python
queued = [p for p in self.payments if p.status == QUEUED]        # QUEUED only
if self.strategy in ("S2", "S4"):
    ranked = self.rank_fn([self._payment_view(p) for p in queued],
                          self._state_view(), self.config)
    order  = list(ranked.get("order") or [])
    ordered = [self.by_id[pid] for pid in order if pid in known and ...]
    missing = [...]                                              # safety net
    return ordered + missing
return sorted(queued, key=lambda p: (p.arrival_time, p.payment_id))   # S0/S1/S3
```

`_review()` then walks that order once per re-review loop and submits every
instruction whose `amount_rmb <= rmb_available`, recalculating the available balance
after each submission (proposal §4.2.2, "After each submission, available funds are
recalculated"). The first instruction in score order that cannot be funded becomes the
funding target handed to Module 5 for S3/S4.

Consequences worth stating in the report:

* Ranking is recomputed at **every decision event** (arrival, inflow notice, inflow,
  FX completion, confirmation, periodic review), so the order is never stale. Scores
  move continuously with `t`; there is no cached order.
* Because `queue` contains only `QUEUED` payments, a `PENDING` payment is not ranked
  again, and an already-`SETTLED` one disappears from the queue.
* The engine appends any instruction Module 4 omitted, so a ranking bug cannot lose a
  payment — and `rank_payments` already guarantees completeness itself.

## 3. Information used

Only fields Module 3 puts in the view at the current instant:

| Used | Not used |
|---|---|
| `t`, `rmb_available` | the full `inflows.csv` |
| `payment_id`, `arrival_time`, `amount_rmb`, `priority`, `deadline_time` | future inflow amounts or arrival times |
| resolved `config.ranking_parameters` | other strategies' outcomes |

`pending_fx` and `cpty_remaining` are *not* used by the ranking: a pending FX trade
that will cover a gap changes **fundability** (an engine/Module 5 question), not
**priority**. Mixing the two would let a top-up that has not completed silently
reorder the queue.

## 4. Deadline-risk and the "cannot pay anything" case

When no queued instruction is fundable the engine still calls the ranker (it needs to
know which payment is first), so `rank_payments` is expected to work with
`rmb_available = 0`. It does: `fundable_now` becomes `false` for the whole queue, the
order is unchanged, and the first entry is the one Module 5 must reason about.

Overdue instructions stay in the queue and keep `D = 1.0`; the module never removes a
payment and never marks it failed. `overdue` / `at_risk` flags are exposed for
Module 5 and 6 but do not alter the arithmetic beyond the `D` clamp.

## 5. Interaction with Module 5 / S4

* Module 5 should take its target from `rank_payments(...)["order"][0]` **after**
  filtering to fundable-check-then-blocked, i.e. the same rule the engine uses:
  the highest-scoring eligible instruction that cannot be funded.
* `select_payable(order, queue, available_rmb)` returns exactly `first_blocked`, so
  Module 5 can call it instead of re-implementing the skip logic.
* A `WAIT` decision does not change the order; the next review re-ranks with a larger
  `t`, which mechanically raises `A` and lowers `D`. That is the intended coupling.
* Do not add a "promised by FX" bonus to the score. Proposal §4.2.3 says a successful
  top-up "does not reserve priority for its target: all queued instructions are
  reassessed under the applicable strategy" — the ranking must stay blind to who was
  topped up.

## 6. S2 / S4 status

| Item | Status |
|---|---|
| S2 order implemented by Module 4, used by Module 3 | **verified** — `using_fallback_module4 = false` |
| S4 order identical to S2 for the same event path | **verified** — both call the same function |
| S2 economy vs S1 on `pilot/low_rmb_liquidity/seed_1001` | URGENT mean delay 134.5 → 97.5 s, HIGH 68.8 → 56.3 s, NORMAL mean 94.6 → 92.1 s, NORMAL p95 262.5 → 302.0 s, FX trades 64 → 62 |
| S4 waiting behaviour | **not implemented** — Module 5 fallback (immediate top-up) |
| S3 | Module 4 not involved (arrival order) |
