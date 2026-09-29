"""담당자 사이에 주고받는 값이 shared.py의 약속을 지키는지 확인합니다."""
import math

from shared import AGENT_KEYS


def check_fields(value, fields, label, optional=()):
    if not isinstance(value, dict):
        raise ValueError(f"{label}: 객체(dict)여야 합니다.")
    missing = set(fields) - value.keys()
    extra = value.keys() - set(fields) - set(optional)
    if missing:
        raise ValueError(f"{label}: 필수 항목이 없습니다: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"{label}: 약속에 없는 항목입니다: {', '.join(sorted(extra))}")


def check_text(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label}: 문자열이어야 합니다.")


def check_example(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label}.is_example: true 또는 false여야 합니다.")


def validate_company(value, label="company"):
    check_fields(value, ["id", "name", "description", "website", "is_example"], label)
    for field in ["id", "name", "description", "website"]:
        check_text(value[field], f"{label}.{field}")
    if not value["id"].strip() or not value["name"].strip():
        raise ValueError(f"{label}: id와 name은 비어 있을 수 없습니다.")
    check_example(value["is_example"], label)


def validate_candidates(candidates):
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("후보 목록은 한 곳 이상을 담은 배열(list)이어야 합니다.")
    ids = set()
    for index, company in enumerate(candidates):
        validate_company(company, f"후보[{index}]")
        if company["id"] in ids:
            raise ValueError(f"후보 id가 중복되었습니다: {company['id']}")
        ids.add(company["id"])


def validate_sources(sources, label):
    if not isinstance(sources, list):
        raise ValueError(f"{label}: 배열(list)이어야 합니다.")
    for index, source in enumerate(sources):
        source_label = f"{label}[{index}]"
        check_fields(source, ["title", "url", "page"], source_label, optional=["published_at"])
        check_text(source["title"], f"{source_label}.title")
        check_text(source["url"], f"{source_label}.url")
        if not source["title"].strip() or not source["url"].strip():
            raise ValueError(f"{source_label}: title과 url은 비어 있을 수 없습니다.")
        page = source["page"]
        if page is not None and (type(page) is not int or page < 1):
            raise ValueError(f"{source_label}.page: 1 이상의 정수 또는 null이어야 합니다.")
        if source.get("published_at") is not None:
            check_text(source["published_at"], f"{source_label}.published_at")


def validate_analysis(value, label):
    check_fields(value, ["summary", "sources", "uncertainties", "is_example"], label)
    check_text(value["summary"], f"{label}.summary")
    validate_sources(value["sources"], f"{label}.sources")
    uncertainties = value["uncertainties"]
    if not isinstance(uncertainties, list) or not all(isinstance(item, str) for item in uncertainties):
        raise ValueError(f"{label}.uncertainties: 문자열 배열이어야 합니다.")
    check_example(value["is_example"], label)


def validate_investment(value, label="investment"):
    check_fields(value, ["decision", "reason", "score", "sources", "is_example"], label)
    if value["decision"] not in ("invest", "hold"):
        raise ValueError(f"{label}.decision: invest 또는 hold여야 합니다.")
    check_text(value["reason"], f"{label}.reason")
    score = value["score"]
    if score is not None:
        if type(score) not in (int, float) or not 0 <= score <= 100 or not math.isfinite(score):
            raise ValueError(f"{label}.score: 0~100의 유한한 숫자 또는 null(미확인)이어야 합니다.")
    validate_sources(value["sources"], f"{label}.sources")
    check_example(value["is_example"], label)


def validate_report(value, label="report"):
    check_fields(value, ["summary", "markdown", "is_example"], label)
    check_text(value["summary"], f"{label}.summary")
    check_text(value["markdown"], f"{label}.markdown")
    check_example(value["is_example"], label)


def validate_record(record, label):
    check_fields(record, ["company", "company_info", "technology", "market_competition", "investment"], label)
    validate_company(record["company"], f"{label}.company")
    for key in ["company_info", "technology", "market_competition"]:
        validate_analysis(record[key], f"{label}.{key}")
    validate_investment(record["investment"], f"{label}.investment")


def validate_state(state):
    """단독 실행용 JSON에 있는 값도 확인합니다. State는 일부 항목만 있어도 됩니다."""
    if not isinstance(state, dict):
        raise ValueError("state: 객체(dict)여야 합니다.")
    allowed = {"domain", "candidates", "candidate_index", "company", "company_info", "technology", "market_competition", "investment", "history", "report"}
    if state.keys() - allowed:
        raise ValueError("state: shared.py에 없는 항목이 있습니다.")
    if "domain" in state and state["domain"] != "Physical AI":
        raise ValueError("state.domain: 이 프로젝트의 분야는 Physical AI입니다.")
    if "candidates" in state:
        validate_candidates(state["candidates"])
    if "candidate_index" in state:
        index = state["candidate_index"]
        if type(index) is not int or index < 0:
            raise ValueError("state.candidate_index: 0 이상의 정수여야 합니다.")
        if "candidates" in state and index >= len(state["candidates"]):
            raise ValueError("state.candidate_index: 후보 목록 범위를 벗어났습니다.")
    if "company" in state:
        validate_company(state["company"])
    if {"company", "candidates", "candidate_index"} <= state.keys():
        if state["company"] != state["candidates"][state["candidate_index"]]:
            raise ValueError("state.company: 현재 후보와 후보 목록의 내용이 다릅니다.")
    for key in ["company_info", "technology", "market_competition"]:
        if key in state:
            validate_analysis(state[key], key)
    if "investment" in state:
        validate_investment(state["investment"])
    if "history" in state:
        if not isinstance(state["history"], list):
            raise ValueError("state.history: 배열(list)이어야 합니다.")
        for index, record in enumerate(state["history"]):
            validate_record(record, f"history[{index}]")
    if "report" in state:
        validate_report(state["report"])


def validate_agent_result(agent_name, result):
    if agent_name not in AGENT_KEYS:
        raise ValueError(f"알 수 없는 agent입니다: {agent_name}")
    key = AGENT_KEYS[agent_name]
    check_fields(result, [key], f"{agent_name} agent 반환값")
    if agent_name == "investment":
        validate_investment(result[key], f"{agent_name} agent")
    elif agent_name == "report":
        validate_report(result[key], f"{agent_name} agent")
    else:
        validate_analysis(result[key], f"{agent_name} agent")
