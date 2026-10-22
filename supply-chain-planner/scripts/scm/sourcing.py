"""Finite-horizon TCO and evidence-qualified decision comparison; no external actions."""
import math
from urllib.parse import urlparse

from plan_inventory import ContractError
from . import VERSION
from .contracts import day, num, object_, rows, text, unique

COST_FIELDS = ("unit_price", "freight", "setup", "annual_support", "annual_energy", "disposal", "residual_value")


def compare(data):
    object_(data, ("as_of", "currency", "quantity", "horizon_years", "criteria", "requirements", "sources", "options"),
            ("max_source_age_days", "sensitivity_delta"))
    as_of = day(data["as_of"], "as_of")
    currency = text(data["currency"], "currency")
    quantity = num(data["quantity"], "quantity", minimum=1, whole=True)
    years = num(data["horizon_years"], "horizon_years", minimum=1, maximum=20, whole=True)
    age = num(data.get("max_source_age_days", 90), "max_source_age_days", maximum=3650, whole=True)
    delta = num(data.get("sensitivity_delta", .1), "sensitivity_delta", minimum=.001, maximum=.5)
    criteria = rows(data["criteria"], "criteria")
    unique(criteria, context="criteria")
    if len(criteria) > 20:
        raise ContractError("criteria: maximum 20")
    weights = {}
    for r in criteria:
        object_(r, ("id", "weight"), context="criterion")
        key = text(r["id"], "criterion.id")
        weights[key] = num(r["weight"], "weight", maximum=1)
    if not math.isclose(math.fsum(weights.values()), 1, abs_tol=1e-9, rel_tol=0):
        raise ContractError("criteria weights must sum to 1")
    requirements = data["requirements"]
    if not isinstance(requirements, list) or any(not isinstance(r, str) or not r.strip() or r != r.strip() for r in requirements):
        raise ContractError("requirements: require list of nonempty unique names")
    if len(set(requirements)) != len(requirements) or set(requirements) & (set(weights) | {"costs"}):
        raise ContractError("requirement names must be unique and distinct from criteria/costs")
    sources = rows(data["sources"], "sources", empty=True)
    unique(sources, context="sources")
    source_map = {}
    for r in sources:
        object_(r, ("id", "url", "title", "checked_on", "status", "supports"), ("review_note", "publisher_group"), "source")
        url = urlparse(text(r["url"], "source.url"))
        if url.scheme not in ("https", "http") or not url.netloc or url.username or url.password:
            raise ContractError("source URL must be http(s), without credentials")
        text(r["title"], "source.title")
        checked = day(r["checked_on"], "source.checked_on")
        if checked > as_of:
            raise ContractError("source checked_on is after as_of")
        if r["status"] not in ("verified", "unverified", "refuted"):
            raise ContractError("source.status must be verified, unverified or refuted")
        if not isinstance(r["supports"], list) or not r["supports"] or any(not isinstance(s, str) or not s for s in r["supports"]):
            raise ContractError("source.supports: require nonempty topic list")
        if r["status"] == "verified":
            text(r.get("review_note"), "verified source.review_note")
        source_map[r["id"]] = {**r, "fresh": (as_of - checked).days <= age}
    options = rows(data["options"], "options")
    unique(options, context="options")
    if len(options) > 1000:
        raise ContractError("options: maximum 1000")
    result = []
    for o in options:
        object_(o, ("id", "name", "currency", "costs", "requirements", "scores", "evidence"), context="option")
        text(o["name"], "option.name")
        if o["currency"] != currency:
            raise ContractError("TCO comparison requires one matching currency; convert with documented rates first")
        costs = object_(o["costs"], COST_FIELDS, context="costs")
        costs = {k: num(v, k) for k, v in costs.items()}
        # Freight/setup/disposal/residual are total one-off amounts; support/energy are total per year.
        capital = quantity * costs["unit_price"] + costs["freight"] + costs["setup"]
        recurring = years * (costs["annual_support"] + costs["annual_energy"])
        tco = capital + recurring + costs["disposal"] - costs["residual_value"]
        req = object_(o["requirements"], requirements, context="option.requirements")
        if any(v not in ("pass", "fail", "unknown") for v in req.values()):
            raise ContractError("requirement verdict must be pass, fail or unknown")
        scores = object_(o["scores"], set(weights) - {"tco"}, context="option.scores")
        scores = {k: num(v, k, maximum=100) if v is not None else None for k, v in scores.items()}
        evidence = object_(o["evidence"], ("costs", *requirements, *[k for k in weights if k != "tco"]), context="option.evidence")
        issues, evidence_audit = [], []
        for topic, ids in evidence.items():
            if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
                raise ContractError("evidence: require unique source-id lists")
            if any(i not in source_map for i in ids):
                raise ContractError("evidence: unknown source id")
            relevant = [source_map[i] for i in ids if topic in source_map[i]["supports"]]
            refuted = any(s["status"] == "refuted" for s in relevant)
            qualified = any(s["status"] == "verified" and s["fresh"] for s in relevant) and not refuted
            if not qualified:
                issues.append(f"evidence_not_qualified:{topic}")
            evidence_audit.append({"topic": topic, "source_ids": ids,
                                   "qualified_by_caller_records": qualified,
                                   "conflict_or_refutation": refuted})
        if any(v == "fail" for v in req.values()):
            issues.append("hard_requirement_failed")
        if any(v == "unknown" for v in req.values()):
            issues.append("hard_requirement_unknown")
        if any(v is None for v in scores.values()):
            issues.append("score_missing")
        result.append({"id": o["id"], "name": o["name"], "currency": currency,
                       "acquisition_total": capital, "recurring_total": recurring,
                       "disposal": costs["disposal"], "residual_value": costs["residual_value"],
                       "tco": tco, "requirements": req, "criterion_scores": scores,
                       "evidence_audit": evidence_audit, "issues": issues,
                       "eligible_for_comparison": not issues, "weighted_score": None})
    eligible = [r for r in result if r["eligible_for_comparison"]]
    if eligible and "tco" in weights:
        low, high = min(r["tco"] for r in eligible), max(r["tco"] for r in eligible)
        for r in eligible:
            r["criterion_scores"]["tco"] = (high - r["tco"]) / (high - low) * 100 if high > low else 100.
    def rank(w):
        scored = [{"id": r["id"], "score": math.fsum(w[k] * r["criterion_scores"][k] for k in w),
                   "tco": r["tco"]} for r in eligible]
        return sorted(scored, key=lambda r: (-r["score"], r["tco"], r["id"]))
    baseline = rank(weights)
    scores = {r["id"]: r["score"] for r in baseline}
    for r in eligible:
        r["weighted_score"] = scores[r["id"]]
    sensitivity = []
    for k, weight in weights.items():
        for change in (-delta, delta):
            target = min(1., max(0., weight + change))
            if math.isclose(target, weight) or len(weights) == 1:
                continue
            others = {j: w for j, w in weights.items() if j != k}
            remainder = math.fsum(others.values())
            adjusted = {j: ((1 - target) * w / remainder if remainder else (1 - target) / len(others))
                        for j, w in others.items()}
            adjusted[k] = target
            ranked = rank(adjusted)
            sensitivity.append({"criterion": k, "weight": target, "weights": adjusted,
                                "leading_option": ranked[0]["id"] if ranked else None})
    leader = baseline[0]["id"] if baseline else None
    stable = sum(r["leading_option"] == leader for r in sensitivity) / len(sensitivity) if sensitivity and leader else None
    return {"kind": "sourcing_comparison", "engine_version": VERSION, "as_of": as_of.isoformat(),
            "currency": currency, "quantity": quantity, "horizon_years": years, "weights": weights,
            "options": result, "ranking": baseline, "leading_option_for_review": leader,
            "sensitivity": sensitivity, "leader_share_in_weight_scenarios": stable,
            "decision_status": "review_qualified_options" if eligible else "evidence_or_requirements_incomplete",
            "sources": list(source_map.values()),
            "limitations": ["Undiscounted TCO; same quantity, currency and horizon. Tax, financing and unsupplied costs are excluded.",
                "Evidence qualification checks caller-supplied review records, dates, topics and conflicts; it does not fetch or certify source content.",
                "TCO score uses the eligible-options cost range only when tco is an explicit weighted criterion; other scores are supplied 0..100.",
                "Weight perturbations are finite scenarios, not statistical confidence. Ranking supports review and executes no supplier award."]}
