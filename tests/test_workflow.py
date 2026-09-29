"""API 없이 평가 무결성과 실제 그래프 분기/종료를 검증한다."""
import copy
import unittest
from unittest.mock import patch

from agents.analysis import SECTIONS, load_demo_candidates, run_analysis
from agents.evaluation import evaluate_candidate
from app import build_graph


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.candidate = load_demo_candidates()[0]
        self.analyses = [run_analysis(self.candidate, section, "demo") for section in SECTIONS]

    def complete_analyses(self, value=4):
        analyses = copy.deepcopy(self.analyses)
        for analysis in analyses:
            for score in analysis["scores"].values():
                score.update(value=value, evidence_ids=[analysis["evidence"][0]["id"]])
        return analyses

    def test_unknown_is_not_zero_or_renormalized(self):
        result = evaluate_candidate(self.candidate, self.analyses)
        self.assertEqual(result["decision"], "hold")
        self.assertIsNone(result["weighted_score"])
        self.assertIsNone(result["scores"]["founder"]["value"])
        self.assertAlmostEqual(result["coverage"], .6)
        zeros = evaluate_candidate(self.candidate, self.complete_analyses(0))
        self.assertEqual(zeros["weighted_score"], 0)
        self.assertEqual(zeros["coverage"], 1)

    def test_boundary_and_eligibility(self):
        result = evaluate_candidate(self.candidate, self.complete_analyses(3.5))
        self.assertEqual(result["weighted_score"], 70)
        self.assertEqual(result["decision"], "invest")
        self.assertIn("팀 검토", result["reason"])
        unverified = dict(self.candidate, eligibility="unverified")
        self.assertEqual(evaluate_candidate(unverified, self.complete_analyses())["decision"], "hold")

    def test_rejects_wrong_candidate_and_unknown_reference(self):
        for change in ("analysis_candidate", "evidence_candidate", "unknown_ref"):
            with self.subTest(change=change):
                data = copy.deepcopy(self.analyses)
                if change == "analysis_candidate":
                    data[0]["candidate_id"] = "another"
                elif change == "evidence_candidate":
                    data[0]["evidence"][0]["candidate_id"] = "another"
                else:
                    data[0]["scores"]["traction"]["evidence_ids"] = ["missing"]
                with self.assertRaises(ValueError):
                    evaluate_candidate(self.candidate, data)

    def test_rejects_invalid_scores_and_duplicate_items(self):
        for value in (-1, 6, float("nan"), float("inf"), True, "4"):
            with self.subTest(value=value):
                data = copy.deepcopy(self.analyses)
                data[0]["scores"]["traction"]["value"] = value
                with self.assertRaises(ValueError):
                    evaluate_candidate(self.candidate, data)
        for change in ("unknown_key", "duplicate_key", "duplicate_evidence", "no_reference"):
            with self.subTest(change=change):
                data = copy.deepcopy(self.analyses)
                if change == "unknown_key":
                    data[0]["scores"]["invented"] = data[0]["scores"]["traction"]
                elif change == "duplicate_key":
                    data[1]["scores"]["traction"] = data[0]["scores"]["traction"]
                elif change == "duplicate_evidence":
                    data[1]["evidence"].append(data[0]["evidence"][0])
                else:
                    data[0]["scores"]["traction"]["evidence_ids"] = []
                with self.assertRaises(ValueError):
                    evaluate_candidate(self.candidate, data)

    def test_all_hold_terminates_and_reports_once(self):
        calls = []
        def report(state):
            calls.append(state)
            return {"report_paths": {"markdown": "demo.md"}}
        result = build_graph(report).invoke({"candidates": load_demo_candidates(),
            "candidate_index": 0, "evaluations": [], "mode": "demo"})
        self.assertEqual(len(result["evaluations"]), 2)
        self.assertTrue(all(item["decision"] == "hold" for item in result["evaluations"]))
        self.assertEqual(result["candidate_index"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["report_paths"]["markdown"], "demo.md")

    def test_invest_stops_before_second_candidate(self):
        complete = {item["section"]: item for item in self.complete_analyses()}
        with patch("agents.analysis.run_analysis", side_effect=lambda candidate, section, mode: complete[section]):
            result = build_graph(lambda state: {"report_paths": {}}).invoke({
                "candidates": load_demo_candidates(), "candidate_index": 0,
                "evaluations": [], "mode": "demo"})
        self.assertEqual(len(result["evaluations"]), 1)
        self.assertEqual(result["latest_decision"], "invest")

    def test_live_mode_is_explicitly_unimplemented(self):
        with self.assertRaises(NotImplementedError):
            build_graph(lambda state: {}).invoke({"candidates": load_demo_candidates(), "mode": "live"})
        with self.assertRaises(NotImplementedError):
            run_analysis(self.candidate, "company", "live")

    def test_empty_candidates_reports_without_analysis(self):
        result = build_graph(lambda state: {"report_paths": {}}).invoke({
            "candidates": [], "candidate_index": 0, "evaluations": [], "mode": "demo"})
        self.assertEqual(result["evaluations"], [])


if __name__ == "__main__":
    unittest.main()
