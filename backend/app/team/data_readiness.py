"""Read-only report: is the local DB ready for courses, festivals and support programs?

    python -m app.team.data_readiness            (run from backend/, same environment as the API)

Exit code: 0 when every one of the 27 sigungu can build a course (spots + food + stay collected),
1 otherwise. Only counts and timestamps are printed; never keys or request URLs.
"""
import json
import sys

from sqlmodel import Session, func, select

COURSE_TYPES = {"spot": ("12", "14", "28"), "food": ("39",), "stay": ("32",)}


def report(session: Session) -> dict:
    from .date_recommend import benefit_sources, festival_source
    from .regions import sigungu_map
    from .tourism_data import cache_stats
    from .tourism_models import Place

    rows = session.exec(select(Place.sigungu_code, Place.content_type_id, func.count())
                        .group_by(Place.sigungu_code, Place.content_type_id)).all()
    counts: dict[str, dict[str, int]] = {}
    for code, ctype, n in rows:
        for kind, types in COURSE_TYPES.items():
            if ctype in types:
                counts.setdefault(code or "", {}).setdefault(kind, 0)
                counts[code or ""][kind] += n
    regions, missing = [], []
    for code, region in sigungu_map().items():
        c = {kind: counts.get(code, {}).get(kind, 0) for kind in COURSE_TYPES}
        lacking = [kind for kind, n in c.items() if n == 0]
        regions.append({"sigungu_code": code, "name": region.label, **c,
                        "course_ready": c["spot"] > 0, "lacking": lacking})
        if c["spot"] == 0:
            missing.append(region.label)
    tourism = cache_stats(session)
    benefits = benefit_sources(session)
    festivals = festival_source(session)
    return {
        "course": {"ready": not missing and tourism["status"] != "empty",
                   "regions_ready": sum(r["course_ready"] for r in regions), "regions_total": len(regions),
                   "regions_without_spots": missing,
                   "regions_without_food_or_stay": [r["name"] for r in regions if r["course_ready"] and r["lacking"]],
                   "tourism_data": tourism},
        "festivals": festivals,
        "benefits": benefits,
        "regions": regions,
    }


def main(argv=None) -> int:
    from ..database import DB_PATH, engine, init_db
    from ..main import app  # noqa: F401 -- register every model
    from ..schema_check import check_registered_schema
    check_registered_schema(DB_PATH)
    init_db()
    with Session(engine) as session:
        data = report(session)
    print(json.dumps(data, ensure_ascii=False, indent=1, default=str))
    return 0 if data["course"]["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
