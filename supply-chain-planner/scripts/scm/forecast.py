"""Past-only forecast comparison and empirical protection-period calibration."""
import math
import statistics as st

METHODS = ("mean28", "mean7", "seasonal7", "sba", "tsb")


def predict(y, horizon, method):
    if not y or horizon < 1:
        raise ValueError("nonempty history and positive horizon required")
    if method not in METHODS:
        raise ValueError("unknown forecast method")
    if method == "seasonal7":
        week = y[-7:]
        return [float(week[i % len(week)]) for i in range(horizon)]
    if method.startswith("mean"):
        return [st.mean(y[-int(method[4:]):])] * horizon
    alpha = 0.1
    positive = [i for i, x in enumerate(y) if x > 0]
    if not positive:
        return [0.] * horizon
    first = positive[0]
    size, interval, elapsed = float(y[first]), float(first + 1), 1
    probability = 1 / interval
    for x in y[first + 1:]:
        if method == "tsb":
            probability += alpha * ((1 if x > 0 else 0) - probability)
        if x > 0:
            size += alpha * (x - size)
            interval += alpha * (elapsed - interval)
            elapsed = 1
        else:
            elapsed += 1
    value = (1 - alpha / 2) * size / interval if method == "sba" else size * probability
    return [max(0., value)] * horizon


def segment(y):
    positive = [x for x in y if x > 0]
    if not positive:
        return {"label": "all_zero", "adi": None, "cv2_positive": None}
    adi = len(y) / len(positive)
    cv2 = st.pvariance(positive) / st.mean(positive) ** 2
    label = ("lumpy" if cv2 >= .49 else "intermittent") if adi >= 1.32 else (
        "erratic" if cv2 >= .49 else "smooth")
    return {"label": label, "adi": adi, "cv2_positive": cv2}


def compare(y, horizon, forced=None):
    """Common rolling origins; no training window ever includes its future actuals."""
    if forced is not None and forced not in METHODS:
        raise ValueError("unknown forecast method")
    candidates = METHODS if len(y) >= 28 else ("mean7",)
    origins = list(range(max(28, len(y) - horizon - 27), len(y) - horizon + 1))
    metrics = {}
    for method in candidates:
        daily, totals, denominator = [], [], 0.
        for o in origins:
            f, actual = predict(y[:o], horizon, method), y[o:o + horizon]
            daily.extend(abs(a - b) for a, b in zip(actual, f))
            totals.append(abs(sum(actual) - sum(f)))
            denominator += sum(actual)
        metrics[method] = {"origins": len(origins),
                           "mae_daily": st.mean(daily) if daily else None,
                           "mae_protection_total": st.mean(totals) if totals else None,
                           "wape": sum(daily) / denominator if denominator else None}
    chosen = forced or (min(candidates, key=lambda m: (
        metrics[m]["mae_protection_total"], metrics[m]["mae_daily"], candidates.index(m)))
        if len(origins) >= 8 else ("mean28" if len(y) >= 28 else "mean7"))
    return chosen, metrics


def quantile(values, p):
    """Nearest-rank empirical quantile. No continuous-normal tail assumption."""
    if not values or not 0 < p <= 1:
        raise ValueError("nonempty sample and probability in (0,1] required")
    values = sorted(values)
    return values[max(0, math.ceil(p * len(values)) - 1)]


def protection(y, lead, review, service, method, lead_scenarios):
    """Empirical demand-minus-forecast error mixture; lead delays are explicit scenarios.

    Disjoint calibration periods reduce overlap, but are NOT independent service trials.
    Method selection and calibration share history: call this a design buffer, not coverage.
    """
    max_h = lead + review + max(d for d, _ in lead_scenarios)
    origins = list(range(28, len(y) - max_h + 1, max_h))
    errors = []
    for o in origins:
        base = sum(predict(y[:o], lead + review, method))
        for delay, weight in lead_scenarios:
            realized = sum(y[o:o + lead + review + delay])
            errors.append((realized - base, weight / len(origins)))
    if len(origins) >= 4:
        errors.sort()
        cumulative, buffer = 0., errors[-1][0]
        for error, weight in errors:
            cumulative += weight
            if cumulative + 1e-12 >= service:
                buffer = error
                break
        name = "empirical_protection_error_mixture"
    else:
        # Sparse-data scenario, not a claim of calibrated tail probability.
        buffer = (st.NormalDist().inv_cdf(service) *
                  (st.stdev(y) if len(y) > 1 else 0) * math.sqrt(max_h))
        buffer += sum(predict(y, max_h, method)) - sum(predict(y, lead + review, method))
        name = "iid_plus_max_lead_scenario"
    return {"safety_stock": max(0., buffer), "method": name,
            "nonoverlapping_calibration_periods": len(origins),
            "service_target_is_not_achieved_service": True,
            "target": sum(predict(y, lead + review, method)) + max(0., buffer)}
