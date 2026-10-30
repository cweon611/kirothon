"""Collect the tourism APIs into SQLite (S1). Run before the event, not per request.

    python -m app.team.sync_tourism                      # all steps, all 27 sigungu
    python -m app.team.sync_tourism --base-ym 202606     # fix the hub/related month
    python -m app.team.sync_tourism --steps places,match --sigungu 46840

Key: TOURAPI_SERVICE_KEY (Decoding key) from the environment only.
A failed sigungu keeps its previous rows; nothing is deleted on error or empty pages.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import html
import json
import re
import sys
from collections.abc import Iterable

from sqlmodel import Session, delete, select

from ..database import DB_PATH, engine, init_db
from ..schema_check import check_registered_schema
from .regions import (KST, SPOT_TYPES, codes_path, interests, internal_code, ldong_for, load_codes,
                      name_key, name_variants, place_overrides, sigungu_from_address, sigungu_map)
from .geo import haversine_km
from .tourapi import TourApiClient, TourApiError
from .tourism_models import HubRank, Place, RelatedPlace, TourismSyncRun, utc_now

STEPS = ("codes", "places", "std", "festivals", "hubs", "related", "match", "details")
PLACE_TYPES = ("12", "14", "28", "39", "32")
GWANGJU_JEONNAM = ("광주", "전라남", "전남")
STALE_RUN = timedelta(hours=2)
INTRO_KEYS = ("restdate", "usetime", "restdateculture", "usetimeculture", "usefee", "spendtime",
              "restdateleports", "usetimeleports", "usefeeleports", "restdatefood", "opentimefood",
              "checkintime", "checkouttime", "parking", "infocenter")
STD_FIELDS = {"trrsrtSe": "std_category", "prkplceCo": "std_parking", "aceptncCo": "std_capacity",
              "cnvnncFclty": "std_facilities", "referenceDate": "std_reference_date"}


class StepLog:
    def __init__(self):
        self.steps: dict[str, dict] = {}

    def step(self, name: str) -> dict:
        return self.steps.setdefault(name, {"status": "ok", "rows": 0, "failures": [], "notes": []})

    def fail(self, name: str, target: str, error: TourApiError) -> None:
        entry = self.step(name)
        entry["status"] = "partial"
        entry["failures"].append({"target": target, **error.to_dict()})

    @property
    def overall(self) -> str:
        states = {s["status"] for s in self.steps.values()}
        if not states or states == {"ok"}:
            return "success"
        return "failed" if states == {"failed"} else "partial"


def clean(value) -> str | None:
    text = html.unescape(re.sub(r"<[^>]*>", " ", str(value or ""))).strip()
    return re.sub(r"\s+", " ", text) or None


def to_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number else None


def to_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def ymd(value) -> str | None:
    text = str(value or "").strip()
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return None


# ---------- step 1: codes ----------

def resolve_ldong(rows: list[dict]) -> tuple[dict, list[dict], list[str]]:
    """Match seed sigungu names to ldongCode2 rows of Gwangju/Jeonnam sido names."""
    resolved, changed, unresolved = {}, [], []
    local = [r for r in rows if any(k in str(r.get("lDongRegnNm", "")) for k in GWANGJU_JEONNAM)]
    for code, region in sigungu_map().items():
        want_gwangju = region.sido == "광주광역시"
        pool = [r for r in local if ("광주" in str(r.get("lDongRegnNm"))) == want_gwangju
                or "전남광주" in str(r.get("lDongRegnNm"))]
        exact = [r for r in pool if str(r.get("lDongSignguNm", "")).strip() == region.name]
        if len(exact) > 1 and want_gwangju:
            exact = [r for r in exact if "광주" in str(r.get("lDongRegnNm"))]
        if len(exact) != 1:
            unresolved.append(code)
            continue
        pair = [str(exact[0]["lDongRegnCd"]), str(exact[0]["lDongSignguCd"])]
        resolved[code] = pair
        if (pair[0] + pair[1] if len(pair[1]) == 3 else pair[1]) != code:
            changed.append({"internal": code, "ldong": pair, "sido": exact[0].get("lDongRegnNm")})
    return resolved, changed, unresolved


def resolve_lcls(rows: list[dict]) -> dict:
    result = {}
    for interest in interests().values():
        name_field, code_field = (("lclsSystm1Nm", "lclsSystm1Cd") if interest.level == 1
                                  else ("lclsSystm2Nm", "lclsSystm2Cd"))
        hits = sorted({str(r[code_field]) for r in rows if r.get(code_field)
                       and any(k in str(r.get(name_field, "")) for k in interest.keywords)})
        names = sorted({str(r[name_field]) for r in rows if str(r.get(code_field)) in hits})
        if hits:
            result[interest.key] = {f"lcls{interest.level}": hits, "names": names}
    return result


def step_codes(client: TourApiClient, log: StepLog) -> dict:
    entry = log.step("codes")
    codes = load_codes()
    try:
        rows, _, truncated = client.fetch_all("KorService2", "ldongCode2", num_of_rows=1000,
                                              max_pages=5, lDongListYn="Y")
        resolved, changed, unresolved = resolve_ldong(rows)
        codes["ldong"] = resolved
        codes["ldong_all"] = [
            {"sido": str(r.get("lDongRegnNm") or ""), "name": str(r.get("lDongSignguNm") or ""),
             "code": (str(r["lDongRegnCd"]) + str(r["lDongSignguCd"]) if len(str(r["lDongSignguCd"])) == 3
                      else str(r["lDongSignguCd"]))}
            for r in rows if r.get("lDongRegnCd") and r.get("lDongSignguCd")]
        entry["notes"].append({"ldong_rows": len(rows), "resolved": len(resolved),
                               "changed_from_seed": changed, "unresolved": unresolved,
                               "truncated": truncated})
        if unresolved:
            entry["status"] = "partial"
    except TourApiError as exc:
        log.fail("codes", "ldongCode2", exc)
    try:
        rows, _, _ = client.fetch_all("KorService2", "lclsSystmCode2", num_of_rows=1000,
                                      max_pages=5, lclsSystmListYn="Y")
        codes["lcls"] = resolve_lcls(rows)
        entry["notes"].append({"lcls_rows": len(rows), "interest_codes": codes["lcls"]})
    except TourApiError as exc:
        log.fail("codes", "lclsSystmCode2", exc)
    codes["resolved_at"] = datetime.now(KST).isoformat(timespec="seconds")
    path = codes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(codes, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return codes


# ---------- step 2/3: places and festivals ----------

def upsert_place(session: Session, row: dict, codes: dict, *, source_type: str | None = None) -> bool:
    content_id = str(row.get("contentid") or "").strip()
    title = clean(row.get("title"))
    if not content_id or not title:
        return False
    place = session.get(Place, content_id) or Place(content_id=content_id, content_type_id="", title=title)
    place.content_type_id = str(row.get("contenttypeid") or source_type or place.content_type_id)
    place.title = title
    place.ldong_regn_cd = str(row.get("lDongRegnCd") or "") or None
    place.ldong_signgu_cd = str(row.get("lDongSignguCd") or "") or None
    place.sigungu_code = internal_code(place.ldong_regn_cd, place.ldong_signgu_cd, codes) or place.sigungu_code
    place.lcls1 = str(row.get("lclsSystm1") or "") or None
    place.lcls2 = str(row.get("lclsSystm2") or "") or None
    place.lcls3 = str(row.get("lclsSystm3") or "") or None
    place.addr = clean(" ".join(filter(None, [str(row.get("addr1") or ""), str(row.get("addr2") or "")])))
    place.lng, place.lat = to_float(row.get("mapx")), to_float(row.get("mapy"))
    place.image_url = str(row.get("firstimage") or "") or None
    place.thumb_url = str(row.get("firstimage2") or "") or None
    place.cpyright_type = str(row.get("cpyrhtDivCd") or "") or None
    place.tel = clean(row.get("tel"))
    place.source_modified = str(row.get("modifiedtime") or "") or None
    if place.content_type_id == "15":
        place.event_start, place.event_end = ymd(row.get("eventstartdate")), ymd(row.get("eventenddate"))
    place.source = "kor"
    place.fetched_at = utc_now()
    session.add(place)
    return True


def step_places(client, session, log, targets, codes, num_of_rows, max_pages) -> None:
    entry = log.step("places")
    for code in targets:
        regn, signgu = ldong_for(code, codes)
        for content_type in PLACE_TYPES:
            label = f"{code}/type{content_type}"
            try:
                rows, total, truncated = client.fetch_all(
                    "KorService2", "areaBasedList2", num_of_rows=num_of_rows, max_pages=max_pages,
                    arrange="C", contentTypeId=content_type, lDongRegnCd=regn, lDongSignguCd=signgu)
            except TourApiError as exc:
                log.fail("places", label, exc)
                continue
            entry["rows"] += sum(upsert_place(session, row, codes, source_type=content_type) for row in rows)
            if truncated:
                entry["notes"].append({"target": label, "truncated": True, "total": total, "got": len(rows)})
        session.commit()


def step_std(client, session, log, targets) -> None:
    """전국관광지정보표준데이터: enrich a matching KorService2 place, otherwise add it as source='std'."""
    entry = log.step("std")
    try:
        rows, total, truncated = client.fetch_standard_sites()
    except TourApiError as exc:
        log.fail("std", "tn_pubr_public_trrsrt_api", exc)
        return
    wanted = set(targets)
    by_code: dict[str, list[Place]] = {}
    for place in session.exec(select(Place).where(Place.content_type_id != "15")).all():
        by_code.setdefault(place.sigungu_code or "", []).append(place)
    region_rows = enriched = added = 0
    for row in rows:
        addr = clean(row.get("rdnmadr")) or clean(row.get("lnmadr"))
        code = sigungu_from_address(addr) or sigungu_from_address(clean(row.get("lnmadr")))
        name = clean(row.get("trrsrtNm"))
        if not code or code not in wanted or not name:
            continue
        region_rows += 1
        extra = {key: clean(row.get(src)) for src, key in STD_FIELDS.items() if clean(row.get(src))}
        lat, lng = to_float(row.get("latitude")), to_float(row.get("longitude"))
        content_id, _ = match_name(name, code, by_code, {}, (lat, lng) if lat and lng else None)
        place = session.get(Place, content_id) if content_id else None
        if place is None:
            content_id = "std-" + hashlib.sha1(f"{code}:{name_key(name)}".encode()).hexdigest()[:12]
            place = session.get(Place, content_id) or Place(content_id=content_id, content_type_id="12",
                                                             title=name, source="std")
            place.title, place.sigungu_code, place.addr = name, code, addr
            place.lat, place.lng = lat, lng
            place.overview = clean(row.get("trrsrtIntrcn"))
            place.intro_json = json.dumps(extra, ensure_ascii=False)
            place.source_modified = extra.get("std_reference_date")
            place.fetched_at = utc_now()
            by_code.setdefault(code, []).append(place)
            added += 1
        else:
            intro = json.loads(place.intro_json) if place.intro_json else {}
            intro.update(extra)
            place.intro_json = json.dumps(intro, ensure_ascii=False)
            place.overview = place.overview or clean(row.get("trrsrtIntrcn"))
            if place.lat is None and lat:
                place.lat, place.lng = lat, lng
            enriched += 1
        session.add(place)
    session.commit()
    entry["rows"] = enriched + added
    entry["notes"].append({"total": total, "region_rows": region_rows, "enriched": enriched, "added": added,
                           "truncated": truncated})


def step_festivals(client, session, log, codes, today: date, num_of_rows, max_pages) -> None:
    entry = log.step("festivals")
    regns = sorted({ldong_for(code, codes)[0] for code in sigungu_map()})
    for regn in regns:
        try:
            # Start a month back so events already running are included; trips are matched by overlap.
            since = (today - timedelta(days=31)).strftime("%Y%m%d")
            rows, _, truncated = client.fetch_all("KorService2", "searchFestival2", num_of_rows=num_of_rows,
                                                  max_pages=max_pages, eventStartDate=since, lDongRegnCd=regn)
        except TourApiError as exc:
            log.fail("festivals", regn, exc)
            continue
        entry["rows"] += sum(upsert_place(session, row, codes, source_type="15") for row in rows)
        if truncated:
            entry["notes"].append({"target": regn, "truncated": True})
    session.commit()


# ---------- step 4/5: hubs and related (navigation-based ranks) ----------

def month_back(ym: str, months: int) -> str:
    year, month = int(ym[:4]), int(ym[4:])
    index = year * 12 + month - 1 - months
    return f"{index // 12:04d}{index % 12 + 1:02d}"


def probe_base_ym(client, service: str, start_ym: str, code: str, limit: int = 30) -> str | None:
    """Walk back month by month until the API returns rows (portal lists 2024-05~2025-04 for related)."""
    for back in range(limit):
        ym = month_back(start_ym, back)
        try:
            page = client.get(service, "areaBasedList1", pageNo=1, numOfRows=1, baseYm=ym,
                              areaCd=code[:2], signguCd=code)
        except TourApiError as exc:
            if exc.kind in ("auth", "quota", "config"):
                raise
            continue
        if page.items:
            return ym
    return None


def replace_rows(session: Session, model, base_ym: str, code: str, rows: list) -> None:
    session.exec(delete(model).where(model.base_ym == base_ym, model.sigungu_code == code))
    session.add_all(rows)


def step_hubs(client, session, log, targets, base_ym, num_of_rows, max_pages) -> None:
    entry = log.step("hubs")
    for code in targets:
        try:
            rows, _, truncated = client.fetch_all("LocgoHubTarService1", "areaBasedList1",
                                                  num_of_rows=num_of_rows, max_pages=max_pages,
                                                  baseYm=base_ym, areaCd=code[:2], signguCd=code)
        except TourApiError as exc:
            log.fail("hubs", code, exc)
            continue
        hubs = [HubRank(base_ym=base_ym, sigungu_code=code, rank=to_int(r.get("hubRank")) or 999,
                        hub_code=str(r.get("hubTatsCd") or ""), name=clean(r.get("hubTatsNm")) or "",
                        lat=to_float(r.get("mapY")), lng=to_float(r.get("mapX")),
                        category_l=clean(r.get("hubCtgryLclsNm")), category_m=clean(r.get("hubCtgryMclsNm")))
                for r in rows if r.get("hubTatsCd") and r.get("hubTatsNm")]
        if not hubs:
            entry["notes"].append({"target": code, "empty": True, "kept_previous": True})
            continue
        replace_rows(session, HubRank, base_ym, code, hubs)
        entry["rows"] += len(hubs)
        if truncated:
            entry["notes"].append({"target": code, "truncated": True})
        session.commit()


def step_related(client, session, log, targets, base_ym, num_of_rows, max_pages) -> None:
    entry = log.step("related")
    for code in targets:
        try:
            rows, _, truncated = client.fetch_all("TarRlteTarService1", "areaBasedList1",
                                                  num_of_rows=num_of_rows, max_pages=max_pages,
                                                  baseYm=base_ym, areaCd=code[:2], signguCd=code)
        except TourApiError as exc:
            log.fail("related", code, exc)
            continue
        related = [RelatedPlace(base_ym=base_ym, sigungu_code=code, src_code=str(r.get("tAtsCd") or ""),
                                src_name=clean(r.get("tAtsNm")) or "", rel_code=str(r.get("rlteTatsCd") or ""),
                                rel_name=clean(r.get("rlteTatsNm")) or "",
                                rel_sigungu_code=str(r.get("rlteSignguCd") or "") or None,
                                rel_category_l=clean(r.get("rlteCtgryLclsNm")),
                                rel_category_m=clean(r.get("rlteCtgryMclsNm")),
                                rel_category_s=clean(r.get("rlteCtgrySclsNm")),
                                rank=to_int(r.get("rlteRank")) or 999)
                   for r in rows if r.get("tAtsCd") and r.get("rlteTatsCd")]
        if not related:
            entry["notes"].append({"target": code, "empty": True, "kept_previous": True})
            continue
        replace_rows(session, RelatedPlace, base_ym, code, related)
        entry["rows"] += len(related)
        if truncated:
            entry["notes"].append({"target": code, "truncated": True})
        session.commit()


# ---------- step 6: name matching ----------

def match_name(name: str, code: str | None, places_by_code: dict[str, list[Place]], overrides: dict[str, str],
               point: tuple[float, float] | None = None) -> tuple[str | None, str | None]:
    if code and f"{code}:{name}" in overrides:
        return overrides[f"{code}:{name}"], "override"
    key = name_key(name)
    same = [p for p in places_by_code.get(code or "", []) if name_key(p.title) == key]
    if point:
        near = [p for p in same if p.lat and p.lng and haversine_km(point, (p.lat, p.lng)) <= 0.5]
        if len(near) == 1:
            return near[0].content_id, "name+coord"
    if len(same) == 1:
        return same[0].content_id, "name"
    if same:
        return None, None  # several exact hits: do not guess
    wanted = name_variants(name, code)
    loose = [p for p in places_by_code.get(code or "", []) if wanted & name_variants(p.title, code)]
    if point:
        near = [p for p in loose if p.lat and p.lng and haversine_km(point, (p.lat, p.lng)) <= 0.5]
        if len(near) == 1:
            return near[0].content_id, "variant+coord"
    if len(loose) == 1:
        return loose[0].content_id, "variant"
    return None, None


def step_match(client, session, log, targets: Iterable[str], codes: dict, keyword_limit: int) -> None:
    entry = log.step("match")
    overrides = place_overrides()
    by_code: dict[str, list[Place]] = {}
    for place in session.exec(select(Place).where(Place.content_type_id != "15")).all():
        by_code.setdefault(place.sigungu_code or "", []).append(place)
    targets = list(targets)
    hubs = session.exec(select(HubRank).where(HubRank.sigungu_code.in_(targets))).all()
    hub_matched, keyword_calls = 0, 0
    for hub in sorted(hubs, key=lambda h: h.rank):
        point = (hub.lat, hub.lng) if hub.lat and hub.lng else None
        content_id, method = match_name(hub.name, hub.sigungu_code, by_code, overrides, point)
        if not content_id and hub.rank <= 10 and client and keyword_calls < keyword_limit:
            keyword_calls += 1
            content_id, method = keyword_match(client, session, log, hub, codes, by_code)
        hub.content_id, hub.match_method = content_id, method
        hub_matched += bool(content_id)
        session.add(hub)
    hub_ids = {(h.sigungu_code, h.hub_code): h.content_id for h in hubs}
    related = session.exec(select(RelatedPlace).where(RelatedPlace.sigungu_code.in_(targets))).all()
    rel_matched = 0
    for row in related:
        row.src_content_id = hub_ids.get((row.sigungu_code, row.src_code)) or match_name(
            row.src_name, row.sigungu_code, by_code, overrides)[0]
        row.rel_content_id = match_name(row.rel_name, row.rel_sigungu_code, by_code, overrides)[0]
        rel_matched += bool(row.rel_content_id)
        session.add(row)
    session.commit()
    entry["rows"] = hub_matched + rel_matched
    entry["notes"].append({"hub_rows": len(hubs), "hub_matched": hub_matched,
                           "hub_match_rate": round(hub_matched / len(hubs), 3) if hubs else None,
                           "related_rows": len(related), "related_matched": rel_matched,
                           "related_match_rate": round(rel_matched / len(related), 3) if related else None,
                           "keyword_calls": keyword_calls})


def keyword_match(client, session, log, hub: HubRank, codes, by_code) -> tuple[str | None, str | None]:
    regn, signgu = ldong_for(hub.sigungu_code, codes)
    try:
        page = client.get("KorService2", "searchKeyword2", keyword=hub.name, numOfRows=20,
                          lDongRegnCd=regn, lDongSignguCd=signgu)
    except TourApiError as exc:
        log.fail("match", f"keyword:{hub.sigungu_code}", exc)
        return None, None
    key = name_key(hub.name)
    hits = [r for r in page.items if name_key(clean(r.get("title"))) == key]
    if len(hits) != 1:
        return None, None
    upsert_place(session, hits[0], codes)
    session.flush()
    place = session.get(Place, str(hits[0]["contentid"]))
    by_code.setdefault(hub.sigungu_code, []).append(place)
    return place.content_id, "keyword"


# ---------- step 7: details for top candidates ----------

def fetch_detail(client: TourApiClient, place: Place) -> None:
    """detailCommon2 (overview) + detailIntro2 (rest/use time, fee); detailInfo2 room fee for stays."""
    common = client.get("KorService2", "detailCommon2", contentId=place.content_id).items
    intro = client.get("KorService2", "detailIntro2", contentId=place.content_id,
                       contentTypeId=place.content_type_id).items
    if common:
        place.overview = clean(common[0].get("overview")) or place.overview
    if intro:
        place.intro_json = json.dumps({k: clean(intro[0].get(k)) for k in INTRO_KEYS if clean(intro[0].get(k))},
                                      ensure_ascii=False)
    if place.content_type_id == "32":
        rooms = client.get("KorService2", "detailInfo2", contentId=place.content_id, contentTypeId="32").items
        fees = [to_int(r.get("roomoffseasonminfee1")) for r in rooms]
        fees = [f for f in fees if f]
        place.room_price_krw = min(fees) if fees else None
    place.detail_fetched_at = utc_now()


def step_details(client, session, log, targets, top: int) -> None:
    entry = log.step("details")
    for code in targets:
        hubs = session.exec(select(HubRank).where(HubRank.sigungu_code == code, HubRank.content_id.is_not(None))
                            .order_by(HubRank.rank)).all()
        ids = [h.content_id for h in hubs][:top]
        for content_id in ids:
            place = session.get(Place, content_id)
            if (not place or place.source != "kor" or place.content_type_id not in SPOT_TYPES
                    or place.detail_fetched_at):
                continue
            try:
                fetch_detail(client, place)
            except TourApiError as exc:
                log.fail("details", content_id, exc)
                if exc.kind in ("auth", "quota"):
                    session.commit()
                    return
                continue
            session.add(place)
            entry["rows"] += 1
        session.commit()


# ---------- runner ----------

def run(args, client: TourApiClient | None = None) -> TourismSyncRun:
    check_registered_schema(DB_PATH)
    init_db()
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    unknown = set(steps) - set(STEPS)
    if unknown:
        raise SystemExit(f"unknown steps: {sorted(unknown)}")
    targets = args.sigungu or list(sigungu_map())
    bad = [c for c in targets if c not in sigungu_map()]
    if bad:
        raise SystemExit(f"unknown sigungu codes: {bad}")
    today = datetime.now(KST).date()
    with Session(engine) as session:
        running = session.exec(select(TourismSyncRun).where(TourismSyncRun.status == "running")).all()
        now = utc_now()
        active = [r for r in running if now - r.started_at.replace(tzinfo=timezone.utc) < STALE_RUN]
        if active and not args.force:
            raise SystemExit(f"another sync run (id={active[0].id}) started at {active[0].started_at}; "
                             "use --force if it is known to be dead")
        record = TourismSyncRun()
        session.add(record)
        session.commit()
        session.refresh(record)
        log = StepLog()
        own_client = client is None
        try:
            client = client or TourApiClient(timeout=args.timeout, min_interval=args.interval)
            codes = step_codes(client, log) if "codes" in steps else load_codes()
            if "places" in steps:
                step_places(client, session, log, targets, codes, args.num_of_rows, args.max_pages)
            if "std" in steps:
                step_std(client, session, log, targets)
            if "festivals" in steps:
                step_festivals(client, session, log, codes, today, args.num_of_rows, args.max_pages)
            start_ym = (today.replace(day=1) - timedelta(days=1)).strftime("%Y%m")
            for step, service, attr, fn in (("hubs", "LocgoHubTarService1", "base_ym_hub", step_hubs),
                                            ("related", "TarRlteTarService1", "base_ym_related", step_related)):
                if step not in steps:
                    continue
                base_ym = args.base_ym or probe_base_ym(client, service, start_ym, targets[0])
                if not base_ym:
                    log.step(step)["status"] = "failed"
                    log.step(step)["notes"].append({"base_ym": None, "message": "응답이 있는 기준연월을 찾지 못함"})
                    continue
                setattr(record, attr, base_ym)
                fn(client, session, log, targets, base_ym, args.related_rows if step == "related" else 100,
                   args.max_pages)
            if "match" in steps:
                step_match(client, session, log, targets, codes, args.keyword_limit)
            if "details" in steps:
                step_details(client, session, log, targets, args.details_top)
            record.status = log.overall
        except TourApiError as exc:
            record.status = "failed"
            record.message = str(exc)
        finally:
            if own_client and client is not None:
                client.close()
            record.finished_at = utc_now()
            record.steps_json = json.dumps({"calls": getattr(client, "calls", 0), **log.steps}, ensure_ascii=False)
            session.add(record)
            session.commit()
            session.refresh(record)
        return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--steps", default=",".join(STEPS), help="comma list of " + ",".join(STEPS))
    parser.add_argument("--sigungu", action="append", help="internal 5-digit code; repeatable (default: all 27)")
    parser.add_argument("--base-ym", help="YYYYMM for hub/related APIs (default: latest month with data)")
    parser.add_argument("--num-of-rows", type=int, default=500)
    parser.add_argument("--related-rows", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--details-top", type=int, default=5, help="hub places per sigungu to fetch details for")
    parser.add_argument("--keyword-limit", type=int, default=30, help="max searchKeyword2 calls for unmatched hubs")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--interval", type=float, default=0.2, help="seconds between calls")
    parser.add_argument("--force", action="store_true", help="ignore a running-run marker")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.base_ym and not (len(args.base_ym) == 6 and args.base_ym.isdigit()):
        raise SystemExit("--base-ym must be YYYYMM")
    record = run(args)
    summary = {"run_id": record.id, "status": record.status, "message": record.message,
               "base_ym_hub": record.base_ym_hub, "base_ym_related": record.base_ym_related,
               "steps": json.loads(record.steps_json)}
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0 if record.status in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
