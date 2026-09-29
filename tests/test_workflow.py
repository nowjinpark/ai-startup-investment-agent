"""연결만 시험합니다. 5개 run을 모두 대체하여 실제 API를 호출하지 않습니다."""
from contextlib import ExitStack
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import main
from shared import AGENT_KEYS


def analysis(summary, is_example=False):
    return {"summary": summary, "sources": [], "uncertainties": [], "is_example": is_example}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.state = json.loads((main.ROOT / "data" / "test_state.json").read_text(encoding="utf-8"))
        self.candidates = deepcopy(self.state["candidates"])
        for candidate in self.candidates:
            candidate["is_example"] = False
        self.calls = []
        self.inputs = []
        self.decisions = {}
        self.overrides = {}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # 본문이 실제 AI 구현으로 바뀌어도 이 테스트에서는 전혀 실행하지 않습니다.
        for name in AGENT_KEYS:
            module = getattr(main, name)
            self.stack.enter_context(patch.object(module, "run", side_effect=self.stub(name)))

    def stub(self, name):
        def run(state):
            company_id = state.get("company", {}).get("id")
            self.calls.append((name, company_id))
            self.inputs.append((name, deepcopy(state)))
            if name in self.overrides:
                return self.overrides[name](state)
            if name == "investment":
                return {"investment": {"decision": self.decisions.get(company_id, "hold"), "reason": "시험 판단", "score": None, "sources": [], "is_example": False}}
            if name == "report":
                return {"report": {"summary": "시험 보고서", "markdown": "# SUMMARY\n시험\n# REFERENCE", "is_example": False}}
            return {AGENT_KEYS[name]: analysis(f"{company_id} {name}")}
        return run

    def invoke(self, candidates=None):
        candidates = self.candidates if candidates is None else candidates
        return main.build_graph().invoke(main.prepare_state(candidates), {"recursion_limit": 6 * len(candidates) + 5})

    def test_five_agents_in_order_and_stop_on_invest(self):
        first_id = self.candidates[0]["id"]
        self.decisions[first_id] = "invest"
        result = self.invoke()
        self.assertEqual([name for name, _ in self.calls], list(AGENT_KEYS))
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["investment"]["decision"], "invest")
        self.assertFalse(result["report"]["is_example"])

    def test_hold_moves_to_next_company_then_invest_stops(self):
        third = {**self.candidates[1], "id": "third", "name": "세 번째"}
        self.decisions[self.candidates[1]["id"]] = "invest"
        result = self.invoke([*self.candidates, third])
        expected = ["company", "technology", "market_competition", "investment"] * 2 + ["report"]
        self.assertEqual([name for name, _ in self.calls], expected)
        self.assertEqual([record["company"]["id"] for record in result["history"]], [item["id"] for item in self.candidates])
        self.assertEqual(result["candidate_index"], 1)

    def test_all_hold_ends_with_one_report(self):
        result = self.invoke()
        self.assertEqual(len(result["history"]), 2)
        self.assertEqual([name for name, _ in self.calls].count("report"), 1)
        self.assertTrue(all(record["investment"]["decision"] == "hold" for record in result["history"]))
        self.assertTrue(all(record["investment"]["score"] is None for record in result["history"]))

    def test_new_company_does_not_receive_previous_analysis(self):
        result = self.invoke()
        second_input = [state for name, state in self.inputs if name == "company"][1]
        for key in ["company_info", "technology", "market_competition"]:
            self.assertEqual(second_input[key], main.empty_analysis())
        self.assertEqual(second_input["investment"]["reason"], "")
        self.assertIsNone(second_input["investment"]["score"])
        self.assertEqual(len(second_input["history"]), 1)
        self.assertIn(self.candidates[0]["id"], result["history"][0]["technology"]["summary"])
        self.assertIn(self.candidates[1]["id"], result["history"][1]["technology"]["summary"])

    def test_agent_cannot_mutate_other_results(self):
        def mutate_input(state):
            state["company_info"]["summary"] = "덮어쓰기 시도"
            state["company"]["name"] = "변경 시도"
            state["history"].clear()
            return {"technology": analysis("기술 결과")}
        self.overrides["technology"] = mutate_input
        result = self.invoke()
        self.assertEqual(len(result["history"]), 2)
        self.assertEqual(result["history"][0]["company"]["name"], self.candidates[0]["name"])
        self.assertNotIn("덮어쓰기", result["history"][0]["company_info"]["summary"])

    def test_invalid_return_stops_at_named_agent(self):
        self.overrides["technology"] = lambda state: {"company_info": analysis("다른 담당자의 키")}
        with self.assertRaisesRegex(ValueError, "technology agent"):
            self.invoke()
        self.assertEqual([name for name, _ in self.calls], ["company", "technology"])

    def test_example_marker_propagates_from_first_company_to_report(self):
        self.candidates[0]["is_example"] = True
        result = self.invoke()
        for key in ["company_info", "technology", "market_competition", "investment"]:
            self.assertTrue(result["history"][0][key]["is_example"])
            self.assertFalse(result["history"][1][key]["is_example"])
        self.assertTrue(result["report"]["is_example"])

    def test_single_agent_ignores_downstream_example_markers(self):
        state = deepcopy(self.state)
        state["company"]["is_example"] = False
        state["candidates"][0]["is_example"] = False
        state["company_info"]["is_example"] = False
        result = main.run_agent("technology", main.technology.run, state)
        self.assertFalse(result["technology"]["is_example"])
        result = main.run_agent("company", main.company.run, state)
        self.assertFalse(result["company_info"]["is_example"])
        state["company_info"]["is_example"] = True
        result = main.run_agent("technology", main.technology.run, state)
        self.assertTrue(result["technology"]["is_example"])

    def test_report_keeps_history_example_marker(self):
        state = deepcopy(self.state)
        state["company"]["is_example"] = False
        state["candidates"][0]["is_example"] = False
        for key in ["company_info", "technology", "market_competition", "investment"]:
            state[key]["is_example"] = False
        result = main.run_agent("report", main.report.run, state)
        self.assertTrue(result["report"]["is_example"])

    def test_prepare_state_rejects_empty_and_duplicate_candidates(self):
        with self.assertRaises(ValueError):
            main.prepare_state([])
        with self.assertRaisesRegex(ValueError, "중복"):
            main.prepare_state([self.candidates[0], self.candidates[0]])


if __name__ == "__main__":
    unittest.main()
