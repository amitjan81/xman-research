"""H1 — the MVP's anchor hypothesis, its pre-registered gate, and the run that decides it.

Three modules, deliberately separated by what each one is allowed to know:

* :mod:`~xman_research.h1.hypothesis` — the content-addressed record. Text and thresholds
  only; it can reach neither the corpus nor a result.
* :mod:`~xman_research.h1.calibrate_thresholds` — the synthetic calibration behind the
  deflated-Sharpe bars. It imports no store and no backtester, so it *cannot* be calibrated
  against the result it will grade, which is the property that makes the bars defensible.
* :mod:`~xman_research.h1.run_decision` — the loop: backtest, adapt, grade, and read the
  holdout only if everything else passed.

The gate file and the validation configuration live outside the package, at
``research/h1/``, because they are the pre-registration artefacts rather than code — they
were committed before the first run, and the commit boundary is what corroborates their
recorded timestamps.
"""
