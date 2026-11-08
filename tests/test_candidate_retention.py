import copy
import unittest
from unittest.mock import patch

from experiments.candidate_retention import retain_candidates, round_robin_pool
from experiments.query_pilot import ACTIONS
from tests.test_query_pilot import CONFIG, result, results
from tools.analyse_candidate_retention import replay_row, score_replay, target_diagnostics


class CandidateRetentionTests(unittest.TestCase):
    def test_round_robin_skips_shared_ids_without_wasting_turn(self):
        rows = {"original": result(["a", "b", "c"]), "identifiers": result(["a", "d", "e"])}
        self.assertEqual(round_robin_pool(rows, ("identifiers",), 4), ["a", "d", "b", "e"])

    def test_membership_changes_but_final_order_uses_same_rrf(self):
        rows = {"original": result(["a", "b", "c"]), "identifiers": result(["a", "d", "e"])}
        output = retain_candidates(rows, ("identifiers",), 2, 60)
        self.assertEqual(output["rrf"], ["a", "b"])
        self.assertEqual(output["round_robin"], ["a", "d"])
        self.assertEqual(output["round_robin"], [x for x in output["full_rrf"] if x in {"a", "d"}])

    def test_no_actions_is_identical_to_baseline(self):
        output = retain_candidates(results(), (), 2, 60)
        self.assertEqual(output["rrf"], output["round_robin"])

    def test_empty_and_exhausted_lists_and_zero_cap(self):
        rows = {"original": result([]), "identifiers": result(["a", "b"]), "code": result([])}
        self.assertEqual(round_robin_pool(rows, ("identifiers", "code"), 10), ["a", "b"])
        self.assertEqual(round_robin_pool(rows, ("identifiers",), 0), [])
        self.assertEqual(round_robin_pool({"original": result([])}, (), 10), [])

    def test_invalid_actions_and_duplicates_fail(self):
        for choice, cap in ((("identifiers", "identifiers"), 2), (("gold",), 2), ((), -1)):
            with self.assertRaises(ValueError):
                round_robin_pool(results(), choice, cap)
        rows = results()
        rows["original"] = result(["a", "a"])
        with self.assertRaises(ValueError):
            round_robin_pool(rows, (), 2)

    def test_selection_order_is_canonical_and_inputs_unchanged(self):
        rows = results()
        before = copy.deepcopy(rows)
        self.assertEqual(round_robin_pool(rows, ("code", "identifiers"), 3),
                         round_robin_pool(rows, ("identifiers", "code"), 3))
        self.assertEqual(rows, before)

    def test_replay_reads_no_files_and_never_invokes_gold(self):
        trace = {"instance_id": "x", "repo": "o/r", "base_commit": "abc", "status": "ok", "actions": results()}
        with patch("builtins.open", side_effect=AssertionError("No file IO allowed")), \
             patch("tools.analyse_candidate_retention.gold_targets", side_effect=AssertionError("Gold accessed")):
            replayed = replay_row(trace, CONFIG)
        self.assertTrue(replayed["options"])
        for option in replayed["options"]:
            self.assertLessEqual(len(option["rrf"]), CONFIG["candidate_cap"])
            self.assertLessEqual(len(option["round_robin"]), CONFIG["candidate_cap"])
            self.assertEqual(len(option["round_robin"]), len(set(option["round_robin"])))
            self.assertLessEqual(option["cost"]["retrieval_calls"], CONFIG["max_retrieval_calls"])

    def test_diagnostic_distinguishes_missing_action_and_truncation(self):
        trace = {"instance_id": "x", "repo": "o/r", "base_commit": "abc", "status": "ok", "actions": results()}
        replayed = replay_row(trace, {**CONFIG, "candidate_cap": 1})
        diagnostic = target_diagnostics(trace, replayed, {"target"}, {**CONFIG, "candidate_cap": 1})[0]
        original = next(x for x in diagnostic["options"] if x["selected_actions"] == [])
        code = next(x for x in diagnostic["options"] if x["selected_actions"] == ["code"])
        self.assertEqual(original["rrf_loss_stage"], "not_in_selected_action_returns")
        self.assertEqual(code["rrf_loss_stage"], "fusion_truncation")
        self.assertAlmostEqual(code["rrf_contributions"]["code"], 1/61)
        self.assertIsNone(code["rrf_retained_rank"])

    def test_scores_keep_failures_and_absent_targets(self):
        trace = {"instance_id": "x", "repo": "o/r", "base_commit": "abc", "status": "error", "actions": {}}
        replayed = replay_row(trace, CONFIG)
        scored = score_replay(trace, replayed, {"absent"}, CONFIG)
        self.assertTrue(scored["scorable"])
        self.assertTrue(all(arm["coverage"] == 0 for arm in scored["arms"].values()))
        self.assertFalse(score_replay(trace, replayed, set(), CONFIG)["scorable"])

    def test_changing_labels_changes_only_offline_scoring(self):
        trace = {"instance_id": "x", "repo": "o/r", "base_commit": "abc", "status": "ok", "actions": results()}
        replayed = replay_row(trace, CONFIG)
        frozen = copy.deepcopy(replayed)
        score_replay(trace, replayed, {"a"}, CONFIG)
        score_replay(trace, replayed, {"target", "absent"}, CONFIG)
        self.assertEqual(replayed, frozen)


if __name__ == "__main__":
    unittest.main()
