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
    python -m xman_research.alpha.cli track record --sheet ideas.json
    python -m xman_research.alpha.cli track settle --through 2026-04-30 \\
        [--demote-by <name>]
    python -m xman_research.alpha.cli track report [--template <id>]

``track`` closes the loop the other two open: ``record`` files what one night's sheet
proposed, ``settle`` marks every idea whose hold has elapsed at the prices the market
actually printed, and ``report`` prints realised against admitted per template. ``settle``
reports which admitted points breach the demotion rule and files the demotions only when
``--demote-by`` names whoever is accountable for them — the same convention ``library
demote`` follows, for the same reason.

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
from xman_research.alpha.gate import (
    DECISION_RECORD_NAME,
    StageTwoGateError,
    run_stage_two_gate,
)
from xman_research.alpha.library import (
    DEFAULT_LIBRARY_PATH,
    AdmissionStatus,
    AdmittedParametersMismatchError,
    AmbiguousParameterPointError,
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
from xman_research.alpha.templates import (
    TemplateRegistry,
    UnknownTemplateError,
    default_registry,
)
from xman_research.alpha.tracking import (
    DEFAULT_LEDGER_PATH,
    DEFAULT_MIN_SETTLED,
    DEFAULT_WINDOW,
    STATUS_SETTLED,
    IdeaLedger,
    LedgerError,
    apply_demotions,
)
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

    stage_two = commands.add_parser(
        "gate", help="grade one screened instance against a pre-registered gate"
    )
    stage_two.add_argument("--sheet", required=True, type=Path, help="path to a screen sheet")
    stage_two.add_argument(
        "--rank", type=int, default=1, help="which ranked instance to grade, one-based"
    )
    stage_two.add_argument(
        "--gate", required=True, type=Path, help="path to the pre-registered gate TOML"
    )
    stage_two.add_argument(
        "--out", required=True, type=Path, help=f"directory to write {DECISION_RECORD_NAME} into"
    )
    stage_two.add_argument(
        "--seal-override",
        help=(
            "written reason for grading a holdout that ends on or after the corpus-wide "
            "seal; recorded in the decision record. Without it such a window is refused"
        ),
    )
    stage_two.add_argument(
        "--holdout-end",
        required=True,
        help=(
            "last date of the holdout, YYYY-MM-DD. Required rather than defaulted: where the "
            "unseen months end is a pre-registration, and the holdout is read only if the "
            "in-sample verdict passes"
        ),
    )
    stage_two.add_argument(
        "--holdout-first",
        help="first date of the holdout (default: the day after the screened window)",
    )
    stage_two.add_argument(
        "--corpus-root", type=Path, help="override the session store's corpus root"
    )
    stage_two.add_argument(
        "--trial-log",
        type=Path,
        help="where to append this run's trials; defaults to the log the sheet names",
    )
    stage_two.add_argument(
        "--gaps-reason",
        help="override the gap policy; defaults to the one the screened sheet recorded",
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
    seed.add_argument(
        "--override-reason",
        help=(
            "required with --admit when the decision record did not pass its gate; "
            "recorded verbatim on the entry"
        ),
    )

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
    demote.add_argument(
        "--point",
        help=(
            "which admitted parameter point to demote, as the key `library list` prints. "
            "Required when the template is filed at more than one: a bare id names two "
            "different trades"
        ),
    )

    track = commands.add_parser("track", help="record presented ideas and mark what they made")
    track.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help=f"path to the idea ledger JSON (default: {DEFAULT_LEDGER_PATH})",
    )
    track_commands = track.add_subparsers(dest="track_command", required=True)

    track_record = track_commands.add_parser("record", help="file every idea on one night's sheet")
    track_record.add_argument("--sheet", required=True, type=Path, help="path to an idea sheet")

    track_settle = track_commands.add_parser(
        "settle", help="mark every open idea whose hold has elapsed"
    )
    track_settle.add_argument(
        "--seal-override",
        help=(
            "written reason for settling through a date on or after the corpus-wide seal; "
            "recorded on every row it allowed. Without it such a date is refused"
        ),
    )
    track_settle.add_argument(
        "--through",
        required=True,
        help=(
            "settle using sessions up to and including this date, YYYY-MM-DD. Nothing later "
            "is ever read, which is what keeps a sealed holdout sealed"
        ),
    )
    track_settle.add_argument(
        "--corpus-root", type=Path, help="override the session store's corpus root"
    )
    track_settle.add_argument(
        "--decision-time",
        default=DEFAULT_DECISION_TIME.isoformat(timespec="minutes"),
        help=f"minute of the session marks are taken at (default: {DEFAULT_DECISION_TIME:%H:%M})",
    )
    track_settle.add_argument(
        "--gaps-reason",
        help="accept missing sessions inside the settlement range, against this written reason",
    )
    track_settle.add_argument(
        "--demote-by",
        help=(
            "run the demotion rule after settling and file any breach under this name. "
            "Omitted, the rule is only reported: demoting a template is somebody's decision "
            "and the library records whose"
        ),
    )
    _add_drift_arguments(track_settle)

    track_report = track_commands.add_parser(
        "report", help="print realised against expected, per admitted point"
    )
    track_report.add_argument("--template", help="restrict the report to one template id")
    _add_drift_arguments(track_report)
    return parser


def _add_drift_arguments(parser: argparse.ArgumentParser) -> None:
    """The two knobs the drift statistics take, on every command that computes them.

    Both are shared rather than defaulted per command so that a settle and the report that
    follows it cannot silently judge the same ledger over two different windows.

    ``--min-settled`` may only be raised. The demotion rule's claim is that it was written
    before the first observation, and a floor an operator could lower on the night is a floor
    that can be argued down after seeing a bad month — ``--min-settled 1`` would demote a
    template on one idea. ``--window`` stays free in both directions: it changes how much
    evidence is looked at, not how little is enough to act. Both land in every report's
    :meth:`~xman_research.alpha.tracking.DriftReport.summary`, which is what a demotion's
    recorded reason is made of.
    """
    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW,
        help=f"settled ideas the drift statistics look back over (default: {DEFAULT_WINDOW})",
    )
    parser.add_argument(
        "--min-settled",
        type=int,
        default=DEFAULT_MIN_SETTLED,
        help=(
            "settled ideas below which no demotion may fire, however bad the numbers "
            f"(default and floor: {DEFAULT_MIN_SETTLED}; a smaller value is refused)"
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "min_settled", DEFAULT_MIN_SETTLED) < DEFAULT_MIN_SETTLED:
        parser.error(
            f"--min-settled {args.min_settled} is below the floor {DEFAULT_MIN_SETTLED}. The "
            "rule this feeds claims it cannot be retuned after seeing a bad month, and a "
            "floor that can be lowered on the night is exactly that retuning."
        )
    try:
        if args.command == "scan":
            return _scan(args)
        if args.command == "screen":
            return _screen(args)
        if args.command == "gate":
            return _gate(args)
        if args.command == "track":
            return _track(args)
        return _library(args)
    except (
        AdmittedParametersMismatchError,
        AmbiguousParameterPointError,
        CalendarCoverageError,
        DecisionRecordError,
        LedgerError,
        LibraryFileError,
        ScreenSpecError,
        ScreeningRunError,
        SessionStoreError,
        StageTwoGateError,
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
        print(
            f"  {rank}. {row.instance.instance_id}: alpha={alpha} "
            f"n={row.n_observations} entered={row.sessions_entered} ({row.outcome})"
        )
    return _EXIT_OK


def _gate(args: argparse.Namespace) -> int:
    """Stage two: one screened instance, one pre-registered gate, one decision record."""
    run = run_stage_two_gate(
        sheet_path=args.sheet,
        gate_path=args.gate,
        out_dir=args.out,
        rank=args.rank,
        holdout_end=dt.date.fromisoformat(args.holdout_end),
        holdout_first=(dt.date.fromisoformat(args.holdout_first) if args.holdout_first else None),
        store=SessionStore(root=args.corpus_root) if args.corpus_root else None,
        trial_log_path=args.trial_log,
        gaps_reason=args.gaps_reason,
        seal_override=args.seal_override,
    )
    print(run.decision.summary())
    print()
    print(f"{args.out / DECISION_RECORD_NAME}: {run.decision.outcome}")
    print(
        f"family trial count at decision: {run.trial_count} "
        f"(the screen at {run.sheet_path} contributed {run.screen_trials})"
    )
    print(f"holdout spent: {run.holdout_spent}")
    return _EXIT_OK


def _track(args: argparse.Namespace) -> int:
    """The forward loop: what was proposed, what it made, and whether it still earns its place."""
    ledger = IdeaLedger.load(args.ledger)
    if args.track_command == "record":
        recorded = ledger.record_sheet(json.loads(args.sheet.read_text()))
        ledger.save()
        print(f"{args.ledger}: recorded {len(recorded)} idea(s) from {args.sheet}")
        for idea in recorded:
            print(
                f"  {idea.as_of} {idea.template_id} [{idea.parameter_key or 'no parameters'}] "
                f"{idea.underlying}: {idea.granted_lots} lot(s), expected "
                f"{idea.expected_edge:+.6g} over {idea.hold_sessions} session(s)"
            )
        return _EXIT_OK

    library = TemplateLibrary.load(args.library)
    if args.track_command == "settle":
        settled = ledger.settle(
            as_of_end=dt.date.fromisoformat(args.through),
            store=SessionStore(root=args.corpus_root) if args.corpus_root else SessionStore(),
            decision_time=dt.time.fromisoformat(args.decision_time),
            gaps_reason=args.gaps_reason,
            seal_override=args.seal_override,
        )
        ledger.save()
        marked = sum(1 for entry in settled if entry.status == STATUS_SETTLED)
        print(
            f"{args.ledger}: settled {marked} idea(s) through {args.through}, "
            f"{len(settled) - marked} unmarkable, {len(ledger.open_ideas())} still open"
        )
        for entry in settled:
            if entry.realised_return is None:
                print(f"  {entry.as_of} {entry.template_id}: UNMARKABLE — {entry.reason}")
            else:
                print(
                    f"  {entry.as_of} {entry.template_id}: realised "
                    f"{entry.realised_return:+.6g} vs expected {entry.expected_return:+.6g} "
                    f"(drift {entry.drift:+.6g}), exited {entry.exit_as_of}"
                )
        reports = ledger.drift(library, window=args.window, min_settled=args.min_settled)
        if args.demote_by:
            demoted = apply_demotions(reports, library, by=args.demote_by)
            if demoted:
                library.save()
            print(f"{args.library}: demoted {len(demoted)} admitted point(s)")
            for report in demoted:
                print(f"  {report.summary()}")
        else:
            breached = [report for report in reports if report.breached]
            print(
                f"{len(breached)} admitted point(s) breach the demotion rule; pass --demote-by "
                "to file the demotions"
            )
            for report in breached:
                print(f"  {report.summary()}")
        return _EXIT_OK

    reports = ledger.drift(
        library,
        window=args.window,
        min_settled=args.min_settled,
        template_id=args.template,
    )
    if not reports:
        print(f"{args.ledger}: no settled ideas to report on")
        return _EXIT_OK
    for report in reports:
        print(report.summary())
        card = report.card_mean_return_at_hold
        print(
            f"    admitted mean return at hold: "
            f"{'none on the card' if card is None else format(card, '+.6g')}"
        )
        per_trip = report.card_mean_return_per_round_trip
        print(
            f"    admitted mean return per round trip: "
            f"{'none on the card' if per_trip is None else format(per_trip, '+.6g')}"
            f" (each promised edge scaled by {report.expected_scale:.4g} to reach it)"
        )
        if report.realised_hit_rate is not None:
            deviation = report.hit_rate_deviation
            print(
                f"    hit rate: {report.realised_hit_rate:.3f} realised"
                + (
                    ""
                    if deviation is None
                    else f", {deviation:+.3f} against the admitted {report.card_hit_rate:.3f}"
                )
            )
        if report.cusum is not None and report.cusum_threshold is not None:
            print(
                f"    drift CUSUM: {report.cusum:.6g} against a threshold of "
                f"{report.cusum_threshold:.6g} (sigma {report.sigma:.6g})"
            )
        if report.t_statistic is not None:
            print(f"    one-sided t on realised: {report.t_statistic:.4g}")
    return _EXIT_OK


def _seed_from_screen(
    args: argparse.Namespace, library: TemplateLibrary, registry: TemplateRegistry
) -> int:
    sheet = load_screen_sheet(args.sheet)
    if args.rank < 1 or args.rank > len(sheet.instances):
        raise ValueError(
            f"--rank {args.rank} names no instance: the sheet at {args.sheet} ranks "
            f"{len(sheet.instances)} of them"
        )
    row = sheet.instances[args.rank - 1]
    template = registry.get(row.instance.template_id)
    card = evidence_card_from_screen(
        sheet, row.instance.instance_id, source=str(args.sheet), template=template
    )
    entry = library.seed_from_screen(
        template=template,
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


def _point_named(
    library: TemplateLibrary, template_id: str, key: str | None
) -> dict[str, float] | None:
    """The parameter point ``key`` names, or ``None`` to let the library decide.

    ``None`` is passed through rather than resolved here, so a template filed at two points
    is refused by :meth:`TemplateLibrary.current` with its own message instead of by a
    second check that could disagree with it.
    """
    if key is None:
        return None
    for entry in reversed(library.history(template_id)):
        if entry.parameter_key == key:
            return dict(entry.parameters)
    raise ValueError(
        f"template {template_id!r} has no entry at [{key}]; it is filed at "
        f"{list(library.points(template_id))}"
    )


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
            unregistered = "" if template_id in registry else " [NOT REGISTERED]"
            points = library.points(template_id)
            if not points:
                print(f"{template_id}: unfiled{unregistered} — no entry in this library")
                continue
            # One line per point, not per template. A template admitted at two points is two
            # admissions carrying two different sets of numbers, and a listing that showed
            # only the latest would hide whichever the ranker is also proposing tonight.
            latest = {row.parameter_key: row for row in library.history(template_id)}
            for key in points:
                entry = latest[key]
                print(
                    f"{template_id}[{key}]: {entry.status}{unregistered} — "
                    f"{entry.admitted_by} at {entry.admitted_at}: {entry.reason}"
                )
                if entry.override_reason:
                    # On its own line and unabbreviated: an admission over unpassed evidence
                    # is the one thing in this listing a reader must not be able to skim past.
                    print(f"    ADMITTED OVER UNPASSED EVIDENCE: {entry.override_reason}")
        return _EXIT_OK

    if args.library_command == "seed-from-screen":
        return _seed_from_screen(args, library, registry)

    if args.library_command == "demote":
        entry = library.demote(
            template_id=args.template,
            by=args.by,
            reason=args.reason,
            parameters=_point_named(library, args.template, args.point),
        )
        library.save()
        print(f"{entry.template_id}[{entry.parameter_key}]: demoted by {entry.admitted_by}")
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
        override_reason=args.override_reason,
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
