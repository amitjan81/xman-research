"""Command line for the nightly scan and the template library.

Two commands, because there are two clocks. ``scan`` runs after the close and writes the
night's idea sheet. ``library`` maintains the set of templates the scan is allowed to
propose, which changes only when a human decides it does — an admission is somebody's
decision and the command demands their name for it.

    python -m xman_research.alpha.cli scan --as-of 2026-04-24 --universe NIFTY \\
        --top 10 --out ideas.json
    python -m xman_research.alpha.cli library seed-from-decision \\
        --template short_atm_straddle_hold_n --decision research/h1/decision.json
    python -m xman_research.alpha.cli library list
    python -m xman_research.alpha.cli library demote --template <id> --by <name> \\
        --reason "<why>"

``seed-from-decision`` files a template as a **candidate** unless ``--admit`` is given with
``--by``. The default is the conservative one: filing evidence and letting the ranker trade
on it are different acts, and a command that did both on one flag would make the second a
side effect of the first.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from xman_research.alpha.features import (
    DEFAULT_DECISION_TIME,
    DEFAULT_REGIME_LOOKBACK_SESSIONS,
    FeatureBuilder,
)
from xman_research.alpha.library import (
    DEFAULT_LIBRARY_PATH,
    AdmissionStatus,
    DecisionRecordError,
    TemplateLibrary,
)
from xman_research.alpha.ranker import NightlyScan
from xman_research.alpha.templates import UnknownTemplateError, default_registry
from xman_research.backtest.execution import ParticipationLimits
from xman_research.session_store import CalendarCoverageError, SessionStore, SessionStoreError

__all__ = ["build_parser", "main"]

_EXIT_OK = 0
_EXIT_REFUSED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m xman_research.alpha.cli",
        description="Rank admitted strategy templates for one session, and maintain the "
        "library of templates the ranker may propose.",
    )
    parser.add_argument(
        "--library",
        type=Path,
        default=DEFAULT_LIBRARY_PATH,
        help=f"path to the template library JSON (default: {DEFAULT_LIBRARY_PATH})",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan", help="write one night's idea sheet")
    scan.add_argument("--as-of", required=True, help="the session to scan, YYYY-MM-DD")
    scan.add_argument(
        "--universe",
        nargs="+",
        default=["NIFTY"],
        help="underlyings to scan, space separated (default: NIFTY)",
    )
    scan.add_argument("--top", type=int, default=10, help="how many ideas to keep")
    scan.add_argument("--out", type=Path, help="where to write the sheet; stdout if omitted")
    scan.add_argument("--corpus-root", type=Path, help="override the session store's corpus root")
    scan.add_argument(
        "--decision-time",
        default=DEFAULT_DECISION_TIME.isoformat(timespec="minutes"),
        help=f"minute of the session to act at (default: {DEFAULT_DECISION_TIME:%H:%M})",
    )
    scan.add_argument(
        "--regime-lookback",
        type=int,
        default=DEFAULT_REGIME_LOOKBACK_SESSIONS,
        help=(
            "sessions the volatility-regime tercile is cut over (default: "
            f"{DEFAULT_REGIME_LOOKBACK_SESSIONS}); a shorter window loads fewer sessions "
            "and describes a shorter history"
        ),
    )
    scan.add_argument(
        "--target-notional",
        type=float,
        help="override each template's declared exposure target, in rupees",
    )
    scan.add_argument(
        "--max-pct-of-bar-volume",
        type=float,
        default=ParticipationLimits().max_pct_of_bar_volume,
    )
    scan.add_argument(
        "--max-pct-of-open-interest",
        type=float,
        default=ParticipationLimits().max_pct_of_open_interest,
    )

    library = commands.add_parser("library", help="inspect and change template admissions")
    library_commands = library.add_subparsers(dest="library_command", required=True)

    library_commands.add_parser("list", help="print every template's current status")

    seed = library_commands.add_parser(
        "seed-from-decision",
        help="file a template's evidence from an existing decision record",
    )
    seed.add_argument("--template", required=True, help="registered template id")
    seed.add_argument("--decision", required=True, type=Path, help="path to decision.json")
    seed.add_argument(
        "--admit",
        action="store_true",
        help="file as ADMITTED rather than CANDIDATE; requires --by",
    )
    seed.add_argument("--by", help="who is making this decision")
    seed.add_argument("--reason", help="why; defaults to a description of the source record")
    seed.add_argument("--notes", help="free text carried on the entry")

    admit = library_commands.add_parser("admit", help="admit a template the ranker may propose")
    admit.add_argument("--template", required=True)
    admit.add_argument("--decision", required=True, type=Path)
    admit.add_argument("--by", required=True)
    admit.add_argument("--reason", required=True)
    admit.add_argument("--notes")

    demote = library_commands.add_parser("demote", help="stop the ranker proposing a template")
    demote.add_argument("--template", required=True)
    demote.add_argument("--by", required=True)
    demote.add_argument("--reason", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            return _scan(args)
        return _library(args, parser)
    except (
        CalendarCoverageError,
        DecisionRecordError,
        KeyError,
        SessionStoreError,
        UnknownTemplateError,
        ValueError,
    ) as error:
        # Refusals are the interesting outcome of this tool and are printed as one line on
        # stderr with a distinct exit code, so a nightly wrapper can tell "the scan declined"
        # from "the scan crashed" without parsing a traceback. The tuple covers every refusal
        # reachable from an argument: a date the corpus has no session for, a range the
        # exchange calendar does not cover, a corpus with a hole in it, a template id nothing
        # registers, and a decision record that is missing or unreadable.
        print(f"refused: {error}", file=sys.stderr)
        return _EXIT_REFUSED


def _scan(args: argparse.Namespace) -> int:
    as_of = dt.date.fromisoformat(args.as_of)
    store = SessionStore(root=args.corpus_root) if args.corpus_root else SessionStore()
    builder = FeatureBuilder(
        store,
        decision_time=dt.time.fromisoformat(args.decision_time),
        regime_lookback_sessions=args.regime_lookback,
    )
    sheet = NightlyScan(
        store=store,
        registry=default_registry(),
        library=TemplateLibrary.load(args.library),
        as_of=as_of,
        universe=args.universe,
        top_n=args.top,
        participation=ParticipationLimits(
            max_pct_of_bar_volume=args.max_pct_of_bar_volume,
            max_pct_of_open_interest=args.max_pct_of_open_interest,
        ),
        target_notional=args.target_notional,
        feature_builder=builder,
    ).run()
    document = json.dumps(sheet.as_dict(), indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(document)
        print(
            f"{args.out}: {len(sheet.ideas)} idea(s), {len(sheet.skipped)} skipped"
            + (f" — {sheet.no_ideas_reason}" if sheet.no_ideas_reason else "")
        )
    else:
        print(document, end="")
    return _EXIT_OK


def _library(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    registry = default_registry()
    library = TemplateLibrary.load(args.library)

    if args.library_command == "list":
        for template in registry:
            entry = library.current(template.template_id)
            status = str(entry.status) if entry else "unfiled"
            suffix = (
                f" — {entry.admitted_by} at {entry.admitted_at}: {entry.reason}"
                if entry
                else " — no entry in this library"
            )
            print(f"{template.template_id}: {status}{suffix}")
        return _EXIT_OK

    if args.library_command == "demote":
        entry = library.demote(template_id=args.template, by=args.by, reason=args.reason)
        library.save()
        print(f"{entry.template_id}: demoted by {entry.admitted_by}")
        return _EXIT_OK

    template = registry.get(args.template)
    if args.library_command == "seed-from-decision":
        if args.admit and not args.by:
            parser.error("--admit requires --by: an admission is somebody's decision")
        status = AdmissionStatus.ADMITTED if args.admit else AdmissionStatus.CANDIDATE
        by = args.by or "seed-from-decision"
        reason = args.reason or f"evidence filed from {args.decision}"
    else:
        status = AdmissionStatus.ADMITTED
        by = args.by
        reason = args.reason

    entry = library.admit(
        template=template,
        decision_path=args.decision,
        by=by,
        reason=reason,
        status=status,
        notes=args.notes,
    )
    library.save()
    card = entry.evidence
    print(
        f"{entry.template_id}: {entry.status} from {entry.decision_path} "
        f"(outcome={entry.decision_outcome}, gate={card.gate_status}, "
        f"n={card.n_observations}, mean return at hold={card.mean_return_at_hold})"
    )
    if not card.passed_gate:
        print(
            "note: this evidence did not clear its pre-registered gate. Any idea sheet "
            "resting on it is flagged `rests_on_unpassed_evidence`.",
            file=sys.stderr,
        )
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
