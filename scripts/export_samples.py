"""Export collected data and real API responses for frontend work, without any keys.

Reads a copy of the local DB (.local-data/records.sqlite3 by default), so the
source DB is never modified. Public-data keys are removed from this process's
environment first, so no external API is called and no key can reach the output.

    backend\\.venv\\Scripts\\python.exe scripts\\export_samples.py [--db PATH] [--out samples] [--today YYYY-MM-DD]

Writes:
    <out>/tables/*.json  collected rows (places, hub ranks, related places, benefit records)
    <out>/api/*.json     {request, status, response} for each frontend-facing endpoint
    <out>/api/openapi.json and <out>/manifest.json
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
KEY_VARS = ("TOURAPI_SERVICE_KEY", "KIROTHON_DATA_GO_KR_SERVICE_KEY")

# Collected tables worth sharing. course/record hold user input; *_version/*_run/*_state are internal.
TABLES = {
    "places": ("place", None),
    "hub_rank": ("hub_rank", None),
    "related_place": ("related_place", None),
    "benefit_records": ("benefit_source_record", {"raw_json"}),
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=ROOT / ".local-data" / "records.sqlite3")
    parser.add_argument("--out", type=Path, default=ROOT / "samples")
    parser.add_argument("--today", type=date.fromisoformat, default=datetime.now(KST).date(),
                        help="service 'today' (TEAM_TODAY); request dates are set relative to it")
    return parser.parse_args()


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def write_rows(path: Path, rows: list[dict]) -> None:
    """A JSON array with one compact row per line: small, and diffs stay per row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ",\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows)
    path.write_text(f"[\n{lines}\n]\n" if rows else "[]\n", encoding="utf-8", newline="\n")


def export_tables(db: Path, out: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    counts = {}
    for name, (table, drop) in TABLES.items():
        rows = []
        for row in con.execute(f'SELECT * FROM "{table}"'):
            item = {}
            for key in row.keys():
                if drop and key in drop:
                    continue
                value = row[key]
                if key.endswith("_json") and isinstance(value, str):
                    value = json.loads(value)
                item[key] = value
            rows.append(item)
        write_rows(out / "tables" / f"{name}.json", rows)
        counts[name] = len(rows)
    con.close()
    return counts


def export_api(out: Path, today: date) -> list[str]:
    from fastapi.testclient import TestClient
    from app.main import app

    saved = []
    start = today + timedelta(days=11)
    end = start + timedelta(days=1)

    def call(client, name, method, path, body=None, params=None):
        res = client.request(method, path, json=body, params=params)
        record = {"request": {"method": method, "path": path, "params": params, "body": body},
                  "status": res.status_code, "response": res.json()}
        write(out / "api" / f"{name}.json", record)
        saved.append(f"{name} {res.status_code}")
        return res.json() if res.status_code < 400 else None

    trip = {"trip_type": "1N2D", "start_date": start.isoformat(), "origin": "gj-buk",
            "interests": ["nature", "history"], "party_size": 2, "transport": "car",
            "residence_code": "29170", "benefit_conditions": {"birth_date": "1995-03-01"}}
    with TestClient(app) as client:
        write(out / "api" / "openapi.json", client.get("/openapi.json").json())
        call(client, "01-team-meta", "GET", "/api/team/meta")
        call(client, "02-team-programs", "GET", "/api/team/programs")
        rec = call(client, "03-team-recommend", "POST", "/api/team/recommend", trip)
        regions = (rec or {}).get("regions") or []
        top = regions[0] if regions else {}
        course_body = {k: v for k, v in trip.items() if k != "benefit_conditions"}
        course_body.update(sigungu_code=top.get("sigungu_code") or "46840",
                           program_id=(top.get("refund") or {}).get("program_id"),
                           meal_cost_krw=12000, room_price_krw=None)
        course = call(client, "04-team-course-create", "POST", "/api/team/courses", course_body)
        if course:
            cid = course["id"]
            call(client, "05-team-course-get", "GET", f"/api/team/courses/{cid}")
            call(client, "06-team-course-reasons", "POST", f"/api/team/courses/{cid}/reasons", {"day": 1})
            spot = next((i for d in course["days"] for i in d["items"] if i["kind"] == "spot"), None)
            if spot:
                cand = call(client, "07-team-course-candidates", "GET", f"/api/team/courses/{cid}/candidates",
                            params={"day": course["days"][0]["day"], "order": spot["order"]})
                call(client, "08-team-place-detail", "GET", f"/api/team/places/{spot['place']['content_id']}",
                     params={"date": start.isoformat()})
                if cand and cand.get("candidates"):
                    call(client, "09-team-course-swap", "POST", f"/api/team/courses/{cid}/swap",
                         {"day": cand["day"], "order": cand["order"],
                          "content_id": cand["candidates"][0]["content_id"]})
            call(client, "10-team-course-refund", "POST", f"/api/team/courses/{cid}/refund",
                 {"residence_code": "29170", "benefit_conditions": {"birth_date": "1995-03-01"}})
        call(client, "11-team-date-recommendations", "POST", "/api/team/date-recommendations",
             {"start_date": start.isoformat(), "end_date": end.isoformat(), "residence": "29170",
              "party_size": 2, "birth_date": "1995-03-01"})
        check = call(client, "12-benefits-check", "POST", "/api/benefits/check", {
            "departure": {"sido": "광주광역시", "sigungu": "북구"},
            "residence": {"sido": "광주광역시", "sigungu": "북구"},
            "trip_start": start.isoformat(), "trip_end": (start + timedelta(days=2)).isoformat(),
            "party_size": 2, "birth_date": "1995-03-01", "prior_participated_program_ids": [],
            "reference_date": today.isoformat(),
            "visits": [
                {"region": {"sido": "전라남도", "sigungu": "무안군"},
                 "start_date": start.isoformat(), "end_date": end.isoformat(), "nights": 1,
                 "places": ["무안황토갯벌랜드", "회산백련지"],
                 "expected_spend": {"by_category": {"lodging": 100000, "food": 96000, "transport": 30000}}},
                {"region": {"sido": "전라남도", "sigungu": "장흥군"},
                 "start_date": end.isoformat(), "end_date": (start + timedelta(days=2)).isoformat(), "nights": 1},
            ]})
        call(client, "13-benefits-sources", "GET", "/api/benefits/sources")
        first = next(iter((check or {}).get("results") or []), None)
        if first:
            call(client, "14-benefits-detail", "GET", f"/api/benefits/{first['benefit_id']}")
    return saved


def main() -> int:
    args = parse_args()
    if not args.db.is_file():
        raise SystemExit(f"DB not found: {args.db}")
    for name in KEY_VARS:
        os.environ.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="kirothon-samples-") as tmp:
        db = Path(tmp) / "records.sqlite3"
        shutil.copyfile(args.db, db)
        codes = args.db.with_name("tourism-codes.json")
        if codes.is_file():
            shutil.copyfile(codes, Path(tmp) / codes.name)
        os.environ.update(KIROTHON_DB_PATH=str(db), KIROTHON_AI_MODE="mock", TEAM_TODAY=args.today.isoformat())
        sys.path.insert(0, str(ROOT / "backend"))
        if args.out.exists():
            shutil.rmtree(args.out / "tables", ignore_errors=True)
            shutil.rmtree(args.out / "api", ignore_errors=True)
        counts = export_tables(db, args.out)
        calls = export_api(args.out, args.today)
        from app.database import engine
        engine.dispose()
    write(args.out / "manifest.json", {"generated_at": datetime.now(KST).isoformat(timespec="seconds"),
                                       "service_today": args.today.isoformat(), "ai_mode": "mock",
                                       "external_calls": False, "tables": counts, "api_calls": calls})
    print(json.dumps({"tables": counts, "api_calls": calls}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
