"""Small strict contracts shared by offline operational workflows."""
import hashlib
import json
import math
from datetime import date
from pathlib import Path

from plan_inventory import ContractError, parse_date


def object_(value, required, optional=(), context="input"):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ContractError(f"{context}: require {sorted(required)}; optional {sorted(optional)}")
    return value


def text(value, context):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{context}: require nonempty text (preserve identifiers)")
    return value.strip()


def num(value, context, *, minimum=0, maximum=1e12, whole=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{context}: require finite JSON number, not text or boolean")
    if not minimum <= value <= maximum or (whole and int(value) != value):
        raise ContractError(f"{context}: value outside bounds or not whole units")
    return value


def rows(value, context, *, empty=False):
    if not isinstance(value, list) or (not value and not empty) or any(not isinstance(x, dict) for x in value):
        raise ContractError(f"{context}: require {'possibly empty ' if empty else 'nonempty '}list of objects")
    if len(value) > 100000:
        raise ContractError(f"{context}: maximum 100000 rows")
    return value


def unique(records, field="id", context="rows"):
    keys = [text(x.get(field), f"{context}.{field}") for x in records]
    if any(x.get(field) != k for x, k in zip(records, keys)):
        raise ContractError(f"{context}: identifiers must not contain leading/trailing whitespace")
    if len(set(keys)) != len(keys):
        raise ContractError(f"{context}: duplicate {field}")


def month(value, context):
    value = text(value, context)
    try:
        parsed = date.fromisoformat(value + "-01")
    except ValueError:
        raise ContractError(f"{context}: require canonical YYYY-MM") from None
    if parsed.strftime("%Y-%m") != value:
        raise ContractError(f"{context}: require canonical YYYY-MM")
    return value


def day(value, context):
    return parse_date(value, context)


def percentile(values, p):
    values = sorted(values)
    index = (len(values) - 1) * p
    lo = int(index)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (index - lo)


def load_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ContractError(f"JSON: duplicate key {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ContractError(f"JSON: nonfinite constant {value}")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=invalid)


def provenance(path):
    path = Path(path)
    return {"input_name": path.name, "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
