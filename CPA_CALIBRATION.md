# CPA V4.3: prospective calibration foundation

The monitor's V4.2 scoring and confirmation rules are unchanged. Calibration
records observations for later review; it never promotes a coin or changes
weights, trade signals or alert eligibility.

## Entry cohorts

- Observe eligible `NEAR ENTRY` / `CONFIRMED` rows at confirmation scores 3, 4 or 5.
- Score 3 is a shadow observation, not a confirmed trade.
- One observation per coin per continuous eligible episode. Freeze the score,
  Action Score, event risk/score and market regime at entry. A later rise from
  3 to 4 does not relabel the original sample.
- Missing coins or UNVERIFIED data do not restart episodes. A verified exit
  from eligibility permits a new episode on the next qualifying observation.
- Begin with new observations; do not retroactively label old V4 performance
  history using information unavailable at the original entry.

## Outcomes and interpretation

Capture gross price returns after 24 hours and 7 days, using the first observed
price at/after the horizon, with at most a two-hour delay. Record actual elapsed
time. Missed horizons remain missing, never zero or a late substituted price.
These are price observations, not executed-trade P&L or a backtest.

`calibration_history.json` preserves observations and active episodes.
`calibration_report.json` summarizes confirmation (3/4/5), Action Score (<70/70+),
entry event risk and entry regime. Each horizon reports measured, missed and
pending counts, mean return and positive-return rate. Empty metrics are null.
Thirty measured observations per bucket unlock a descriptive review label
only: samples can overlap in time and across correlated coins, so this count
does not establish statistical significance. Automatic reweighting is disabled.
The two-hour tolerance and thirty-sample gate are initial operational defaults,
not optimized trading parameters. Fees, slippage and fills are excluded.

This first increment provides machine-readable reports; the existing Signal Lab
screen is not yet wired to the new cohort report. Data collection starts only
after this branch is merged and the monitor runs successfully.

## Validation

Run `python -m compileall -q scripts tests` and
`python -m unittest discover -s tests -v`.
The read-only validation workflow runs on relevant pull requests and main
pushes. It makes no external market calls, publishes no data and creates no
alerts. The production workflow publishes the two additional JSON files.
