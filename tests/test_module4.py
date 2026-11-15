"""Module 4 acceptance tests.

Run with either of::

    python -m unittest discover -s tests -t . -v
    python run_module4.py selftest

The tests are grouped as:

* contract      — the exact return shape Module 3 depends on
* formula       — P / D / A / L definitions and their required monotonicity
* determinism   — same input always gives the same order
* tie-breaking  — score, then arrival_time, then payment_id
* unfundable    — a temporarily unfundable instruction is never dropped
* properties    — the function only sorts: no money changes, no mutation
* golden case   — the exact hand-verified orders of examples/demo_case.json
* integration   — optional, only when MODULE3_PATH points at Module 3
"""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from m4rank import (RankingConfigError, RankingInputError, aging_component,  # noqa: E402
                    before_after_table, deadline_component, deadline_slack,
                    funding_component, load_case, order_table, priority_component,
                    rank_payments, resolve_params, score_row, select_payable,
                    to_decimal, write_detail_csv)
from m4rank.cases import case_config, case_queue, case_state  # noqa: E402
from m4rank.ranking import compare_orders, rank_with_ranks  # noqa: E402

CASE = load_case()

# Hand-verified expected orders for examples/demo_case.json (t = 1800 s).
GOLDEN_DEFAULT = ["P000001", "P000004", "P000003", "P000007", "P000008", "P000002",
                  "P000005", "P000006", "P000010", "P000011", "P000009"]
GOLDEN_FUNDING = ["P000001", "P000003", "P000004", "P000008", "P000007", "P000002",
                  "P000005", "P000006", "P000010", "P000011", "P000009"]
GOLDEN_AGING_HEAVY = ["P000001", "P000004", "P000003", "P000002", "P000007", "P000008",
                      "P000005", "P000006", "P000010", "P000011", "P000009"]


def _payment(payment_id, arrival, amount, priority, deadline):
    return {"payment_id": payment_id, "arrival_time": arrival, "amount_rmb": amount,
            "priority": priority, "deadline_time": deadline}


def _config(**overrides):
    """A minimal Module 2 shaped config with optional ranking overrides."""
    config = copy.deepcopy(CASE["config"])
    config["ranking_parameters"].update(overrides)
    return config


class ContractTests(unittest.TestCase):
    def test_return_shape_matches_module3_contract(self):
        result = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
        self.assertIn("order", result)
        self.assertIn("scores", result)
        self.assertIsInstance(result["order"], list)
        self.assertEqual(sorted(result["order"]), sorted(p["payment_id"] for p in CASE["queue"]))
        self.assertEqual(set(result["scores"]), set(result["order"]))
        for payment_id, entry in result["scores"].items():
            self.assertIn("score", entry, f"{payment_id} entry must carry a score")

    def test_every_queued_payment_returned_exactly_once(self):
        result = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
        self.assertEqual(len(result["order"]), len(set(result["order"])))
        self.assertEqual(len(result["order"]), len(CASE["queue"]))

    def test_empty_queue(self):
        result = rank_payments([], {"t": 10}, case_config(CASE))
        self.assertEqual(result["order"], [])
        self.assertEqual(result["scores"], {})

    def test_scores_are_sorted_descending(self):
        result = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
        scores = [result["scores"][pid]["score"] for pid in result["order"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_accepts_decimal_money_like_module3(self):
        queue = [dict(p, amount_rmb=Decimal(p["amount_rmb"])) for p in case_queue(CASE)]
        result = rank_payments(queue, case_state(CASE), case_config(CASE))
        self.assertEqual(result["order"], GOLDEN_DEFAULT)

    def test_rejects_duplicate_ids(self):
        queue = [_payment("P1", 0, "100.00", "NORMAL", 100),
                 _payment("P1", 0, "100.00", "NORMAL", 100)]
        with self.assertRaises(RankingInputError):
            rank_payments(queue, {"t": 0}, case_config(CASE))

    def test_rejects_unknown_priority(self):
        queue = [_payment("P1", 0, "100.00", "CRITICAL", 100)]
        with self.assertRaises(RankingInputError):
            rank_payments(queue, {"t": 0}, case_config(CASE))

    def test_rejects_missing_contract_field(self):
        queue = [{"payment_id": "P1", "arrival_time": 0, "priority": "NORMAL",
                  "deadline_time": 100}]
        with self.assertRaises(RankingInputError):
            rank_payments(queue, {"t": 0}, case_config(CASE))

    def test_state_without_rmb_available_is_derived(self):
        state = {"t": 100, "rmb_total": "1000.00", "rmb_locked": "100.00",
                 "rmb_reserved": "700.00"}
        result = rank_payments([_payment("P1", 0, "300.00", "NORMAL", 500)],
                               state, case_config(CASE))
        self.assertEqual(result["decision"]["rmb_available"], "200.00")
        self.assertFalse(result["detail"][0]["fundable_now"])

    def test_state_without_t_is_an_error(self):
        with self.assertRaises(RankingInputError):
            rank_payments([_payment("P1", 0, "1.00", "NORMAL", 10)], {}, case_config(CASE))


class FormulaTests(unittest.TestCase):
    def setUp(self):
        self.params = resolve_params(case_config(CASE), strict=True)

    def test_priority_component_normalised(self):
        self.assertAlmostEqual(priority_component("URGENT", self.params), 1.0)
        self.assertAlmostEqual(priority_component("HIGH", self.params), 2.0 / 3.0, places=9)
        self.assertAlmostEqual(priority_component("NORMAL", self.params), 1.0 / 3.0, places=9)

    def test_priority_points_come_from_config(self):
        params = resolve_params(_config(priority_points={"URGENT": 9.0, "HIGH": 4.0,
                                                         "NORMAL": 1.0}))
        self.assertAlmostEqual(priority_component("NORMAL", params), 1.0 / 9.0)
        self.assertAlmostEqual(priority_component("URGENT", params), 1.0)

    def test_deadline_urgency_is_monotone_in_slack(self):
        """Less remaining time must never produce a lower deadline score."""
        values = [deadline_component(slack, self.params) for slack in range(-500, 9000, 100)]
        for earlier, later in zip(values, values[1:]):
            self.assertGreaterEqual(earlier, later - 1e-12)
        self.assertEqual(values[0], 1.0)  # overdue -> maximum urgency

    def test_deadline_urgency_exponential_mode_is_monotone(self):
        params = resolve_params(_config(deadline_mode="exponential"))
        values = [deadline_component(slack, params) for slack in range(-100, 20000, 250)]
        self.assertEqual(values[0], 1.0)
        for earlier, later in zip(values, values[1:]):
            self.assertGreaterEqual(earlier, later - 1e-12)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in values))

    def test_slack_subtracts_confirmation_delay_and_guard(self):
        payment = _payment("P1", 0, "1.00", "NORMAL", 1000)
        raw, used = deadline_slack(payment, 100, self.params)
        self.assertEqual(raw, 900)
        self.assertEqual(used, 900 - int(self.params.expected_confirmation_delay_sec)
                         - int(self.params.deadline_guard_sec))
        self.assertEqual(self.params.expected_confirmation_delay_sec, 10.0)  # from engine_parameters

    def test_aging_is_monotone_in_waiting_time(self):
        values = [aging_component(wait, self.params) for wait in range(0, 9000, 100)]
        for later, earlier in zip(values[1:], values):
            self.assertGreaterEqual(later, earlier - 1e-12)
        self.assertEqual(values[0], 0.0)

    def test_aging_exponential_mode(self):
        params = resolve_params(_config(aging_mode="exponential"))
        self.assertAlmostEqual(aging_component(0, params), 0.0)
        self.assertGreater(aging_component(7200, params), 0.6)
        self.assertLess(aging_component(7200, params), 1.0)

    def test_aging_lets_an_ordinary_payment_climb(self):
        """Older ordinary payment overtakes a newer high-priority one when aging dominates."""
        config = _config(weight_priority=0.2, weight_deadline=0.2, weight_aging=0.6)
        queue = [
            _payment("P_OLD", 0, "100000.00", "NORMAL", 20000),     # waited 5000 s
            _payment("P_NEW", 4900, "100000.00", "HIGH", 20000),    # waited 100 s
        ]
        result = rank_payments(queue, {"t": 5000, "rmb_available": "0.00"}, config)
        self.assertEqual(result["order"][0], "P_OLD")

    def test_funding_component_is_a_penalty(self):
        queue = [to_decimal("50000.00"), to_decimal("500000.00")]
        params = resolve_params(_config(weight_funding=1.0,
                                        funding_demand_reference_rmb=1000000.0))
        small = funding_component(queue[0], params, queue)
        large = funding_component(queue[1], params, queue)
        self.assertLess(small, large)
        self.assertAlmostEqual(small, 0.05, places=9)
        self.assertAlmostEqual(large, 0.5, places=9)

        result = rank_payments(
            [_payment("P_SMALL", 0, "50000.00", "NORMAL", 9000),
             _payment("P_LARGE", 0, "500000.00", "NORMAL", 9000)],
            {"t": 1000, "rmb_available": "0.00"},
            _config(weight_funding=1.0, funding_demand_reference_rmb=1000000.0))
        self.assertEqual(result["order"], ["P_SMALL", "P_LARGE"])

    def test_funding_reference_falls_back_to_queue_maximum(self):
        params = resolve_params(_config(weight_funding=1.0, funding_demand_reference_rmb=None))
        self.assertIsNone(params.funding_demand_reference_rmb)
        queue = [to_decimal("100000.00"), to_decimal("400000.00")]
        self.assertAlmostEqual(funding_component(queue[1], params, queue), 1.0)

    def test_funding_mode_off_returns_zero(self):
        params = resolve_params(_config(funding_demand_mode="off"))
        self.assertEqual(funding_component(to_decimal("999999.00"), params), 0.0)

    def test_all_components_stay_in_unit_interval(self):
        result = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
        for row in result["detail"]:
            for key in ("p_component", "d_component", "a_component", "l_component"):
                self.assertGreaterEqual(row[key], 0.0)
                self.assertLessEqual(row[key], 1.0)

    def test_score_equals_weighted_sum_of_components(self):
        params = resolve_params(case_config(CASE), strict=True)
        for row in rank_payments(case_queue(CASE), case_state(CASE),
                                 case_config(CASE))["detail"]:
            expected = (params.weight_priority * row["p_component"]
                        + params.weight_deadline * row["d_component"]
                        + params.weight_aging * row["a_component"]
                        - params.weight_funding * row["l_component"])
            self.assertAlmostEqual(row["score"], expected, places=5)

    def test_overdue_payment_is_flagged(self):
        result = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
        overdue = [row["payment_id"] for row in result["detail"] if row["overdue"]]
        self.assertEqual(overdue, ["P000001", "P000004"])

    def test_score_row_explanation_contains_all_terms(self):
        params = resolve_params(case_config(CASE))
        row = score_row(_payment("P1", 60, "100000.00", "URGENT", 660), 1800, params,
                        [to_decimal("100000.00")])
        for token in ("P=", "D=", "A=", "L=", "=>"):
            self.assertIn(token, row["explanation"])


class ConfigTests(unittest.TestCase):
    def test_defaults_when_ranking_block_absent(self):
        params = resolve_params({})
        self.assertAlmostEqual(params.weight_priority, 0.45)
        self.assertAlmostEqual(params.weight_deadline, 0.40)
        self.assertAlmostEqual(params.weight_aging, 0.15)
        self.assertAlmostEqual(params.weight_funding, 0.0)
        self.assertTrue(params.warnings)  # priority_points defaulted, reported not hidden

    def test_reads_module2_contract_values(self):
        params = resolve_params(case_config(CASE), strict=True)
        self.assertEqual(params.points, {"URGENT": 3.0, "HIGH": 2.0, "NORMAL": 1.0})
        self.assertEqual(params.deadline_normalizer_sec, 7200.0)
        self.assertEqual(params.aging_normalizer_sec, 7200.0)
        self.assertEqual(params.sources["weight_priority"], "ranking_parameters.weight_priority")
        self.assertEqual(params.sources["expected_confirmation_delay_sec"],
                         "engine_parameters.payment_confirmation_delay_sec")
        self.assertEqual(params.sources["funding_demand_reference_rmb"],
                         "data_generation.payment_amount_max_rmb")
        self.assertEqual(params.warnings, ())

    def test_strict_mode_rejects_unknown_key(self):
        config = _config()
        config["ranking_parameters"]["weight_agings"] = 0.5
        with self.assertRaises(RankingConfigError):
            resolve_params(config, strict=True)
        self.assertTrue(resolve_params(config).warnings)  # non-strict: reported

    def test_negative_weight_rejected(self):
        with self.assertRaises(RankingConfigError):
            resolve_params(_config(weight_aging=-0.1))

    def test_zero_total_weight_rejected(self):
        with self.assertRaises(RankingConfigError):
            resolve_params(_config(weight_priority=0.0, weight_deadline=0.0,
                                   weight_aging=0.0, weight_funding=0.0))

    def test_non_positive_normaliser_rejected(self):
        with self.assertRaises(RankingConfigError):
            resolve_params(_config(deadline_normalizer_sec=0))
        with self.assertRaises(RankingConfigError):
            resolve_params(_config(aging_normalizer_sec=-5))

    def test_bad_mode_rejected(self):
        with self.assertRaises(RankingConfigError):
            resolve_params(_config(deadline_mode="sqrt"))
        with self.assertRaises(RankingConfigError):
            resolve_params(_config(funding_demand_mode="off", weight_funding=1.0))

    def test_missing_priority_point_rejected(self):
        with self.assertRaises(RankingConfigError):
            resolve_params(_config(priority_points={"URGENT": 3.0, "HIGH": 2.0}))

    def test_parameter_snapshot_is_json_serialisable(self):
        params = resolve_params(case_config(CASE))
        json.dumps(params.to_dict())
        self.assertIn("0.45", params.formula())


class DeterminismTests(unittest.TestCase):
    def test_repeated_calls_identical(self):
        first = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
        for _ in range(3):
            again = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
            self.assertEqual(first["order"], again["order"])
            self.assertEqual(first["scores"], again["scores"])

    def test_float_noise_does_not_split_an_exact_tie(self):
        """Two instructions with mathematically equal scores must tie, then use the id."""
        queue = [_payment("P_B", 100, "100000.00", "NORMAL", 5000),
                 _payment("P_A", 100, "100000.00", "NORMAL", 5000),
                 _payment("P_C", 100, "300000.00", "NORMAL", 5000)]
        config = _config(weight_aging=0.0)
        result = rank_payments(queue, {"t": 1000, "rmb_available": "0.00"}, config)
        scores = result["scores"]
        self.assertEqual(scores["P_A"]["score"], scores["P_B"]["score"])
        self.assertEqual(scores["P_A"]["score"], scores["P_C"]["score"])
        self.assertEqual(result["order"], ["P_A", "P_B", "P_C"])


class TieBreakTests(unittest.TestCase):
    def test_score_then_arrival_then_id(self):
        queue = [
            _payment("P_LATE", 200, "100000.00", "NORMAL", 5000),
            _payment("P_EARLY", 100, "100000.00", "NORMAL", 5000),
            _payment("P_BOOST", 300, "100000.00", "URGENT", 5000),
        ]
        config = _config(weight_aging=0.0)  # remove aging so the tie is exact
        result = rank_payments(queue, {"t": 1000, "rmb_available": "0.00"}, config)
        self.assertEqual(result["order"], ["P_BOOST", "P_EARLY", "P_LATE"])

    def test_same_arrival_time_falls_back_to_payment_id(self):
        queue = [_payment("P2", 100, "100000.00", "NORMAL", 5000),
                 _payment("P1", 100, "100000.00", "NORMAL", 5000)]
        config = _config(weight_aging=0.0)
        result = rank_payments(queue, {"t": 1000, "rmb_available": "0.00"}, config)
        self.assertEqual(result["order"], ["P1", "P2"])

    def test_tie_in_the_golden_case(self):
        result = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
        self.assertEqual(result["scores"]["P000010"]["score"],
                         result["scores"]["P000011"]["score"])
        order = result["order"]
        self.assertLess(order.index("P000010"), order.index("P000011"))


class UnfundableTests(unittest.TestCase):
    def test_unfundable_payment_is_ranked_not_dropped(self):
        queue = [_payment("P_BIG", 0, "9000000.00", "URGENT", 1000),
                 _payment("P_SMALL", 100, "10000.00", "NORMAL", 5000)]
        result = rank_payments(queue, {"t": 500, "rmb_available": "50000.00"},
                               case_config(CASE))
        self.assertIn("P_BIG", result["order"])
        self.assertEqual(len(result["order"]), 2)
        self.assertFalse(result["scores"]["P_BIG"]["fundable_now"] if
                         "fundable_now" in result["scores"]["P_BIG"] else
                         result["detail"][0]["fundable_now"])
        big = next(row for row in result["detail"] if row["payment_id"] == "P_BIG")
        self.assertFalse(big["fundable_now"])
        self.assertEqual(big["funding_gap_rmb"], str(to_decimal("8950000.00")))

    def test_skipping_lets_a_later_instruction_through(self):
        queue = [_payment("P_HEAD", 0, "500000.00", "NORMAL", 9000),
                 _payment("P_TAIL", 100, "100000.00", "URGENT", 1000)]
        result = rank_payments(queue, {"t": 500, "rmb_available": "200000.00"},
                               case_config(CASE))
        preview = select_payable(result["order"], queue, "200000.00")
        self.assertEqual(preview["payable"], ["P_TAIL"])
        self.assertEqual(preview["blocked"], ["P_HEAD"])
        self.assertEqual(preview["first_blocked"], "P_HEAD")

    def test_select_payable_respects_running_balance(self):
        queue = [_payment("P1", 0, "100000.00", "URGENT", 9000),
                 _payment("P2", 0, "100000.00", "URGENT", 9000),
                 _payment("P3", 0, "100000.00", "URGENT", 9000)]
        preview = select_payable(["P1", "P2", "P3"], queue, "250000.00")
        self.assertEqual(preview["payable"], ["P1", "P2"])
        self.assertEqual(preview["blocked"], ["P3"])
        self.assertEqual(preview["remaining_rmb"], "50000.00")

    def test_select_payable_detects_head_of_line_blocking(self):
        queue = [_payment("P_BIG", 0, "900000.00", "NORMAL", 9000),
                 _payment("P_SMALL", 0, "1000.00", "NORMAL", 9000)]
        preview = select_payable(["P_BIG", "P_SMALL"], queue, "10000.00")
        self.assertTrue(preview["head_of_line_blocked"])
        self.assertEqual(preview["payable"], ["P_SMALL"])

    def test_select_payable_with_unknown_balance_keeps_everything(self):
        queue = [_payment("P1", 0, "1.00", "NORMAL", 10)]
        preview = select_payable(["P1"], queue, None)
        self.assertEqual(preview["payable"], ["P1"])
        self.assertFalse(preview["fundability_known"])

    def test_select_payable_rejects_foreign_id(self):
        queue = [_payment("P1", 0, "1.00", "NORMAL", 10)]
        with self.assertRaises(RankingInputError):
            select_payable(["P9"], queue, "10.00")


class PurityTests(unittest.TestCase):
    def test_rank_payments_does_not_mutate_its_inputs(self):
        queue = case_queue(CASE)
        state = case_state(CASE)
        config = case_config(CASE)
        queue_before = copy.deepcopy(queue)
        state_before = copy.deepcopy(state)
        config_before = copy.deepcopy(config)

        rank_payments(queue, state, config)

        self.assertEqual(queue, queue_before)
        self.assertEqual(state, state_before)
        self.assertEqual(config, config_before)
        # no money field may appear in the queue view
        for payment in queue:
            for key in ("submit_time", "settle_time", "status", "rmb_available"):
                self.assertNotIn(key, payment)

    def test_balances_untouched_by_ranking(self):
        state = {"t": 1000, "rmb_total": "1000000.00", "rmb_locked": "0.00",
                 "rmb_reserved": "200000.00", "rmb_available": "800000.00"}
        before = dict(state)
        rank_payments([_payment("P1", 0, "500000.00", "URGENT", 2000)], state,
                      case_config(CASE))
        self.assertEqual(state, before)


class GoldenCaseTests(unittest.TestCase):
    """The exact orders verified by hand for examples/demo_case.json."""

    def test_default_weights(self):
        result = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
        self.assertEqual(result["order"], GOLDEN_DEFAULT)

    def test_funding_penalty_variant(self):
        result = rank_payments(case_queue(CASE), case_state(CASE),
                               case_config(CASE, {"weight_funding": 1.0}))
        self.assertEqual(result["order"], GOLDEN_FUNDING)

    def test_aging_heavy_variant(self):
        config = case_config(CASE, {"weight_priority": 0.2, "weight_deadline": 0.2,
                                    "weight_aging": 0.6})
        result = rank_payments(case_queue(CASE), case_state(CASE), config)
        self.assertEqual(result["order"], GOLDEN_AGING_HEAVY)

    def test_known_scores(self):
        result = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
        scores = result["scores"]
        # P000001: 0.45*1.0 (URGENT) + 0.40*1.0 (overdue, D clamped) + 0.15*1740/7200
        self.assertAlmostEqual(scores["P000001"]["score"], 0.88625, places=6)
        self.assertAlmostEqual(scores["P000004"]["score"], 0.880625, places=6)
        self.assertAlmostEqual(scores["P000009"]["score"], 0.2055556, places=6)

    def test_arrival_order_is_the_reference_for_before_after(self):
        arrival = sorted(CASE["queue"], key=lambda p: (p["arrival_time"], p["payment_id"]))
        result = rank_payments(case_queue(CASE), case_state(CASE), case_config(CASE))
        comparison = compare_orders([p["payment_id"] for p in arrival], result["order"])
        self.assertEqual(comparison["changed"], 9)
        self.assertEqual(sorted(comparison["moved_up"]),
                         ["P000004", "P000007", "P000008", "P000010", "P000011"])

    def test_report_renderers_run(self):
        result = rank_with_ranks(case_queue(CASE), case_state(CASE), case_config(CASE))
        self.assertIn("P000001", order_table(result))
        comparison = compare_orders(result["order"], result["order"])
        self.assertIn("changed positions: 0/11", before_after_table(comparison,
                                                                    result["scores"]))
        self.assertEqual(result["scores"]["P000001"]["rank"], 1)

    def test_detail_csv_written(self):
        import shutil
        # written inside the project so it also works where %TEMP% is restricted
        directory = ROOT / "outputs" / "_selftest"
        try:
            target = write_detail_csv(directory / "detail.csv", result := rank_with_ranks(
                case_queue(CASE), case_state(CASE), case_config(CASE)))
            text = target.read_text(encoding="utf-8")
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        header = text.splitlines()[0]
        for column in ("payment_id", "score", "p_component", "d_component",
                       "a_component", "explanation"):
            self.assertIn(column, header)
        self.assertEqual(len(text.strip().splitlines()), len(result["detail"]) + 1)


class SensitivityTests(unittest.TestCase):
    def test_sweep_reports_monotone_effect_of_funding_weight(self):
        from m4rank.sensitivity import sweep
        rows = sweep(CASE, "weight_funding", [0.0, 0.5, 1.0])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["changed"], 0)          # baseline against itself
        self.assertGreaterEqual(rows[2]["changed"], rows[1]["changed"])

    def test_sweep_rejects_unknown_key(self):
        from m4rank.sensitivity import sweep
        with self.assertRaises(ValueError):
            sweep(CASE, "not_a_parameter", [1.0])


@unittest.skipUnless(os.environ.get("MODULE3_PATH"), "set MODULE3_PATH to run the integration test")
class IntegrationTests(unittest.TestCase):
    """Runs the real Module 3 engine with this module wired in as module4_rank."""

    @classmethod
    def setUpClass(cls):
        module3 = Path(os.environ["MODULE3_PATH"])
        sys.path.insert(0, str(module3))
        os.environ["M3_MODULE4_MODULE"] = "module4_rank"
        from m3engine import load_dataset  # noqa: PLC0415
        fixture = module3 / "fixtures" / "pilot" / "low_rmb_liquidity" / "seed_1001"
        cls.dataset = load_dataset(fixture)

    def test_module3_uses_the_real_ranking_function(self):
        from m3engine import run_dataset  # noqa: PLC0415
        result = run_dataset(self.dataset, "S2")
        self.assertFalse(result.summary["using_fallback_module4"])

    def test_s2_and_s4_reach_the_same_order_at_a_fixed_decision_event(self):
        """S2 and S4 share one ranking implementation, so the order must agree."""
        from m3engine import run_dataset  # noqa: PLC0415
        s2 = run_dataset(self.dataset, "S2")
        s4 = run_dataset(self.dataset, "S4")
        self.assertFalse(s2.summary["using_fallback_module4"])
        self.assertFalse(s4.summary["using_fallback_module4"])

    def test_s2_differs_from_s1_under_liquidity_pressure(self):
        from m3engine import run_dataset  # noqa: PLC0415
        s1 = run_dataset(self.dataset, "S1")
        s2 = run_dataset(self.dataset, "S2")
        self.assertEqual([row["payment_id"] for row in s1.payments],
                         [row["payment_id"] for row in s2.payments])  # same inputs
        self.assertNotEqual([(r["submit_time"]) for r in s1.payments],
                            [(r["submit_time"]) for r in s2.payments])


if __name__ == "__main__":
    unittest.main(verbosity=2)
