"""Prospective observations only: never modify CPA scores, gates or alerts."""

from datetime import datetime, timedelta, timezone
import json
import math

HORIZONS = {"24h": timedelta(hours=24), "7d": timedelta(days=7)}
MAX_DELAY = timedelta(hours=2)
MIN_SAMPLES = 30  # Descriptive review gate, not statistical significance.


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Calibration timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def positive_price(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def summarize(observations):
    groups = {key: {} for key in ("confirmation", "action_score", "event_risk", "regime", "model_version")}
    for item in observations:
        labels = {
            "confirmation": str(item["confirmation_score"]),
            "action_score": "70+" if item["action_score"] >= 70 else "<70",
            "event_risk": item["event_risk"],
            "regime": item["regime"],
            "model_version": item.get("model_version", "legacy"),
        }
        for dimension, label in labels.items():
            bucket = groups[dimension].setdefault(label, [])
            bucket.append(item)
    for dimension, buckets in groups.items():
        for label, items in buckets.items():
            stats = {"observations": len(items), "horizons": {}}
            for horizon in HORIZONS:
                outcomes = [x["outcomes"].get(horizon, {}) for x in items]
                values = [x["return_pct"] for x in outcomes if x.get("status") == "measured"]
                count = len(values)
                stats["horizons"][horizon] = {
                    "measured": count,
                    "missed": sum(x.get("status") == "missed" for x in outcomes),
                    "pending": sum(not x for x in outcomes),
                    "mean_return_pct": round(sum(values) / count, 4) if count else None,
                    "positive_return_pct": round(sum(v > 0 for v in values) / count * 100, 2) if count else None,
                    "sample_status": "REVIEW_ONLY" if count >= MIN_SAMPLES else "INSUFFICIENT",
                }
            groups[dimension][label] = stats
    return groups


def advance(state, rows, regime, observed_at):
    """One sample per continuous eligible episode; entry cohorts never change.

    3/5 is a shadow cohort, not a trade signal. Outcomes are first observed
    prices at/after each horizon, up to two hours late. Missing/late prices
    never count as zero returns. Missing coins retain their episode identity.
    """
    now = timestamp(observed_at)
    previous = state.get("updated_at")
    if previous and now < timestamp(previous):
        raise ValueError("Calibration observations cannot go backwards")
    observations = state.setdefault("observations", [])
    episodes = state.setdefault("active_episodes", {})
    by_id = {row["id"]: row for row in rows}
    for item in observations:
        start = timestamp(item["opened_at"])
        row = by_id.get(item["coin_id"], {})
        price = row.get("price")
        for horizon, duration in HORIZONS.items():
            if horizon in item["outcomes"]:
                continue
            due = start + duration
            if now > due + MAX_DELAY:
                item["outcomes"][horizon] = {"status": "missed", "due_at": due.isoformat()}
            elif now >= due and positive_price(price):
                item["outcomes"][horizon] = {
                    "status": "measured", "observed_at": observed_at,
                    "elapsed_hours": round((now - start).total_seconds() / 3600, 4),
                    "price": price,
                    "return_pct": round((price / item["entry_price"] - 1) * 100, 6),
                }
    for row in rows:
        coin_id = row["id"]
        score = row.get("confirmation_score")
        if row.get("status") == "UNVERIFIED" or not positive_price(row.get("price")):
            continue  # Data gaps must not create repeated entry samples.
        eligible = row.get("status") in ("NEAR ENTRY", "CONFIRMED") and score in (3, 4, 5)
        if not eligible:
            episodes.pop(coin_id, None)
            continue
        if coin_id in episodes:
            continue
        sample_id = coin_id + "@" + observed_at
        observations.append({
            "id": sample_id, "coin_id": coin_id, "symbol": row["symbol"],
            "opened_at": observed_at, "entry_price": row["price"],
            "confirmation_score": score, "entry_status": row["status"],
            "action_score": row["action_score"], "event_risk": row["event_risk"],
            "event_score": row["event_score"], "regime": regime["name"],
            "regime_score": regime["score"], "data_source": row.get("data_source"),
            "model_version": row.get("model_version", "legacy"),
            "funding_meta": row.get("funding_meta"),
            "outcomes": {},
        })
        episodes[coin_id] = sample_id
    state.update(version="4.3-observational", updated_at=observed_at)
    report = {
        "version": state["version"], "updated_at": observed_at,
        "observations": len(observations), "automatic_reweighting": False,
        "minimum_samples_for_review": MIN_SAMPLES,
        "method": "prospective episode-entry cohorts; gross price returns; 2h maximum observation delay",
        "limitations": "Overlapping coin/time samples are not independent. Fees, slippage and executable fills are excluded. Counts are a review gate, not proof of predictive value.",
        "groups": summarize(observations),
    }
    return state, report


def update_calibration(data, rows, regime, observed_at):
    history_path = data / "calibration_history.json"
    state = json.loads(history_path.read_text()) if history_path.exists() else {}
    state, report = advance(state, rows, regime, observed_at)
    for path, payload in ((history_path, state), (data / "calibration_report.json", report)):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        temporary.replace(path)
