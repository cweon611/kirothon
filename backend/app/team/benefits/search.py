"""Collect candidate programs from gov24 and the manual registry."""
from __future__ import annotations

from datetime import datetime, timezone

from .gov24 import Gov24Client, Gov24Error
from .regions import norm_sido, region_label, text_mentions_region
from .registry import manual_by_external_id, manual_programs
from .schemas import AgeRule, BenefitProgram, FieldConflict, Region, SourceRef, SourceStatus

# serviceList only supports LIKE on 서비스명 (no region, category, or date-of-service filter).
GOV24_KEYWORDS = ["여행", "관광", "휴가"]
MAX_DETAIL_LOOKUPS = 10

# Travel-specific fields the gov24 API does not provide in structured form.
GOV24_UNSTRUCTURED = [
    "target_regions", "application_period", "trip_period", "posted_status", "residence_rule",
    "age_rule.basis", "youth_rule", "party_rule", "family_rule", "participation_rule",
    "benefit", "visit_rule", "stay_rule", "payment_rule", "pre_apply",
    "settlement_days_after_trip", "payout", "stackable_with",
]
_RAW_LIST = ["지원유형", "서비스목적요약", "지원대상", "선정기준", "지원내용", "신청방법", "신청기한",
             "신청기한유형", "접수기관", "전화문의", "소관기관유형", "사용자구분", "서비스분야"]
_RAW_DETAIL = ["서비스목적", "구비서류", "접수기관명", "문의처", "법령", "자치법규", "행정규칙"]


def _hints(record: dict, regions: list[Region]) -> list[Region]:
    provider = str(record.get("소관기관명") or "")
    texts = " ".join(str(record.get(k) or "") for k in ("서비스명", "지원대상", "지원내용", "선정기준"))
    hits = []
    for region in regions:
        if text_mentions_region(provider, region) or text_mentions_region(texts, region):
            hits.append(region)
        elif region.sido and norm_sido(region.sido) and _provider_is_sido(provider, region.sido):
            hits.append(Region(sido=region.sido))
    unique = {}
    for r in hits:
        unique[region_label(r)] = r
    return list(unique.values())


def _provider_is_sido(provider: str, sido: str) -> bool:
    compact = provider.replace(" ", "")
    target = norm_sido(sido) or ""
    # provider is the sido itself (e.g. "전라남도"), not a sigungu inside it
    return bool(target) and (compact == target or compact == sido.replace(" ", ""))


def _age_rule(conditions: dict | None) -> AgeRule | None:
    if not conditions:
        return None
    lo, hi = conditions.get("JA0110"), conditions.get("JA0111")
    lo = lo if isinstance(lo, int) and lo > 0 else None
    hi = hi if isinstance(hi, int) and hi > 0 else None
    if lo is None and hi is None:
        return None
    return AgeRule(min_age=lo, max_age=hi, basis=None)


def program_from_gov24(record: dict, detail: dict | None, conditions: dict | None,
                       hints: list[Region], fetched_at: datetime) -> BenefitProgram:
    service_id = str(record.get("서비스ID"))
    raw = {k: str(record[k]) for k in _RAW_LIST if record.get(k)}
    if detail:
        raw.update({k: str(detail[k]) for k in _RAW_DETAIL if detail.get(k)})
    if conditions:
        flags = [k for k, v in conditions.items() if k.startswith("JA") and v == "Y"]
        if flags:
            raw["supportConditions_Y"] = ",".join(sorted(flags))
    unverified = list(GOV24_UNSTRUCTURED)
    if detail is None:
        unverified.append("detail_not_fetched")
    age = _age_rule(conditions)
    if age is None:
        unverified.append("age_rule")
    return BenefitProgram(
        id=f"gov24:{service_id}",
        program_id=f"gov24:{service_id}",
        provider=record.get("소관기관명"),
        external_service_id=service_id,
        name=str(record.get("서비스명") or service_id),
        target_regions=None,
        region_hints=hints,
        age_rule=age,
        verified_fields=["age_rule"] if age else [],
        official_info_url=record.get("상세조회URL"),
        application_url=(detail or {}).get("온라인신청사이트URL") or None,
        source_type="gov24_api",
        sources=[SourceRef(source_type="gov24_api", title="행정안전부 대한민국 공공서비스(혜택) 정보",
                           url=record.get("상세조회URL"), retrieved_at=fetched_at)],
        verification_status="unverified",
        external_updated_at=(detail or {}).get("수정일시") or record.get("수정일시"),
        unverified_fields=unverified,
        raw_text=raw,
    )


def merge(manual: BenefitProgram, api: BenefitProgram) -> BenefitProgram:
    """Keep the manual record, attach the API source, and record every disagreement."""
    merged = manual.model_copy(deep=True)
    merged.sources = [*merged.sources, *api.sources]
    merged.raw_text = {**api.raw_text, **merged.raw_text}
    merged.external_updated_at = api.external_updated_at
    for field in ("name", "provider", "official_info_url", "application_url"):
        mine, theirs = getattr(merged, field), getattr(api, field)
        if mine is None and theirs is not None:
            setattr(merged, field, theirs)
        elif mine is not None and theirs is not None and str(mine).strip() != str(theirs).strip():
            merged.conflicts.append(FieldConflict(field=field, values=[
                {"source": merged.source_type, "value": mine}, {"source": "gov24_api", "value": theirs}]))
    if api.age_rule and merged.age_rule:
        a, b = merged.age_rule, api.age_rule
        if (a.min_age, a.max_age) != (b.min_age, b.max_age):
            merged.conflicts.append(FieldConflict(field="age_rule", values=[
                {"source": merged.source_type, "value": {"min_age": a.min_age, "max_age": a.max_age}},
                {"source": "gov24_api", "value": {"min_age": b.min_age, "max_age": b.max_age}}]))
    elif api.age_rule and merged.age_rule is None:
        merged.age_rule = api.age_rule
        merged.verified_fields = sorted({*merged.verified_fields, "age_rule"})
    return merged


def search_gov24(client: Gov24Client | None, regions: list[Region], include: bool):
    """Return (programs, SourceStatus). Never raises for upstream problems."""
    status = SourceStatus(source="gov24_api", status="ok", queries=list(GOV24_KEYWORDS))
    if not include:
        status.status, status.message = "skipped", "요청에서 외부 조회를 끔(include_external=false)"
        status.queries = []
        return [], status
    if client is None:
        status.status, status.error_code = "not_configured", "missing_service_key"
        status.message = "서버에 공공데이터포털 인증키가 설정되지 않아 외부 API를 조회하지 않았습니다."
        status.queries = []
        return [], status

    errors: list[Gov24Error] = []
    records: dict[str, dict] = {}
    cache_flags: list[bool] = []
    fetched: list[datetime] = []
    for keyword in GOV24_KEYWORDS:
        try:
            result = client.list_services(keyword)
        except Gov24Error as exc:
            errors.append(exc)
            continue
        status.pages_fetched += result.pages_fetched
        status.truncated = status.truncated or result.truncated
        cache_flags.append(result.from_cache)
        fetched.append(result.fetched_at)
        for r in result.records:
            if r.get("서비스ID"):
                records.setdefault(str(r["서비스ID"]), r)
    status.records_seen = len(records)
    if fetched:
        status.fetched_at = min(fetched)
        status.data_origin = ("cache" if all(cache_flags) else
                              "live_api" if not any(cache_flags) else "mixed")
    if len(errors) == len(GOV24_KEYWORDS):
        status.status, status.error_code = "error", errors[0].code
        status.message = errors[0].message
        return [], status

    candidates = []
    for record in records.values():
        hints = _hints(record, regions)
        if hints:
            candidates.append((record, hints))
    status.candidates = len(candidates)

    programs: list[BenefitProgram] = []
    detail_errors = 0
    for index, (record, hints) in enumerate(candidates):
        detail = conditions = None
        if index < MAX_DETAIL_LOOKUPS:
            sid = str(record["서비스ID"])
            try:
                detail, _ = client.service_detail(sid)
                conditions, _ = client.support_conditions(sid)
            except Gov24Error:
                detail_errors += 1
        programs.append(program_from_gov24(record, detail, conditions, hints,
                                           status.fetched_at or datetime.now(timezone.utc)))

    notes = []
    if errors:
        notes.append(f"키워드 {len(errors)}/{len(GOV24_KEYWORDS)}건 조회 실패({errors[0].code})")
    if status.truncated:
        notes.append(f"페이지 상한({client.max_pages}페이지)으로 일부 목록만 확인")
    if detail_errors:
        notes.append(f"상세·지원조건 조회 실패 {detail_errors}건")
    if len(candidates) > MAX_DETAIL_LOOKUPS:
        notes.append(f"상세 조회는 후보 {MAX_DETAIL_LOOKUPS}건까지만 수행")
    if notes:
        status.status = "partial"
        status.error_code = errors[0].code if errors else None
        status.message = "; ".join(notes)
    return programs, status


def stored_candidates(stored: list, regions: list[Region]) -> list[BenefitProgram]:
    """Programs from the sync store relevant to the visit regions. No network calls.

    gov24 records have no structured region, so text hints are computed from the
    stored list row; tour50 records carry target_regions and are matched later.
    """
    import json
    out = []
    for program, rec in stored:
        if rec.source == "gov24_api":
            row = json.loads(rec.raw_json).get("list") or {}
            hints = _hints(row, regions)
            if not hints:
                continue
            program = program.model_copy(update={"region_hints": hints})
        out.append(program)
    return out


def collect_stored(stored: list, regions: list[Region]):
    """Return list of (program, data_origin) from stored sync data + manual registry."""
    programs = stored_candidates(stored, regions)
    manual = manual_programs()
    by_ext = manual_by_external_id()
    merged_ids = set()
    out: list[tuple[BenefitProgram, str]] = []
    for p in programs:
        if p.sync and p.sync.source == "gov24_api" and p.external_service_id in by_ext:
            out.append((merge(by_ext[p.external_service_id], p), "merged"))
            merged_ids.add(by_ext[p.external_service_id].id)
        else:
            out.append((p, "gov24_api" if p.sync and p.sync.source == "gov24_api" else "kto_tour50"))
    out.extend((p, "manual_registry") for p in manual if p.id not in merged_ids)
    return out, len(manual)


def collect(client: Gov24Client | None, regions: list[Region], include_external: bool):
    """Return (list of (program, data_origin)), [gov24 status, registry status]."""
    api_programs, api_status = search_gov24(client, regions, include_external)
    manual = manual_programs()
    by_ext = manual_by_external_id()
    merged_ids = set()
    out: list[tuple[BenefitProgram, str]] = []
    for api in api_programs:
        if api.external_service_id in by_ext:
            out.append((merge(by_ext[api.external_service_id], api), "merged"))
            merged_ids.add(by_ext[api.external_service_id].id)
        else:
            out.append((api, "gov24_api"))
    out.extend((p, "manual_registry") for p in manual if p.id not in merged_ids)
    registry_status = SourceStatus(source="manual_registry", status="ok", data_origin="local_registry",
                                   records_seen=len(manual),
                                   message="수동 등록 자료(공식 공고 검토 전 항목 포함)")
    return out, [api_status, registry_status]
