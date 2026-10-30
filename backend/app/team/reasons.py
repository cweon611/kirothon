"""F2 reason sentences: rule text first, optional AI rewording (design 10).

AI goes through ai_service.generate_text (same quota as POST /api/ai/generate),
at most once per day and twice per course. Prices, times and refund terms are
never taken from the AI; lines that contain them are discarded.
"""
from collections.abc import Callable
import re

from fastapi import HTTPException

from ..ai_service import DEFAULT_MODEL, generate_text

INSTRUCTION = ("아래 장소별 tags와 overview에 있는 사실만 써서, 장소마다 30자 이내 추천 이유 한 문장을 작성하라. "
               "가격·운영시간·환급 조건은 쓰지 마라. '번호. 문장' 형식으로 한 줄씩만 출력하라.")
MAX_CALLS_PER_COURSE = 2
MAX_SPOTS_PER_CALL = 4
MAX_SENTENCE = 30
OVERVIEW_CHARS = 200
LINE = re.compile(r"^\s*(\d+)\s*[.)]\s*(.+?)\s*$")
FORBIDDEN = re.compile(r"\d[\d,]*\s*(원|시|%|퍼센트)|환급|무료")


def rule_sentence(tags: list[str]) -> str:
    picks = [t for t in tags if not t.startswith("이전 장소")][:2] or tags[:1]
    return " · ".join(picks)


def build_input(spots: list[dict]) -> str:
    lines = []
    for n, spot in enumerate(spots, 1):
        overview = re.sub(r"\s+", " ", spot.get("overview") or "")[:OVERVIEW_CHARS]
        lines.append(f"{n}. {spot['title']} | tags: {', '.join(spot['tags'])} | overview: {overview}")
    return "\n".join(lines)[:4000]


def parse_output(text: str, count: int) -> dict[int, str]:
    found: dict[int, str] = {}
    for line in (text or "").splitlines():
        match = LINE.match(line)
        if not match:
            continue
        n, sentence = int(match.group(1)), match.group(2).strip().strip('"').strip()
        if not 1 <= n <= count or n in found or not sentence:
            continue
        if len(sentence) > MAX_SENTENCE or FORBIDDEN.search(sentence):
            continue
        found[n] = sentence
    return found


def day_spots(body: dict, day_no: int) -> list[dict]:
    for day in body.get("days", []):
        if day["day"] == day_no:
            return [i for i in day["items"] if i["kind"] == "spot" and i.get("place")][:MAX_SPOTS_PER_CALL]
    return []


def generate_for_day(body: dict, state: dict, day_no: int, ai_calls: int, overviews: dict[str, str],
                     generate: Callable[..., dict] = generate_text) -> tuple[dict, int, str]:
    """Return (updated state, ai_calls, status). status: stored | ai | mock | rule | quota | failed."""
    days = state.setdefault("days", {})
    texts = state.setdefault("texts", {})
    key = str(day_no)
    if key in days:
        return state, ai_calls, "stored"
    spots = day_spots(body, day_no)
    if not spots:
        days[key] = "rule"
        return state, ai_calls, "rule"
    if ai_calls >= MAX_CALLS_PER_COURSE:
        days[key] = "rule"
        return state, ai_calls, "quota"
    payload = [{"title": s["place"]["title"], "tags": s["reason_tags"],
                "overview": overviews.get(s["place"]["content_id"])} for s in spots]
    ai_calls += 1
    try:
        result = generate(build_input(payload), INSTRUCTION, DEFAULT_MODEL)
    except HTTPException:
        days[key] = "rule"
        return state, ai_calls, "failed"
    if result.get("mode") == "mock":
        for spot in spots:
            texts[spot["place"]["content_id"]] = {"text": spot["reason_text"], "by": "mock"}
        days[key] = "mock"
        return state, ai_calls, "mock"
    parsed = parse_output(result.get("text", ""), len(spots))
    for n, spot in enumerate(spots, 1):
        if n in parsed:
            texts[spot["place"]["content_id"]] = {"text": parsed[n], "by": "ai"}
    days[key] = "ai"
    return state, ai_calls, "ai"


def apply_state(body: dict, state: dict) -> dict:
    """Overlay stored sentences by content_id (survives swaps of other items)."""
    texts = state.get("texts") or {}
    for day in body.get("days", []):
        for item in day["items"]:
            stored = texts.get((item.get("place") or {}).get("content_id", ""))
            if item["kind"] == "spot" and stored:
                item["reason_text"], item["reason_by"] = stored["text"], stored["by"]
    return body
