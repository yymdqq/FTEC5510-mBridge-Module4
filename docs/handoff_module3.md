# Hand-over to Module 3 — `rank_payments` interface and call example

Module 3 already contains the integration seam (`m3engine/adapters.py`): it imports a
module named `module4_rank` and calls `rank_payments(queue, state, config)`. This
folder provides exactly that file, so **no change to Module 3 is required**.

---

## 1. Signature

```python
rank_payments(queue, state, config) -> dict
```

| Input | Type | Contents handed over by Module 3 |
|---|---|---|
| `queue` | `list[dict]` | `payment_id` (str), `arrival_time` (int s), `amount_rmb` (`Decimal`), `priority` (`URGENT`/`HIGH`/`NORMAL`), `deadline_time` (int s), `submit_time` (`None` while queued), `waiting_time` (int s) |
| `state` | `dict` | `t` (int s), `rmb_total`, `rmb_reserved`, `rmb_locked`, `rmb_available`, `hkd_total`, `hkd_committed`, `hkd_available`, `cpty_remaining`, `pending_fx` |
| `config` | `dict` | the loaded `config.json` (Module 2 contract v1.0.0) |

| Output key | Type | Contract | Content |
|---|---|---|---|
| `order` | `list[str]` | **required** | every queued `payment_id`, highest score first |
| `scores` | `dict[str, dict]` | **required** | per payment `{score, rank, p_component, d_component, a_component, l_component, slack_sec, waiting_sec, fundable_now?, overdue, at_risk, explanation}` |
| `detail` | `list[dict]` | extension | the same rows in rank order, plus raw inputs and weighted terms |
| `decision` | `dict` | extension | `t`, `n_queued`, `rmb_available`, `n_fundable_now` |
| `parameters` | `dict` | extension | resolved weights/normalisers, the config key each came from, warnings |
| `formula` | `str` | extension | the score formula with the resolved weights |
| `warnings` | `list[str]` | extension | configuration problems worth logging |

Only `order` and `scores` are consumed by Module 3; everything else is for the event
log, the report and the audit trail.

## 2. Call example

```python
from decimal import Decimal
from module4_rank import rank_payments

queue = [
    {"payment_id": "P000003", "arrival_time": 240, "amount_rmb": Decimal("75000.00"),
     "priority": "HIGH", "deadline_time": 2040, "submit_time": None, "waiting_time": 1560},
    {"payment_id": "P000002", "arrival_time": 150, "amount_rmb": Decimal("250000.00"),
     "priority": "NORMAL", "deadline_time": 4950, "submit_time": None, "waiting_time": 1650},
]
state = {"t": 1800, "rmb_total": Decimal("1400000.00"),
         "rmb_reserved": Decimal("800000.00"), "rmb_locked": Decimal("0.00"),
         "rmb_available": Decimal("600000.00")}
config = {"ranking_parameters": {
    "priority_points": {"URGENT": 3.0, "HIGH": 2.0, "NORMAL": 1.0},
    "weight_priority": 0.45, "weight_deadline": 0.40, "weight_aging": 0.15,
    "deadline_normalizer_sec": 7200, "aging_normalizer_sec": 7200}}

ranked = rank_payments(queue, state, config)
print(ranked["order"])                 # ['P000003', 'P000002']
print(ranked["scores"]["P000003"])     # {'score': 0.719722, ...}
```

## 3. Wiring options (both verified against Module 3)

### A. PYTHONPATH — nothing is copied (recommended)

```bat
set PYTHONPATH=C:\Users\<you>\Desktop\第四模块
python ..\第三模块\module3\run_engine.py --dataset <dataset> --strategy S2
```

`adapters.load_rank_payments()` does `importlib.import_module("module4_rank")`, which
now resolves to this folder. Check the result:

```bat
python -c "import json;print(json.load(open('module3_outputs/<run_id>/run_summary.json'))['using_fallback_module4'])"
:: must print False
```

### B. Copy into Module 3

Copy `module4_rank.py` **and** the `m4rank/` folder into `module3/m3engine/`, then:

```bat
set M3_MODULE4_MODULE=m3engine.module4_rank
```

`module4_rank.py` inserts its own directory on `sys.path`, so the package import still
works from inside `m3engine/`.

### C. One command that does A and checks the result

```bat
python run_module4.py integrate --module3 "C:\path\to\第三模块\module3" ^
    --dataset "C:\path\to\第三模块\module3\fixtures\pilot\low_rmb_liquidity\seed_1001"
```

The command prints `[OK] S2/S4 ran on the real Module 4 ranking function` or fails
loudly if the engine fell back.

## 4. Behaviour Module 3 can rely on

1. **Pure function** — no balance, lock, status or `queue`/`state`/`config` mutation.
2. **Complete** — every queued `payment_id` appears exactly once in `order`. Module 3's
   `missing` safety net therefore never triggers; if it ever did, it would indicate a
   contract violation worth logging.
3. **Deterministic** — identical inputs give an identical order, so paired S0–S4 runs
   on the same event path stay comparable.
4. **Cheap** — O(n log n) on the queued set with no allocation per money value; 120
   payments × every decision event is well under a second for a full run.
5. **Errors are typed** — `RankingConfigError` for a bad `config.json`,
   `RankingInputError` for a malformed queue/state. Both subclass `ValueError`, so a
   `try/except ValueError` in the run harness catches them.

## 5. What Module 3 should record in `events.csv`

The `reason` field of `PAYMENT_SUBMITTED` (or an extra `RANKING` event) can carry
`ranked["scores"][pid]["explanation"]`, which already contains every weighted term:

```
P=0.667x0.45=0.3000 + D=0.968x0.40=0.3872 + A=0.217x0.15=0.0325 - L=0.037x0.00=0.0000 => 0.7197
```

`run_module4.py rank --json out.json` writes the whole decision event, which is the
most convenient object to keep next to a run.
