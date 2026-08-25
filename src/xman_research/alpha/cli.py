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
    python -m xman_research.alpha.cli screen --spec research/screen/spec.toml \\
        --out research/screen/sheet.json
    python -m xman_research.alpha.cli library seed-from-screen \\
        --sheet research/screen/sheet.json --rank 1 --by <name>

``screen`` is the offline loop's stage one: it runs every instance a TOML spec names over an
in-sample window, appends each as a trial, and writes a ranked sheet. It grades nothing —
``seed-from-screen`` can therefore only file a template as a **candidate**, and admission
stays with ``admit``, which reads a decision record and refuses an unpassed one without a
written override.

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
    LibraryFileError,
    TemplateLibrary,
    UnpassedEvidenceError,
)
from xman_research.alpha.ranker import NightlyScan
from xman_research.alpha.screen import (
    ScreeningRun,
    ScreeningRunError,
    evidence_card_from_screen,
    load_screen_sheet,
)
from xman_research.alpha.spec import ScreenSpecError, load_screen_spec
from xman_research.alpha.templates import UnknownTemplateError, default_registry
from xman_research.backtest.engine import BacktestConfig
from xman_research.backtest.execution import ParticipationLimits
from xman_research.evaluation import open_session
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

    screen = commands.add_parser(
        "screen", help="run one stage-one screen and write its ranked sheet"
    )
    screen.add_argument("--spec", required=True, type=Path, help="path to the screen spec TOML")
    screen.add_argument("--out", required=True, type=Path, help="where to write the sheet JSON")
    screen.add_argument("--corpus-root", type=Path, help="override the session store's corpus root")
    screen.add_argument(
        "--trial-log",
        type=Path,
        help=(
            "where to append this screen's trials; defaults to the path the spec names. "
            "Every instance is logged before its number is read, so a stage-two gate filed "
            "against the same hypothesis deflates against the whole screen."
        ),
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

    seed_screen = library_commands.add_parser(
        "seed-from-screen",
        help="file a screened instance as a candidate, from a screen sheet",
    )
    seed_screen.add_argument("--sheet", required=True, type=Path, help="path to a screen sheet")
    seed_screen.add_argument(
        "--rank",
        type=int,
        default=1,
        help="which ranked instance to file, one-based (default: the top one)",
    )
    seed_screen.add_argument("--by", help="who is filing this evidence")
    seed_screen.add_argument("--reason", help="why; defaults to a description of the sheet")
    seed_screen.add_argument("--notes")

    admit = library_commands.add_parser("admit", help="admit a template the ranker may propose")
    admit.add_argument("--template", required=True)
    admit.add_argument("--decision", required=True, type=Path)
    admit.add_argument("--by", required=True)
    admit.add_argument("--reason", required=True)
    admit.add_argument("--notes")
    admit.add_argument(
        "--override-reason",
        help=(
            "required to admit on a decision record that did not pass its gate; recorded "
            "verbatim on the entry"
        ),
    )

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
        if args.command == "screen":
            return _screen(args)
        return _library(args)
    except (
        CalendarCoverageError,
        DecisionRecordError,
        LibraryFileError,
        ScreenSpecError,
        ScreeningRunError,
        SessionStoreError,
        UnknownTemplateError,
        UnpassedEvidenceError,
        ValueError,
    ) as error:
        # Refusals are the interesting outcome of this tool and are printed as one line on
        # stderr with a distinct exit code, so a nightly wrapper can tell "the scan declined"
        # from "the scan crashed" without parsing a traceback. The tuple covers every refusal
        # reachable from an argument: a date the corpus has no session for, a range the
        # exchange calendar does not cover, a corpus with a hole in it, a template id nothing
        # registers, a decision record that is missing or unreadable, and a library file this
        # reader does not understand. `KeyError` is deliberately absent — a missing key while
        # deserialising a library entry is a corrupt file, not a refusal, and printing it as
        # one would hide a crash behind an orderly exit code.
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


def _screen(args: argparse.Namespace) -> int:
    spec = load_screen_spec(args.spec)
    store = SessionStore(root=args.corpus_root) if args.corpus_root else SessionStore()
    log_path = args.trial_log if args.trial_log else spec.trial_log_path
    builder = FeatureBuilder(store, decision_time=spec.decision_time)
    # `open_session` is this package's wiring boundary: the one place a SystemClock and a
    # git version provider are constructed. Building a TrialLog directly here would make
    # the CLI a second such place, free to disagree with the first about either.
    research = open_session(log_path)
    try:
        sheet = ScreeningRun(
            store=store,
            registry=default_registry(),
            trial_log=research.log,
            hypothesis=spec.hypothesis,
            window=spec.window,
            benchmark=spec.benchmark,
            candidates=spec.candidates,
            config=BacktestConfig(underlying=spec.underlying, decision_time=spec.decision_time),
            gaps_reason=spec.gaps_reason,
            feature_builder=builder,
        ).run()
    finally:
        research.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(sheet.as_dict(), indent=2, sort_keys=True) + "\n")
    print(
        f"{args.out}: {len(sheet.instances)} instance(s) over {sheet.window}, "
        f"{sheet.n_trials_logged} trial(s) logged to {log_path}"
    )
    for rank, row in enumerate(sheet.instances[:5], start=1):
        alpha = "unmeasured" if row.alpha is None else f"{row.alpha:+.3f}"
        print(f"  {rank}. {row.instance.instance_id}: alpha={alpha} n={row.n_observations}")
    return _EXIT_OK


def _seed_from_screen(args: argparse.Namespace, library: TemplateLibrary, registry) -> int:
    sheet = load_screen_sheet(args.sheet)
    if args.rank < 1 or args.rank > len(sheet.instances):
        raise ValueError(
            f"--rank {args.rank} names no instance: the sheet at {args.sheet} ranks "
            f"{len(sheet.instances)} of them"
        )
    row = sheet.instances[args.rank - 1]
    card = evidence_card_from_screen(sheet, row.instance.instance_id, source=str(args.sheet))
    entry = library.seed_from_screen(
        template=registry.get(row.instance.template_id),
        evidence=card,
        sheet_path=args.sheet,
        by=args.by or "seed-from-screen",
        reason=args.reason or f"rank {args.rank} of the screen at {args.sheet}",
        trial_ids=(row.trial_id,),
        notes=args.notes,
    )
    library.save()
    print(
        f"{entry.template_id}: {entry.status} from {entry.decision_path} "
        f"(instance={row.instance.instance_id}, alpha={row.alpha}, n={row.n_observations})"
    )
    print(
        "note: a screening sheet applies no threshold and pre-registers none. This "
        "instance is a CANDIDATE and the ranker will not propose it; admission needs a "
        "decision record.",
        file=sys.stderr,
    )
    return _EXIT_OK


def _library(args: argparse.Namespace) -> int:
    registry = default_registry()
    library = TemplateLibrary.load(args.library)

    if args.library_command == "list":
        # The union, not just the registry: a library entry whose template id is no longer
        # registered is exactly the case the ranker reports as `template_not_registered`, and
        # listing only registered ids would make the one entry a reader needs to find
        # invisible in the command that exists to find it.
        filed = {entry.template_id for entry in library.entries()}
        for template_id in sorted(set(registry.ids()) | filed):
            entry = library.current(template_id)
            status = str(entry.status) if entry else "unfiled"
            suffix = (
                f" — {entry.admitted_by} at {entry.admitted_at}: {entry.reason}"
                if entry
                else " — no entry in this library"
            )
            unregistered = "" if template_id in registry else " [NOT REGISTERED]"
            print(f"{template_id}: {status}{unregistered}{suffix}")
        return _EXIT_OK

    if args.library_command == "seed-from-screen":
        return _seed_from_screen(args, library, registry)

    if args.library_command == "demote":
        entry = library.demote(template_id=args.template, by=args.by, reason=args.reason)
        library.save()
        print(f"{entry.template_id}: demoted by {entry.admitted_by}")
        return _EXIT_OK

    template = registry.get(args.template)
    if args.library_command == "seed-from-decision":
        if args.admit and not args.by:
            raise ValueError("--admit requires --by: an admission is somebody's decision")
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
        override_reason=getattr(args, "override_reason", None),
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
