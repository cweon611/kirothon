"""Operator commands for benefit data collection (no HTTP admin API: the project has no admin auth).

Run from backend/ with the same environment as the API:

    python -m app.team.benefits.cli sync [--source gov24_api|kto_tour50|all]
    python -m app.team.benefits.cli status
    python -m app.team.benefits.cli history [--source ...] [--limit 20]
    python -m app.team.benefits.cli versions <source_key> [--source ...]
    python -m app.team.benefits.cli list [--source ...]

Output never includes the service key or request URLs.
"""
import argparse
import json
import sys

from sqlmodel import Session, select


def _bootstrap():
    from ...database import DB_PATH, engine, init_db
    from ...main import app  # noqa: F401 -- register every model
    from ...schema_check import check_registered_schema
    check_registered_schema(DB_PATH)
    init_db()
    return engine


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(argv=None):
    from . import config, sync
    from .store_models import BenefitRecordVersion, BenefitSourceRecord, BenefitSyncRun

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--source", choices=[*config.SOURCES, "all"], default="all")
    sub.add_parser("status")
    h = sub.add_parser("history")
    h.add_argument("--source", choices=config.SOURCES)
    h.add_argument("--limit", type=int, default=20)
    v = sub.add_parser("versions")
    v.add_argument("source_key")
    v.add_argument("--source", choices=config.SOURCES, default="kto_tour50")
    ls = sub.add_parser("list")
    ls.add_argument("--source", choices=config.SOURCES)
    args = p.parse_args(argv)

    engine = _bootstrap()
    factory = lambda: Session(engine)  # noqa: E731

    if args.cmd == "sync":
        sources = config.SOURCES if args.source == "all" else (args.source,)
        out = []
        for src in sources:
            run = sync.run_sync(src, "manual", factory)
            out.append(run.model_dump(exclude={"id"}) | {"run_id": run.id})
        _print(out)
        return 0 if all(r["status"] in {"ok", "partial"} for r in out) else 1
    with factory() as session:
        if args.cmd == "status":
            states = sync.source_states(session)
            _print({src: {
                "last_attempt_at": st.last_attempt_at if st else None,
                "last_success_at": st.last_success_at if st else None,
                "last_status": st.last_status if st else None,
                "last_error_code": st.last_error_code if st else None,
                "stale": sync.is_stale(st.last_success_at if st else None, src),
                "interval_seconds": config.interval_seconds(src),
                "scheduler_enabled": config.scheduler_enabled(),
                "lease_active": bool(st and st.lease_until),
                "records": len(session.exec(select(BenefitSourceRecord.id)
                                            .where(BenefitSourceRecord.source == src)).all()),
            } for src, st in states.items()})
        elif args.cmd == "history":
            q = select(BenefitSyncRun).order_by(BenefitSyncRun.id.desc()).limit(args.limit)
            if args.source:
                q = q.where(BenefitSyncRun.source == args.source)
            _print([r.model_dump() for r in session.exec(q).all()])
        elif args.cmd == "versions":
            rec = session.exec(select(BenefitSourceRecord).where(BenefitSourceRecord.source == args.source)
                               .where(BenefitSourceRecord.source_key == args.source_key)).first()
            if rec is None:
                print("not found", file=sys.stderr)
                return 1
            vers = session.exec(select(BenefitRecordVersion).where(BenefitRecordVersion.record_id == rec.id)
                                .order_by(BenefitRecordVersion.version)).all()
            _print([{"version": x.version, "captured_at": x.captured_at, "content_hash": x.content_hash,
                     "changed_fields": json.loads(x.changed_fields_json), "sync_run_id": x.sync_run_id}
                    for x in vers])
        elif args.cmd == "list":
            q = select(BenefitSourceRecord)
            if args.source:
                q = q.where(BenefitSourceRecord.source == args.source)
            _print([{"source": r.source, "source_key": r.source_key, "program_key": r.program_key,
                     "round_key": r.round_key, "title": r.title, "version": r.version,
                     "review_status": r.review_status, "last_success_at": r.last_success_at,
                     "content_changed_at": r.content_changed_at, "missing_since": r.missing_since}
                    for r in session.exec(q).all()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
