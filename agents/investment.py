import json
import math
import re
from datetime import date
from pathlib import Path

from common import compact


RUBRIC = json.loads(
    (Path(__file__).resolve().parents[1] / "config/rubric.json").read_text(
        encoding="utf-8"
    )
)
ELIGIBILITY = {
    "domestic": "국내 기업",
    "unlisted": "비상장",
    "stage": "Seed~Series C",
    "no_exit": "Exit 미완료",
    "physical_ai": "Physical AI 분야",
}


def _text(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def _list(value):
    return value if isinstance(value, list) else []


def _source_index(candidate, technology, market):
    index, conflicts = {}, set()
    for record in (candidate, technology, market):
        for source in _list(record.get("sources")):
            if not isinstance(source, dict):
                continue
            key = source.get("source_id")
            if not isinstance(key, str) or not key or not _text(source.get("text")):
                continue
            previous = index.get(key)
            if previous and (
                previous.get("company_id"),
                compact(previous.get("text")),
                previous.get("url"),
            ) != (
                source.get("company_id"),
                compact(source.get("text")),
                source.get("url"),
            ):
                conflicts.add(key)
            index[key] = source
    for key in conflicts:
        index.pop(key, None)
    return index


def _discovery_page_pair(item, items, source, sources, names):
    """쪽 끝의 기업 제목과 바로 다음 쪽의 연속 본문 인용을 함께 확인합니다."""
    page_key = "rendered_page" if source.get("rendered_page") else "original_page"
    page, url = source.get(page_key), source.get("url")
    body = compact(item.get("quote"))
    if type(page) is not int or page < 2 or not url or not body:
        return False
    text = source.get("text", "")
    # 본문 앞부분을 생략하면 중간의 다른 기업 제목·카드 경계를 놓칠 수 있습니다.
    if not compact(text).startswith(body):
        return False
    if re.search(r"상세내용\s*닫기|</article>", item.get("quote", ""), re.I):
        return False
    normalized_names = {compact(name).casefold() for name in names if _text(name)}
    for anchor in items:
        if (
            not isinstance(anchor, dict)
            or not isinstance(anchor.get("source_id"), str)
            or not isinstance(anchor.get("quote"), str)
        ):
            continue
        previous = sources.get(anchor.get("source_id"))
        if not previous or previous.get("company_id") != "__discovery__":
            continue
        if previous.get("url") != url or previous.get(page_key) != page - 1:
            continue
        prior_text = previous.get("text", "")
        lines = [line for line in prior_text.splitlines() if compact(line)]
        # 제목 이후의 소속이 불명확한 구간은 허용하지 않습니다.
        if not lines or compact(lines[-1]).casefold() not in normalized_names:
            continue
        quote = compact(anchor.get("quote"))
        if (
            quote
            and compact(prior_text).endswith(quote)
            and compact(lines[-1]) in quote
        ):
            return True
    return False


def _evidence(items, sources, company_id, criterion_id=None, names=()):
    if not isinstance(items, list) or not items:
        return [], "출처와 원문 인용이 없습니다."
    clean = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            return [], "출처 형식이 올바르지 않습니다."
        source_id, quote = item.get("source_id"), _text(item.get("quote"))
        if not isinstance(source_id, str) or not quote:
            return [], "출처 ID 또는 원문 인용이 비어 있습니다."
        source = sources.get(source_id)
        if not source or compact(quote) not in compact(source.get("text")):
            return [], "등록된 원문에서 인용을 확인하지 못했습니다."
        owner = source.get("company_id")
        allowed = owner == company_id or (
            criterion_id in {1, "comparison", "context"} and owner == "__sector__"
        )
        if criterion_id is None and owner == "__discovery__":
            allowed = any(
                _text(name) and compact(name).casefold() in compact(quote).casefold()
                for name in names
            ) or _discovery_page_pair(item, items, source, sources, names)
        if not allowed:
            return (
                [],
                "현재 기업과 다른 기업의 근거 또는 사용할 수 없는 공통 자료입니다.",
            )
        pair = (source_id, quote)
        if pair not in seen:
            clean.append({"source_id": source_id, "quote": quote})
            seen.add(pair)
    return clean, None


def _explicit_absence(evidence):
    text = " ".join(item["quote"] for item in evidence)
    # 검색되지 않았다는 표현만으로 0건을 확정하지 않습니다.
    if re.search(
        r"확인\s*(?:불가|되지|할\s*수\s*없)|미확인|미공개|자료\s*없|검색.*없|not\s+(?:found|disclosed|available)",
        text,
        re.I,
    ):
        return False
    return bool(
        re.search(
            r"없(?:음|다|습니다|으며|고|는)|0\s*(?:건|곳|개|명)|전무|아직.*않|\b(?:zero|none|no customers|no patents)\b",
            text,
            re.I,
        )
    )


def _comparison_evidence(competitor, sources, company_id):
    evidence, issue = _evidence(
        competitor.get("evidence"), sources, company_id, "comparison"
    )
    if not issue and competitor.get("comparison_kind") == "alternative":
        cited = [sources[e["source_id"]] for e in evidence]
        documents = {s.get("url") or s["source_id"] for s in cited}
        if len(documents) < 2 or not any(
            s.get("company_id") == company_id for s in cited
        ):
            return (
                [],
                "대안 비교에는 대상기업과 대안의 각각 확인된 사실을 두 원문 출처로 제시해야 합니다.",
            )
    return evidence, issue


def _score(rule, finding, evidence):
    value = finding.get(rule["field"])
    alternative = (
        rule.get("alternative_categories", {}).get(finding.get("category_value"))
        if isinstance(finding.get("category_value"), str)
        else None
    )
    if alternative is not None:
        return alternative, None
    if rule["rule"] == "category":
        if not isinstance(value, str) or value not in rule["values"]:
            return None, "허용된 평가 값이 아닙니다."
        if rule["id"] == 3 and value == "none" and not _explicit_absence(evidence):
            return None, "고객 접점이 없다는 명시적 원문 근거가 필요합니다."
        return rule["values"][value], None
    if rule["rule"] == "items":
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            return None, "평가 항목 목록의 형식이 올바르지 않습니다."
        if len(set(value)) != len(value) or not set(value).issubset(rule["allowed"]):
            return None, "허용되지 않거나 중복된 평가 항목입니다."
        value = len(value)
    else:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            return None, "확인 가능한 유한한 숫자가 필요합니다."
        if value < rule.get("minimum", -100) or (
            rule.get("integer") and value != int(value)
        ):
            return None, "평가 수치의 범위 또는 단위가 올바르지 않습니다."
    if rule["id"] in {4, 6, 7, 8} and value == 0 and not _explicit_absence(evidence):
        return None, "0건이라는 명시적 원문 근거가 필요합니다."
    if value >= rule["high"]:
        return 3, None
    if value >= rule["medium"]:
        return 2, None
    return 1, None


def _latest_evidence_date(evidence, sources):
    dates = []
    for item in evidence:
        source = sources.get(item["source_id"], {})
        pattern = r"(20\d{2})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})"
        matches = re.findall(pattern, item["quote"]) or re.findall(
            pattern, str(source.get("published_at") or "")
        )
        for year, month, day in matches:
            try:
                dates.append(date(int(year), int(month), int(day)))
            except ValueError:
                continue
    return max(dates) if dates else None


class _InvestmentEvaluation:
    """기업 한 곳의 평가 상태를 보관하고 검증 단계를 순서대로 실행합니다."""

    def __init__(self, candidate, technology, market, round_id):
        self.candidate = candidate if isinstance(candidate, dict) else {}
        self.technology = technology if isinstance(technology, dict) else {}
        self.market = market if isinstance(market, dict) else {}
        self.round_id = round_id
        self.company_id, self.name = (
            self.candidate.get("company_id"),
            _text(self.candidate.get("name")),
        )
        self.sources = _source_index(self.candidate, self.technology, self.market)
        self.reasons = []
        self.missing = []
        self.used_evidence = []
        self.analyses = {"technology": self.technology, "market": self.market}
        self.details = {
            role: dict(value["details"])
            if isinstance(value.get("details"), dict)
            else {}
            for role, value in self.analyses.items()
        }
        self.valid_analysis = {}

    def run(self):
        self._validate_analyses()
        self._evaluate_criteria()
        self._evaluate_eligibility()
        self._review_technology()
        self._review_market()
        return self._build_result()

    def _validate_analyses(self):
        """분석의 기업·회차·평가기준 버전을 확인합니다."""
        identity_valid = (
            isinstance(self.company_id, str)
            and bool(self.company_id)
            and self.company_id not in {"__sector__", "__discovery__"}
            and isinstance(self.round_id, int)
            and not isinstance(self.round_id, bool)
        )
        if not identity_valid or not self.name:
            self.reasons.append("기업 ID·기업명 또는 분석 회차가 올바르지 않습니다.")
        for role, analysis in self.analyses.items():
            label = "기술" if role == "technology" else "시장·경쟁"
            version_ok = analysis.get("rubric_version") == RUBRIC["version"]
            self.valid_analysis[role] = (
                identity_valid
                and version_ok
                and analysis.get("company_id") == self.company_id
                and type(analysis.get("round_id")) is int
                and analysis["round_id"] == self.round_id
                and analysis.get("status") == "completed"
            )
            if not version_ok:
                self.reasons.append(
                    f"{label} 분석은 평가기준 {RUBRIC['version']}으로 다시 실행해야 합니다."
                )
            if not self.valid_analysis[role]:
                self.reasons.append(
                    f"{label} 분석의 기업·회차·완료 상태가 일치하지 않습니다."
                )
                self.details[role] = {}

    def _evaluate_criteria(self):
        """담당 분석의 원문 근거와 평가표를 대조해 항목별로 채점합니다."""
        self.findings_by_criterion = {}
        for role, analysis in self.analyses.items():
            for finding in _list(analysis.get("findings")):
                if (
                    not isinstance(finding, dict)
                    or type(finding.get("criterion_id")) is not int
                    or finding["criterion_id"] not in range(1, 11)
                ):
                    self.reasons.append(
                        "분석에 형식이 올바르지 않은 평가 항목이 있습니다."
                    )
                    continue
                self.findings_by_criterion.setdefault(
                    finding["criterion_id"], []
                ).append((role, finding))
        self.criteria = []
        for number, rule in enumerate(RUBRIC["criteria"], 1):
            entries = self.findings_by_criterion.get(rule["id"], [])
            finding, evidence, score = {}, [], None
            issue = None
            if len(entries) != 1:
                issue = "평가 항목이 누락되거나 중복되었습니다."
            else:
                role, finding = entries[0]
                if role != rule["owner"] or not self.valid_analysis[role]:
                    issue = "평가 담당 역할 또는 분석 상태가 올바르지 않습니다."
                elif finding.get("status") != "verified":
                    issue = (
                        _text(finding.get("reason")) or "평가 근거가 미확인 상태입니다."
                    )
                else:
                    evidence, issue = _evidence(
                        finding.get("evidence"),
                        self.sources,
                        self.company_id,
                        rule["id"],
                    )
                    if not issue:
                        score, issue = _score(rule, finding, evidence)
            if issue:
                score = None
                self.missing.append(f"{rule['id']}. {rule['name']}: {issue}")
            self.used_evidence.extend(evidence)
            self.criteria.append(
                {
                    "criterion_id": rule["id"],
                    "display_number": number,
                    "name": rule["name"],
                    "grade": RUBRIC["grades"].get(str(score), "미확인"),
                    "score": score,
                    "reason": issue
                    or _text(finding.get("reason"))
                    or "확인된 자료에 평가표 기준을 적용했습니다.",
                    "evidence": evidence,
                }
            )

    def _evaluate_eligibility(self):
        """기업 자격과 법인 동일성, 현재 운영 여부를 확인합니다."""
        eligibility = (
            self.candidate.get("eligibility")
            if isinstance(self.candidate.get("eligibility"), dict)
            else {}
        )
        names = [self.name] + [
            alias
            for alias in _list(self.candidate.get("aliases"))
            if isinstance(alias, str)
        ]
        self.eligibility_checks = {}
        self.eligibility_issues = []
        operating_evidence = []
        for key, label in {
            **ELIGIBILITY,
            "identity": "법인 동일성",
            "operating": "현재 사업 운영",
        }.items():
            check = (
                eligibility.get(key) if key in ELIGIBILITY else self.candidate.get(key)
            )
            check = check if isinstance(check, dict) else {}
            evidence, issue = _evidence(
                check.get("evidence"), self.sources, self.company_id, names=names
            )
            self.used_evidence.extend(evidence)
            status = check.get("status")
            verified = status in {"pass", "fail"} and not issue
            result = status if verified else "unknown"
            explanation = (
                issue or _text(check.get("reason")) or "추가 확인이 필요합니다."
            )
            self.eligibility_checks[key] = {
                "label": label,
                "status": result,
                "reason": explanation,
                "evidence": evidence,
            }
            if result != "pass":
                qualifier = "미충족" if result == "fail" else "미확인"
                self.eligibility_issues.append(
                    f"기업 자격 {qualifier}: {label} — {explanation}"
                )
            elif key == "operating":
                operating_evidence = evidence

        self._check_execution(operating_evidence)
        if any(check["status"] == "fail" for check in self.eligibility_checks.values()):
            self.eligibility_status = "ineligible"
        elif all(
            check["status"] == "pass" for check in self.eligibility_checks.values()
        ):
            self.eligibility_status = "eligible"
        else:
            self.eligibility_status = "pending"

    def _check_execution(self, operating_evidence):
        """사업 중단과 이후 운영 자료의 날짜를 비교합니다."""
        execution = next(item for item in self.criteria if item["criterion_id"] == 10)
        execution_findings = self.findings_by_criterion.get(10, [])
        if (
            execution["score"] is not None
            and execution_findings[0][1].get("category_value") == "stopped"
        ):
            stopped_at = _latest_evidence_date(execution["evidence"], self.sources)
            active_at = _latest_evidence_date(operating_evidence, self.sources)
            if stopped_at and active_at and active_at > stopped_at:
                execution.update(
                    score=None,
                    grade="미확인",
                    reason="과거 사업 중단 이후 운영 자료가 있어 현재 실행 지속성을 다시 확인해야 합니다.",
                )
                self.missing.append(
                    "10. 실행 지속성: 과거 중단과 최근 운영 근거가 충돌합니다."
                )
            else:
                explanation = (
                    "폐업 또는 관련 사업 중단 근거가 확인되어 투자 추천을 보류합니다."
                )
                self.eligibility_checks["operating"] = {
                    "label": "현재 사업 운영",
                    "status": "fail",
                    "reason": explanation,
                    "evidence": execution["evidence"],
                }
                self.eligibility_issues.append(explanation)

    def _review_technology(self):
        """중대한 위험과 정성 분석, 기술·팀 설명의 근거를 확인합니다."""
        risk = self.details["technology"]
        risk_evidence, risk_issue = _evidence(
            risk.get("critical_risk_evidence"),
            self.sources,
            self.company_id,
            criterion_id=9,
        )
        self.used_evidence.extend(risk_evidence)
        self.critical_risk_confirmed = risk.get("critical_risk") is True and (
            not risk_issue
        )
        if self.critical_risk_confirmed:
            self.reasons.append(
                "중대한 미해결 위험: "
                + (
                    _text(risk.get("critical_risk_reason"))
                    or "추가 확인과 대응이 필요합니다."
                )
            )
        if risk_issue:
            risk.update(critical_risk=None, critical_risk_evidence=[])
        self.qualitative_findings = []
        for finding in _list(self.technology.get("qualitative_findings")):
            if not isinstance(finding, dict) or finding.get("criterion_id") not in {
                4,
                5,
                9,
            }:
                continue
            evidence, issue = _evidence(
                finding.get("evidence"),
                self.sources,
                self.company_id,
                finding["criterion_id"],
            )
            if not self.valid_analysis["technology"]:
                evidence, issue = (
                    [],
                    "기술 분석의 기업·회차·완료 상태를 확인해야 합니다.",
                )
            item = dict(finding, evidence=evidence)
            if issue:
                item.update(status="unknown", reason=issue)
            self.qualitative_findings.append(item)
            self.used_evidence.extend(evidence)
        for field in ("technology", "team"):
            evidence_field = field + "_evidence"
            if evidence_field not in risk:
                continue
            evidence, issue = _evidence(
                risk[evidence_field], self.sources, self.company_id, criterion_id=2
            )
            if issue:
                risk[field], risk[evidence_field] = ("확인 필요", [])
            else:
                risk[evidence_field] = evidence
                self.used_evidence.extend(evidence)

    def _review_market(self):
        """시장 규모·비교 대상·산업 배경의 근거를 검증합니다."""
        market_details = self.details["market"]
        size_evidence, size_issue = _evidence(
            market_details.get("market_size_evidence"),
            self.sources,
            self.company_id,
            criterion_id=1,
        )
        if size_issue or not _text(market_details.get("market_size")):
            market_details.update(market_size="확인 필요", market_size_evidence=[])
        else:
            market_details["market_size_evidence"] = size_evidence
            self.used_evidence.extend(size_evidence)
        competitors = []
        for competitor in _list(market_details.get("competitors")):
            if not isinstance(competitor, dict):
                continue
            evidence, issue = _comparison_evidence(
                competitor, self.sources, self.company_id
            )
            if not issue:
                competitors.append({**competitor, "evidence": evidence})
                self.used_evidence.extend(evidence)
        market_details["competitors"] = competitors
        # 산업 공통 위험은 배경 설명으로만 사용하며 점수·중대 위험 판정에 반영하지 않습니다.
        context_risks = []
        for context in _list(market_details.get("context_risks")):
            if not isinstance(context, dict) or not _text(context.get("reason")):
                continue
            evidence, issue = _evidence(
                context.get("evidence"),
                self.sources,
                self.company_id,
                criterion_id="context",
            )
            if issue:
                continue
            context_risks.append(
                {
                    "type": _text(context.get("type")) or "산업 공통",
                    "reason": _text(context["reason"]),
                    "evidence": evidence,
                    "context_only": True,
                }
            )
            self.used_evidence.extend(evidence)
        market_details["context_risks"] = context_risks

    def _build_result(self):
        """총점·자격 판정·실행 상태를 기존 출력 형식으로 구성합니다."""
        known = [item for item in self.criteria if item["score"] is not None]
        coverage = len(known)
        criterion_count = len(self.criteria)
        observed_sum = sum(item["score"] for item in known)
        total = observed_sum if coverage == criterion_count else None
        score_pass = total is not None and total >= RUBRIC["pass_score"]
        if total is None:
            self.reasons.append(
                f"확인된 평가 항목이 {coverage}/{criterion_count}개입니다. 모든 항목의 근거가 있어야 총점을 계산합니다."
            )
        elif not score_pass:
            self.reasons.append(
                f"합계 {total}점으로 통과 기준 {RUBRIC['pass_score']}점에 미달합니다."
            )
        decision = "hold"
        if score_pass and not self.reasons:
            if self.eligibility_status == "eligible":
                decision = "pass"
            elif (
                self.eligibility_status == "pending"
                and RUBRIC.get("eligibility_pending_policy", "hold") == "conditional"
            ):
                decision = "conditional"
        self.reasons = list(dict.fromkeys(self.reasons + self.eligibility_issues))
        used_ids = {item["source_id"] for item in self.used_evidence}
        return {
            "company_id": self.company_id,
            "name": self.name,
            "round_id": self.round_id,
            "rubric_version": RUBRIC["version"],
            "observed_sum": observed_sum,
            "coverage_count": coverage,
            "score_scale": RUBRIC["maximum_score"],
            "criterion_count": criterion_count,
            "pass_score": RUBRIC["pass_score"],
            "score_pass": score_pass,
            "eligibility_status": self.eligibility_status,
            "eligibility_issues": self.eligibility_issues,
            "qualification": self.eligibility_checks,
            "critical_risk_confirmed": self.critical_risk_confirmed,
            "decision": decision,
            "total_score": total,
            "criteria": self.criteria,
            "execution_status": "partial_failure"
            if any(
                a.get("status") == "failed"
                or (
                    a.get("audit_status") == "failed"
                    and (a.get("audit_error") or {}).get("type") != "MissingEvidence"
                )
                for a in self.analyses.values()
            )
            else "completed",
            "analysis_status": {
                role: {
                    "status": a.get("status"),
                    "audit_status": a.get("audit_status"),
                    "error": a.get("error"),
                    "audit_error": a.get("audit_error"),
                }
                for role, a in self.analyses.items()
            },
            "reasons": self.reasons,
            "sources": [
                value for key, value in self.sources.items() if key in used_ids
            ],
            "overview": _text(self.candidate.get("overview")),
            "technology_summary": _text(self.technology.get("summary"))
            if self.valid_analysis["technology"]
            else "",
            "market_summary": _text(self.market.get("summary"))
            if self.valid_analysis["market"]
            else "",
            "details": self.details,
            "qualitative_findings": self.qualitative_findings,
            "missing": list(
                dict.fromkeys(
                    self.missing
                    + [
                        item
                        for analysis in self.analyses.values()
                        for item in _list(analysis.get("missing"))
                        if isinstance(item, str)
                    ]
                )
            ),
            "risks": list(
                dict.fromkeys(
                    item
                    for analysis in self.analyses.values()
                    for item in _list(analysis.get("risks"))
                    if isinstance(item, str)
                )
            ),
        }


def evaluate(candidate, technology, market, round_id):
    """두 분석의 원문 근거를 확인하고 평가표로 투자 후보를 판정합니다."""
    return _InvestmentEvaluation(candidate, technology, market, round_id).run()
