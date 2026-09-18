"""A store that hands the engine modelled bars for strikes the capture does not carry.

**This fabricates data, and the point of the module is to fabricate it in exactly one
place, under one name, with one stamp.** The capture holds roughly a +/-2.3% strike band
around spot, and ST-7's 350-point wing sits outside it in 289 of the 295 entry-window
sessions. A backtest of the specified structure is therefore impossible from prints alone.
The choice made — with the owner, before any result existed — was to run *both* arms: an
observed arm that narrows the wing to what printed, and this one, which keeps the specified
wing and models it.

Three properties keep the fabrication bounded:

1. **Only wings.** Synthetic bars carry ``iv = NaN``. Short-strike selection (ST-6) requires
   an implied volatility, so a synthetic strike can never become a *short* leg — it can only
   ever be bought. The long leg is the one whose mispricing costs the strategy money rather
   than making it.
2. **Only where nothing printed.** A strike that traded is never overwritten.
3. **Liquidity is haircut, not invented.** Volume and open interest are taken from the
   outermost strike that did print on that side and halved, then floored to a whole number
   of lots. The participation caps then bind on that, so a modelled wing cannot support a
   larger position than the observed band's edge could.

The pricing error was measured before use, by holdout, and is quoted in
:mod:`xman_research.overlay.greeks`: median Rs 1.42 per unit on a median true price of
Rs 14.35, biased Rs 1.48 *low*. A cheap long wing flatters the entry credit and depresses
the exit proceeds; the report says so rather than correcting it.
"""

from __future__ import annotations

import datetime as dt
import math
import os
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path

import pandas as pd

from xman_research.corpus_hygiene import clean_iv, underlying_spot
from xman_research.overlay.greeks import ObservedQuote, extrapolated_wing_price, year_fraction
from xman_research.session_store import SessionRef, SessionStore

__all__ = ["DEFAULT_CACHE_ROOT", "SYNTHETIC_WING_STAMP", "SyntheticWingStore"]

#: Bumped when the extension's inputs change, so a cached frame built by an older
#: derivation is not served. v2: spot comes from the index's own bar rather than the
#: snapshot on an arbitrary option row. v3: the edge quote's implied volatility goes
#: through :func:`~xman_research.corpus_hygiene.clean_iv`, so a solver artefact cannot
#: price a wing (see :mod:`xman_research.corpus_hygiene`).
DERIVATION = "v3"

#: Where extended session frames are kept between runs. Beside the corpus, never inside the
#: repository: it is regenerable output, and it is large.
DEFAULT_CACHE_ROOT = Path("/home/qa/runtime/data/research/overlay/extended")

SYNTHETIC_WING_STAMP = (
    "corpus.synthetic_wing_bars: long wing legs outside the captured strike band are "
    "modelled (flat edge implied volatility, Black-Scholes, calibrated to the edge strike's "
    "printed price), not observed. Holdout error: median Rs 1.42 per unit, bias Rs -1.48."
)

_IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


@dataclass(frozen=True, slots=True)
class _SymbolParts:
    expiry: dt.date
    strike: float
    option_type: str


def _parse(symbol: str) -> _SymbolParts | None:
    parts = symbol.split("-")
    if len(parts) != 4:
        return None
    try:
        expiry = dt.datetime.strptime(parts[1], "%d%b%Y").date()
        return _SymbolParts(expiry, float(parts[2]), parts[3])
    except ValueError:
        return None


class SyntheticWingStore(SessionStore):
    """A :class:`SessionStore` whose frames carry modelled far-wing bars.

    ``minutes`` restricts the fabrication to the decision minutes the run will actually act
    on, which is both cheaper and narrower: no minute the strategy never sees gets a
    modelled price. Marks between decision minutes therefore carry forward from the last
    one, which is the engine's existing behaviour for any contract that does not print.

    ``extend_points`` must cover the whole *life* of a position, not just its entry: a wing
    bought when spot was 24,000 still has to be sellable four sessions later when spot is
    23,300 and the captured band has moved with it. It is therefore wide (1,500 points),
    and the far end of that range is deep extrapolation — which is acceptable precisely
    because it is also where the option is worth pennies. The case that matters, a wing
    that has become valuable because spot ran at it, is the case where the band has moved
    over the strike and the price is a real print again.
    """

    def __init__(
        self,
        *args,
        minutes: tuple[dt.time, ...],
        extend_points: float = 1500.0,
        liquidity_haircut: float = 0.5,
        cache_root: Path | None = DEFAULT_CACHE_ROOT,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._minutes = frozenset(minutes)
        self._extend_points = extend_points
        self._liquidity_haircut = liquidity_haircut
        self._cache_root = (
            None
            if cache_root is None
            else Path(cache_root)
            / f"{DERIVATION}_ext{int(extend_points)}_m{len(self._minutes)}_h{liquidity_haircut:g}"
        )
        self.synthetic_rows = 0
        self.sessions_extended = 0
        self.sessions_from_cache = 0

    def _cache_path(self, ref: SessionRef) -> Path | None:
        """Where this session's extended frame is kept.

        **The extension is a pure function of the session, the strike window and the
        decision grid**, so a sweep of seven arms over the same corpus was rebuilding the
        same frames seven times — about fifty minutes an arm, most of it Black-Scholes on
        bars the previous arm had already priced. The cache key carries the two parameters
        that change the output, and :data:`DERIVATION` carries the ones that are a code
        change — so a derivation fix invalidates the cache instead of relying on someone
        remembering to delete it. The directory is regenerable output either way.
        """
        if self._cache_root is None:
            return None
        return self._cache_root / ref.underlying / f"{ref.session_date.isoformat()}.parquet"

    def load_refdata(self, ref: SessionRef):  # type: ignore[override]
        """The session's instrument master, extended to the strikes the wing needs.

        **The capture's refdata lists only the strikes the capture fetched** — 25 of them,
        exactly the band the bar file covers. NSE lists far more, but this corpus has no
        record of them, so a wing strike is not merely unpriced here: it is unlisted, and
        :meth:`ContractUniverse.get` returns nothing for it.

        Composing an instrument row is a deviation from this repository's standing rule that
        strikes, lot sizes, tick sizes and trading symbols are the exchange's to define and
        the platform's to read verbatim. It is made here, in the one module that already
        declares itself the fabrication boundary, because the alternative is that the
        specified structure cannot be backtested at all. The composed rows copy lot size and
        tick size from a real row of the same expiry and follow the vendor's own symbol
        format; nothing about them is guessed except that the exchange lists the strike,
        which for a 50-point ladder either side of a captured band it certainly does.
        """
        refdata = super().load_refdata(ref)
        rows = list(refdata.nfo_instruments)
        by_expiry: dict[tuple[dt.date, str], list[dict]] = {}
        for row in rows:
            parsed = _parse(str(row.get("TradingSymbol", "")))
            if parsed is None:
                continue
            by_expiry.setdefault((parsed.expiry, parsed.option_type), []).append(row)
        added: list[dict] = []
        for (expiry, option_type), group in by_expiry.items():
            strikes = sorted(float(row["StrikePrice"]) for row in group)
            if len(strikes) < 2:
                continue
            step = min(b - a for a, b in pairwise(strikes) if b > a)
            template = group[0]
            below = strikes[0]
            above = strikes[-1]
            count = int(self._extend_points // step)
            for index in range(1, count + 1):
                for strike in (below - index * step, above + index * step):
                    if strike <= 0:
                        continue
                    added.append(
                        {
                            **{
                                key: template[key]
                                for key in ("LookupName", "LotSize", "TickSize", "Segment")
                                if key in template
                            },
                            "ExpiryDate": template["ExpiryDate"],
                            "OptionType": option_type,
                            "StrikePrice": float(strike),
                            "TradingSymbol": _compose_symbol(
                                str(template.get("LookupName", "")), expiry, strike, option_type
                            ),
                            "Synthetic": True,
                        }
                    )
        if not added:
            return refdata
        return replace(refdata, nfo_instruments=tuple(rows + added))

    def load_session(self, ref: SessionRef, *, verify: bool = False) -> pd.DataFrame:
        cache = self._cache_path(ref)
        if (
            cache is not None
            and cache.is_file()
            and cache.stat().st_mtime >= ref.parquet_path.stat().st_mtime
        ):
            # Older than the session it extends means the corpus was re-captured underneath
            # it; rebuild rather than serve a frame derived from bars that no longer exist.
            self.sessions_from_cache += 1
            return pd.read_parquet(cache)
        frame = super().load_session(ref, verify=verify)
        refdata = self.load_refdata(ref)
        listed: dict[tuple[dt.date, str], dict[float, tuple[str, int]]] = {}
        for instrument in refdata.nfo_instruments:
            symbol = str(instrument.get("TradingSymbol", ""))
            parsed = _parse(symbol)
            if parsed is None:
                continue
            key = (parsed.expiry, parsed.option_type)
            listed.setdefault(key, {})[parsed.strike] = (symbol, int(instrument.get("LotSize", 0)))
        if not listed:
            return frame

        options = frame[frame.symbol.str.contains("-", regex=False)]
        if options.empty:
            return frame
        # The index's own bar is the only authority for spot; the column on an option row is
        # that row's snapshot and disagrees inside a minute on a third of sessions.
        own = underlying_spot(frame, ref.underlying, ref.session_date)
        spot_by_minute = dict(zip(own.minute_ts, own.spot, strict=True))
        rows: list[dict[str, object]] = []
        for minute_ts, minute_frame in options.groupby("minute_ts"):
            moment = dt.datetime.fromtimestamp(int(minute_ts) / 1e6, dt.UTC).astimezone(_IST)
            if moment.time() not in self._minutes:
                continue
            spot = spot_by_minute.get(minute_ts)
            if spot is None or spot <= 0:
                continue
            for symbol, quote_frame in _by_side(minute_frame):
                expiry, option_type = symbol
                quotes = [
                    ObservedQuote(
                        strike=row.strike,
                        # Through the corpus boundary, not raw: an edge strike carrying a
                        # 422% solver artefact would otherwise drive the Black-Scholes price
                        # of every wing extrapolated from it. `extrapolated_wing_price`
                        # filters `iv > 0`, which admits it.
                        iv=clean_iv(row.iv) or 0.0,
                        close=float(row.close),
                        volume_units=float(row.volume) if pd.notna(row.volume) else 0.0,
                        open_interest_units=float(row.oi) if pd.notna(row.oi) else 0.0,
                    )
                    for row in quote_frame.itertuples(index=False)
                ]
                usable = [q for q in quotes if q.iv > 0 and q.close > 0]
                if not usable:
                    continue
                if option_type == "CE":
                    edge = max(usable, key=lambda q: q.strike)
                    candidates = [
                        strike
                        for strike in listed.get((expiry, option_type), {})
                        if edge.strike < strike <= edge.strike + self._extend_points
                    ]
                else:
                    edge = min(usable, key=lambda q: q.strike)
                    candidates = [
                        strike
                        for strike in listed.get((expiry, option_type), {})
                        if edge.strike - self._extend_points <= strike < edge.strike
                    ]
                if not candidates:
                    continue
                t_years = year_fraction(
                    minute_hour=moment.hour + moment.minute / 60.0,
                    days_to_expiry=(expiry - ref.session_date).days,
                )
                lot_size = listed[(expiry, option_type)][candidates[0]][1] or 1
                volume = _whole_lots(edge.volume_units * self._liquidity_haircut, lot_size)
                open_interest = _whole_lots(
                    edge.open_interest_units * self._liquidity_haircut, lot_size
                )
                for strike in sorted(candidates):
                    priced = extrapolated_wing_price(
                        option_type=option_type,
                        spot=float(spot),
                        strike=float(strike),
                        t_years=t_years,
                        observed=usable,
                    )
                    if priced is None:
                        continue
                    price, _iv = priced
                    rows.append(
                        {
                            "minute_ts": int(minute_ts),
                            "symbol": listed[(expiry, option_type)][strike][0],
                            "open": price,
                            "high": price,
                            "low": price,
                            "close": price,
                            # NaN, and load-bearing: ST-6 needs an implied volatility, so a
                            # modelled strike can never be selected as a short leg.
                            "iv": float("nan"),
                            "oi": open_interest,
                            "volume": volume,
                            "spot": float(spot),
                            "delta": float("nan"),
                            "gamma": float("nan"),
                            "theta": float("nan"),
                            "vega": float("nan"),
                        }
                    )
        if not rows:
            self._write_cache(cache, frame)
            return frame
        self.synthetic_rows += len(rows)
        self.sessions_extended += 1
        extra = pd.DataFrame(rows)
        for column in frame.columns:
            if column not in extra.columns:
                extra[column] = float("nan")
        extended = pd.concat([frame, extra[list(frame.columns)]], ignore_index=True)
        self._write_cache(cache, extended)
        return extended

    @staticmethod
    def _write_cache(cache: Path | None, frame: pd.DataFrame) -> None:
        if cache is None:
            return
        cache.parent.mkdir(parents=True, exist_ok=True)
        # Written through a temporary name so a concurrent reader never sees half a file, and
        # the name carries the writer's pid: the tuning search runs a dozen workers over the
        # same sessions, and a shared temporary name means one worker renames the file the
        # next is still writing. That failed every configuration in the first parallel batch.
        temporary = cache.with_suffix(f".parquet.{os.getpid()}.tmp")
        try:
            frame.to_parquet(temporary, index=False)
            temporary.replace(cache)
        finally:
            temporary.unlink(missing_ok=True)


def _by_side(minute_frame: pd.DataFrame):
    """``((expiry, option_type), rows)`` for each side present in one minute."""
    parts = minute_frame.symbol.str.split("-", expand=True)
    tagged = minute_frame.assign(
        expiry=parts[1], strike=parts[2].astype(float), option_type=parts[3]
    )
    for (expiry_text, option_type), group in tagged.groupby(["expiry", "option_type"]):
        expiry = dt.datetime.strptime(str(expiry_text), "%d%b%Y").date()
        yield (expiry, str(option_type)), group


def _compose_symbol(underlying: str, expiry: dt.date, strike: float, option_type: str) -> str:
    """The vendor's own symbol format, e.g. ``NIFTY-15Sep2026-22900-CE``."""
    strike_text = str(int(strike)) if float(strike).is_integer() else f"{strike:g}"
    return f"{underlying}-{expiry.strftime('%d%b%Y')}-{strike_text}-{option_type}"


def _whole_lots(value: float, lot_size: int) -> float:
    """Round down to a whole number of lots, so the lot-size audit stays quiet."""
    if lot_size <= 0 or not math.isfinite(value) or value <= 0:
        return 0.0
    return float(int(value // lot_size) * lot_size)
