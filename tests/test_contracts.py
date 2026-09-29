"""API를 실행하지 않고 입력·출력 약속을 검사합니다."""
from copy import deepcopy
import unittest

from validation import validate_agent_result, validate_candidates, validate_state


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.analysis = {"summary": "검토 결과", "sources": [{"title": "자료", "url": "https://example.com/document", "page": 1}], "uncertainties": ["매출 미확인"], "is_example": False}
        self.investment = {"decision": "hold", "reason": "추가 확인", "score": None, "sources": [], "is_example": False}
        self.company = {"id": "one", "name": "후보", "description": "설명", "website": "", "is_example": True}

    def test_required_fields_and_own_output_key_only(self):
        validate_agent_result("company", {"company_info": self.analysis})
        cases = [None, {}, {"technology": self.analysis}, {"company_info": self.analysis, "technology": self.analysis}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_agent_result("company", value)
        for key in self.analysis:
            value = deepcopy(self.analysis)
            del value[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_agent_result("technology", {"technology": value})

    def test_unknown_score_stays_none_and_valid_scores_pass(self):
        for score in [None, 0, 52.5, 100]:
            value = {**self.investment, "score": score}
            validate_agent_result("investment", {"investment": value})
            self.assertEqual(value["score"], score)

    def test_invalid_scores_and_decisions_rejected(self):
        for score in [-1, 101, 10 ** 1000, float("nan"), float("inf"), float("-inf"), True, "70", []]:
            with self.subTest(score=score), self.assertRaisesRegex(ValueError, "score"):
                validate_agent_result("investment", {"investment": {**self.investment, "score": score}})
        for decision in ["buy", None, True, []]:
            with self.subTest(decision=decision), self.assertRaisesRegex(ValueError, "decision"):
                validate_agent_result("investment", {"investment": {**self.investment, "decision": decision}})

    def test_source_page_and_optional_date(self):
        for page in [None, 1, 100]:
            value = deepcopy(self.analysis)
            value["sources"][0]["page"] = page
            validate_agent_result("technology", {"technology": value})
        for page in [0, -1, True, 1.5, "2"]:
            value = deepcopy(self.analysis)
            value["sources"][0]["page"] = page
            with self.subTest(page=page), self.assertRaisesRegex(ValueError, "page"):
                validate_agent_result("technology", {"technology": value})
        for published_at in [None, "2026-09-29"]:
            value = deepcopy(self.analysis)
            value["sources"][0]["published_at"] = published_at
            validate_agent_result("technology", {"technology": value})
        value["sources"][0]["published_at"] = 2026
        with self.assertRaisesRegex(ValueError, "published_at"):
            validate_agent_result("technology", {"technology": value})
        for field in ["title", "url"]:
            value = deepcopy(self.analysis)
            value["sources"][0][field] = "  "
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "비어"):
                validate_agent_result("technology", {"technology": value})

    def test_strict_booleans_and_analysis_types(self):
        for marker in [1, 0, "false", None]:
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, "is_example"):
                validate_agent_result("company", {"company_info": {**self.analysis, "is_example": marker}})
        for changes in [{"summary": 1}, {"sources": {}}, {"uncertainties": "미확인"}, {"uncertainties": [None]}, {"extra": "unknown"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_agent_result("market_competition", {"market_competition": {**self.analysis, **changes}})

    def test_report_and_candidate_contracts(self):
        validate_agent_result("report", {"report": {"summary": "요약", "markdown": "# SUMMARY", "is_example": True}})
        with self.assertRaises(ValueError):
            validate_agent_result("report", {"report": {"summary": "요약", "markdown": None, "is_example": True}})
        for candidates in [[], {}, [self.company, self.company], [{**self.company, "is_example": 1}], [{**self.company, "id": ""}]]:
            with self.subTest(candidates=candidates), self.assertRaises(ValueError):
                validate_candidates(candidates)

    def test_state_checks_candidate_identity_and_history(self):
        state = {"domain": "Physical AI", "candidates": [self.company], "candidate_index": 0, "company": deepcopy(self.company), "history": []}
        validate_state(state)
        state["company"]["id"] = "different"
        with self.assertRaisesRegex(ValueError, "현재 후보"):
            validate_state(state)
        with self.assertRaisesRegex(ValueError, "history"):
            validate_state({"history": [{}]})
        with self.assertRaisesRegex(ValueError, "candidate_index"):
            validate_state({"candidate_index": True})


if __name__ == "__main__":
    unittest.main()
