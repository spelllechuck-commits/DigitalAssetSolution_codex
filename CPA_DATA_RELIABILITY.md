# CPA collection reliability (4.3)

## Rollout order

1. Bound retries and introduce independently timestamped technical caches.
2. Verify candidate providers from GitHub Actions; implement Kraken adapter.
3. Connect validated funding and remove the missing-funding confirmation point.
4. Run offline regressions, production collection, publishing and alert-step checks.

## Collection policy

- CoinGecko requests are spaced at least six seconds apart. HTTP 429 honors
  `Retry-After` (seconds or HTTP date), with exponential backoff and jitter otherwise.
- 401/403/451 stops that host for the current execution. There is no proxy,
  geographic rerouting, key rotation or attempt to bypass access restrictions.
- The shared request budget is 720 seconds; a request or wait that cannot fit
  is skipped and recorded as `BUDGET_EXHAUSTED`. The workflow has a 15-minute limit.
- Successful daily history is cached for approximately 24 hours and hourly
  history for approximately two hours, with deterministic per-asset staggering.
  Success in one component is persisted even if the other fails.
- Both components must pass freshness and history-length checks. Expired or
  legacy aggregate-only caches cannot produce verified technical signals.
  EMA/RSI arithmetic and the existing four-sample extraction are unchanged.
- `latest.json.collection_health` contains call counts, failed URLs/reasons and
  blocked providers; each row has `technical_components` and `funding_meta`.
- Optional GitHub Actions secrets `COINGECKO_DEMO_API_KEY` and
  `COINGECKO_PRO_API_KEY` are read into headers, never URLs/logs. Pro takes priority.
  These changes do not create or purchase an API key. Without a key, shared-IP
  throttling can still reduce coverage; caching/backoff cannot guarantee availability.

## Derivatives source and units

The GitHub runner probe on 2026-09-17 reached Kraken (295 ticker records), while
Bybit returned HTTP 403; earlier Binance requests returned HTTP 451. Routine
collection uses Kraken only. Candidate probing is manual (`workflow_dispatch`).

CoinGecko IDs map explicitly to Kraken linear perpetual contracts, including
bitcoin → PF_XBTUSD and the-open-network → PF_TONUSD. Display symbols are never
used as identity. Unmapped, absent or suspended contracts remain missing.

Kraken's ticker `fundingRate` is an absolute amount, not a percentage. The adapter
uses historical `relativeFundingRate` and checks two adjacent hourly timestamps,
a maximum age of two hours, finite values, and the live contract catalog.
`funding = relativeFundingRate * 8 * 100` expresses the latest hourly relative
rate as an eight-hour-equivalent percent. This is neither a realised eight-hour
payment nor the Binance funding rate. `funding_meta` preserves source, instrument,
raw rate, timestamp, original interval and normalization basis. No stale funding
fallback is allowed. Derivatives are fetched before slow technical histories.

## Signal and calibration implications

The existing 0.05 percent funding threshold, 4-of-5 confirmation rule, score
weights and event gate are retained. Only finite, verified funding below the
threshold earns the funding confirmation point; missing values and NaN do not.
The four other checks can still confirm without funding if all four pass.

Rows and new calibration observations carry `model_version` and funding metadata.
Old entry cohorts are not rewritten. The report includes a model-version grouping;
other aggregate groups can span versions and should not be interpreted as an
isolated comparison of the changed funding logic.

## Verification and recovery

Run `python -m unittest discover -s tests -v` and `python -m compileall -q scripts tests`.
After deployment, check the exact workflow head, all publish/alert step conclusions,
the timestamp/version of latest.json, verified counts, failure reasons, and cache
component reuse. A successful workflow does not imply full source coverage.

If 429 persists, configure a provider-issued CoinGecko key appropriate to the
usage quota or reduce refresh frequency. Do not increase retries to defeat limits.
If Kraken becomes unavailable, funding remains null and receives no confirmation
credit; add another provider only after runner access, identity, interval and unit
checks pass. Rollback can revert the adapter/monitor commit while retaining cache
data; do not restore missing-data confirmation credit.

Sources:
- https://docs.coingecko.com/docs/errors-and-rate-limits
- https://docs.coingecko.com/demo/reference/coins-id-market-chart
- https://docs.kraken.com/api-reference/historical-funding-rates/historical-funding-rates
- https://support.kraken.com/articles/4844359082772-linear-multi-collateral-derivatives-contract-specifications
