"""
matcher.py
==========
Configurable encoder cross-reference scoring engine.

Scoring policy (tiers, weights, fields, compatibility matrices) is driven
entirely by matcher_config.json — no hardcoded weights in this file.

Architecture:
  Step 1  SQL (db_load)   — T1 hard stops + manufacturer/shaft/voltage-class
                            partition pruning + IP floor + housing diameter
                            pre-filter -> candidate DataFrame
  Step 2  Python T1       — hollow bore diameter tolerance check (requires
                            numeric logic not expressible in pure SQL)
  Step 3  Python T2/T3    — vectorized scoring via registered method dispatch
  Step 4  Dedup           — best-scoring row per product_family
  Step 5  Return          — ranked families with per-field score breakdown

Performance notes (v2):
  - get_cached_connection() used — no connection setup overhead per request
  - load_config() result cached at module level — no repeated JSON parse
  - All numeric scoring methods use numpy vectorized operations (no .apply lambdas)
  - CPR JSON arrays pre-parsed once per call (not inside the row loop)
  - Compat matrix lookups use pandas .map(dict) instead of .apply(lambda)

Usage:
    python matcher.py --part "8.KIS40.1342.1024" --source kubler --target epc
    python matcher.py --part "EPC-755A-S-XXXX-A-PP-23A-S" --source epc --target sick --top 5

    from matcher import match, load_config
    src, scored = match("8.KIS40.1342.1024", "kubler", "epc")

AQB Solutions | May 2026
"""

import json
import math
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from db_load import get_cached_connection, fetch_part, fetch_candidates

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG_PATH = Path(__file__).parent / "matcher_config.json"

_CPR_FIELDS    = ("cpr_values", "is_programmable", "ppr_range_min", "ppr_range_max")
_VOLTAGE_FIELDS = ("supply_voltage_min_v", "supply_voltage_max_v")

# Module-level config cache — loaded once, reused on every request
_config_cache: dict | None = None
_config_path_cached: str   = ""


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG LOADER + VALIDATOR
# ─────────────────────────────────────────────────────────────────────────────

def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    """Load and validate matcher_config.json."""
    with open(path) as f:
        cfg = json.load(f)

    errors = []
    t2_sum = sum(v["weight"] for v in cfg["tier2"].values())
    t3_sum = sum(v["weight"] for v in cfg["tier3"].values())
    tw_sum = cfg["tier2_weight"] + cfg["tier3_weight"]

    if abs(t2_sum - 1.0) > 0.001:
        errors.append(f"tier2 weights sum to {t2_sum:.4f}, expected 1.0")
    if abs(t3_sum - 1.0) > 0.001:
        errors.append(f"tier3 weights sum to {t3_sum:.4f}, expected 1.0")
    if abs(tw_sum - 1.0) > 0.001:
        errors.append(f"tier2_weight + tier3_weight = {tw_sum:.4f}, expected 1.0")

    cfg["_path"] = str(path)
    if errors:
        raise ValueError("matcher_config.json is invalid:\n  " + "\n  ".join(errors))
    return cfg


def _validate_registries(cfg: dict) -> None:
    """Check all method/rule names are registered. Called once after config load."""
    errors = []
    for field, fc in cfg["tier2"].items():
        if fc["method"] not in SCORING_REGISTRY:
            errors.append(f"tier2.{field}: unknown method '{fc['method']}'")
    for field, fc in cfg["tier3"].items():
        if fc["method"] not in SCORING_REGISTRY:
            errors.append(f"tier3.{field}: unknown method '{fc['method']}'")
    for rule in cfg["tier1_hard_stops"]:
        if rule["rule"] not in T1_RULE_REGISTRY:
            errors.append(f"tier1 field '{rule['field']}': unknown rule '{rule['rule']}'")
    if errors:
        raise ValueError("matcher_config.json references unregistered names:\n  "
                         + "\n  ".join(errors))


def _get_cached_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    """Return cached config, loading and validating once on first call."""
    global _config_cache, _config_path_cached
    p = str(config_path)
    if _config_cache is None or _config_path_cached != p:
        _config_cache = load_config(p)
        _validate_registries(_config_cache)
        _config_path_cached = p
    return _config_cache


# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _num(val) -> float | None:
    """Safe float coercion. Returns None for NaN/None/non-numeric."""
    try:
        v = float(val)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _safe_score(v) -> "float | None":
    """Coerce a scored column value to float, returning None for NaN/None."""
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _pair_fmt(data: dict, field: str) -> str:
    """
    Format one Silver field value from a dict for pair-comparison display.
    Mirrors serializers._fmt_field logic but operates on plain dicts
    (not DataFrameRow objects) and keeps output short for CLI columns.
    """
    if field == "supply_voltage":
        v_min = _num(data.get("supply_voltage_min_v"))
        v_max = _num(data.get("supply_voltage_max_v"))
        if v_min is not None and v_max is not None:
            return f"{v_min:g}–{v_max:g} V"
        return "—"

    if field == "cpr_values":
        is_prog = str(data.get("is_programmable", "")).strip().lower() in ("true", "1")
        r_min   = _num(data.get("ppr_range_min"))
        r_max   = _num(data.get("ppr_range_max"))
        if is_prog and r_min is not None and r_max is not None:
            return f"prog {int(r_min):,}–{int(r_max):,}"
        raw = data.get("cpr_values")
        if raw and str(raw).strip() not in ("", "nan", "None"):
            try:
                vals = json.loads(str(raw))
                return f"{len(vals)} vals ({min(vals)}–{max(vals)})"
            except Exception:
                pass
        return "—"

    if field == "ip_rating":
        v = _num(data.get(field))
        return f"IP{int(v)}" if v is not None else "—"

    if field in ("housing_diameter_mm", "shaft_bore_diameter_mm"):
        v = _num(data.get(field))
        return f"{v:.2f} mm" if v is not None else "—"

    if field in ("shock_resistance_ms2", "vibration_resistance_ms2"):
        v = _num(data.get(field))
        return f"{v:,.0f} m/s²" if v is not None else "—"

    if field in ("shaft_load_radial_n", "shaft_load_axial_n"):
        v = _num(data.get(field))
        return f"{v:.0f} N" if v is not None else "—"

    if field == "connector_pins":
        v = _num(data.get(field))
        return f"{int(v)} pins" if v is not None else "—"

    if field == "operating_temp_max_c":
        v = _num(data.get(field))
        return f"{v:.0f} °C" if v is not None else "—"

    val = data.get(field)
    if val is None:
        return "—"
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return "—"
    return _fmt(val)


def _weighted_score(score_cols: dict[str, pd.Series],
                    weights: dict[str, float]) -> pd.Series:
    """
    Vectorized weighted average with per-row null redistribution.
    When a field is null for a candidate, its weight is redistributed
    proportionally across the remaining non-null fields for that row.
    """
    idx         = next(iter(score_cols.values())).index
    numerator   = pd.Series(0.0, index=idx)
    denominator = pd.Series(0.0, index=idx)

    for field, s in score_cols.items():
        w    = weights[field]
        mask = s.notna()
        numerator   += s.fillna(0.0) * w * mask
        denominator += w * mask

    return (numerator / denominator.replace(0, float("nan"))).clip(0.0, 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# T1 RULE IMPLEMENTATIONS
# ─────────────────────────────────────────────────────────────────────────────

def _t1_exact_match(src: dict, cand_df: pd.DataFrame, rule: dict) -> pd.Series:
    field   = rule["field"]
    src_val = str(src.get(field) or "").strip()
    # If source value is unknown/empty, we can't enforce a hard stop —
    # pass all candidates through and let T2 scoring handle the comparison.
    if not src_val:
        return pd.Series(True, index=cand_df.index)
    cand_vals = cand_df[field].fillna("").astype(str).str.strip()
    # Also pass candidates with unknown value (both-known condition) —
    # we can't hard-stop a candidate we have no data for (e.g. Sick shaft_type).
    return cand_vals.isin(["", src_val])


def _t1_within_tolerance_pct(src: dict, cand_df: pd.DataFrame, rule: dict) -> pd.Series:
    """
    Numeric tolerance check. Returns True (pass) or False (exclude).
    condition='hollow_only': skips rule for solid shaft sources.
    condition='solid_only':  skips rule for hollow shaft sources.
    """
    params    = rule.get("params", {})
    field     = rule["field"]
    condition = params.get("condition", "")
    tol_pct   = params.get("tolerance_pct", 10) / 100.0

    if condition == "hollow_only":
        src_shaft = str(src.get("shaft_type") or "").strip()
        if src_shaft not in ("hollow_blind", "hollow_thru"):
            return pd.Series(True, index=cand_df.index)

    elif condition == "solid_only":
        src_shaft = str(src.get("shaft_type") or "").strip()
        if src_shaft in ("hollow_blind", "hollow_thru"):
            return pd.Series(True, index=cand_df.index)

    src_val = _num(src.get(field))
    if src_val is None or src_val == 0:
        return pd.Series(True, index=cand_df.index)

    cand_vals = _to_numeric(cand_df[field])
    return cand_vals.apply(
        lambda c: True  if pd.isna(c)
        else      True  if abs(c - src_val) / src_val <= tol_pct
        else      False
    )


def _t1_forbidden_pairs(src: dict, cand_df: pd.DataFrame, rule: dict) -> pd.Series:
    field   = rule["field"]
    pairs   = rule.get("params", {}).get("pairs", [])
    src_val = str(src.get(field) or "").strip()

    forbidden_cand_vals = {pair[1] for pair in pairs if str(pair[0]) == src_val}
    if not forbidden_cand_vals:
        return pd.Series(True, index=cand_df.index)

    return ~cand_df[field].astype(str).str.strip().isin(forbidden_cand_vals)


def _t1_exact_match_except_cable(src: dict, cand_df: pd.DataFrame, rule: dict) -> pd.Series:
    """
    Exact-match T1 for connector type, with cable exempt from the hard stop.

    Decision matrix:
      source=cable   → skip T1 entirely (all candidates pass; T2 matrix scores them)
      source=empty   → skip T1 entirely (no constraint to enforce)
      source=M12/M23/etc.:
        candidate=cable   → PASS (cable can be adapted; T2 scores it at 0.3)
        candidate=empty   → PASS (no data, both-known condition)
        candidate=M12     → PASS iff src=M12 (exact match)
        candidate=M23/etc.→ FAIL (hard stop — connectors cannot physically mate)
    """
    field   = rule["field"]
    src_val = str(src.get(field) or "").strip()

    # Skip T1 if source is unknown/empty — no constraint to enforce
    if not src_val:
        return pd.Series(True, index=cand_df.index)

    # Skip T1 if source is cable — all candidates pass, T2 handles scoring
    if src_val.lower() == "cable":
        return pd.Series(True, index=cand_df.index)

    # Source is a specific connector: exact match required, with two exceptions:
    #   1. Candidate is cable → pass through to T2 soft scoring
    #   2. Candidate is empty/unknown → pass (both-known condition)
    cand_vals  = cand_df[field].fillna("").astype(str).str.strip()
    cand_lower = cand_vals.str.lower()

    is_cable = cand_lower == "cable"
    is_empty = cand_lower.isin(["", "nan", "none"])
    is_exact = cand_vals == src_val

    return is_cable | is_empty | is_exact


T1_RULE_REGISTRY = {
    "exact_match":                _t1_exact_match,
    "within_tolerance_pct":       _t1_within_tolerance_pct,
    "forbidden_pairs":            _t1_forbidden_pairs,
    "exact_match_except_cable":   _t1_exact_match_except_cable,
}


def apply_t1_python_rules(
        src: dict, cand_df: pd.DataFrame, cfg: dict
) -> tuple["pd.DataFrame", list[dict]]:
    """
    Apply all T1 hard stops from config in Python.
    Returns (filtered DataFrame, list of exclusion dicts).

    Each exclusion dict:
      {"field": str, "rule": str, "excluded": int, "total_before": int}

    Callers that don't need exclusion tracking can ignore the second return value.
    """
    mask       = pd.Series(True, index=cand_df.index)
    exclusions = []
    for rule in cfg["tier1_hard_stops"]:
        rule_fn    = T1_RULE_REGISTRY[rule["rule"]]
        rule_mask  = rule_fn(src, cand_df, rule)
        excluded   = (~rule_mask).sum()
        if excluded:
            print(f"    T1 [{rule['field']} / {rule['rule']}]: excluded {excluded:,} candidates")
            exclusions.append({
                "field":         rule["field"],
                "rule":          rule["rule"],
                "excluded":      int(excluded),
                "total_before":  int(mask.sum()),
            })
        mask &= rule_mask

    return cand_df[mask].copy(), exclusions


# ─────────────────────────────────────────────────────────────────────────────
# T2 / T3 SCORING METHODS
# All methods: (src, cand_df, field_key, params, cfg) -> pd.Series[float|NaN]
#
# v2 changes:
#   - All numeric methods use numpy vectorized ops (no .apply lambda loops)
#   - Compat matrix lookups use pd.Series.map(dict) instead of .apply(lambda)
#   - CPR JSON pre-parsed once per call via .map() on the column
# ─────────────────────────────────────────────────────────────────────────────

def _score_cpr(src: dict, cand_df: pd.DataFrame,
               field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    CPR list intersection scoring.

    Source list vs candidate:
      - Candidate programmable -> coverage = proportion of src values in cand range
      - Both have discrete lists -> intersection recall = |src ∩ cand| / |src|
      - Source has list, candidate has range only -> 0.5 × recall (uncertain coverage)
      - Both programmable -> range overlap ratio

    v2: cpr_values JSON is pre-parsed in one vectorized pass before the scoring
    loop. This eliminates repeated json.loads() calls inside the row iteration,
    which was the most expensive step at large candidate counts.
    """
    src_json = src.get("cpr_values")
    src_prog = str(src.get("is_programmable", "")).strip().lower() in ("true", "1")
    src_min  = _num(src.get("ppr_range_min"))
    src_max  = _num(src.get("ppr_range_max"))
    src_list: list | None = None
    src_set:  set  | None = None

    if src_json:
        try:
            src_list = json.loads(str(src_json))
            src_set  = set(src_list)
        except (json.JSONDecodeError, TypeError):
            pass

    # ── Pre-parse ALL candidate CPR JSON in one vectorized pass ──────────────
    # json.loads is called once per unique cpr_values string, not inside the loop.
    def _parse_set(v) -> set | None:
        if pd.isna(v) or str(v).strip() in ("", "nan", "None"):
            return None
        try:
            return set(json.loads(str(v)))
        except Exception:
            return None

    cand_cpr_sets = cand_df["cpr_values"].map(_parse_set)
    cand_prog     = cand_df["is_programmable"].astype(str).str.strip().str.lower().isin(["true", "1"])
    cand_min_s    = pd.to_numeric(cand_df["ppr_range_min"], errors="coerce")
    cand_max_s    = pd.to_numeric(cand_df["ppr_range_max"], errors="coerce")

    # ── Scoring loop — sets are pre-parsed, only intersections remain ─────────
    scores = []
    for i in range(len(cand_df)):
        c_prog = bool(cand_prog.iloc[i])
        c_min  = _num(cand_min_s.iloc[i])
        c_max  = _num(cand_max_s.iloc[i])
        c_set  = cand_cpr_sets.iloc[i]

        score: float | None = None
        try:
            if c_prog and c_min is not None and c_max is not None:
                if src_list:
                    # Source is discrete list, candidate is programmable range
                    covered = sum(1 for v in src_list if c_min <= v <= c_max)
                    score   = covered / len(src_list)
                elif src_min is not None and src_max is not None:
                    # Source is a range encoder (Case 2 or programmable), candidate
                    # is programmable range — score by range overlap.
                    # Fixes K58I/K80I 'XXXXX' PPR: src 1-5000 vs cand 1-16384 -> 1.0
                    # Previously gated on src_prog=True, which excluded Case 2 encoders.
                    overlap = max(0, min(src_max, c_max) - max(src_min, c_min))
                    score   = min(1.0, overlap / max(src_max - src_min, 1))
                else:
                    score = None
            elif src_set and c_set:
                # Both sides have discrete CPR lists
                score = len(src_set & c_set) / len(src_set)
            elif src_set and c_min is not None and c_max is not None:
                # Source discrete, candidate range only — uncertain coverage
                covered = sum(1 for v in src_set if c_min <= v <= c_max)
                score   = 0.5 * covered / len(src_set)
            elif src_min is not None and src_max is not None and c_set:
                # Source is range, candidate has discrete list — score by how many
                # candidate values fall within source range
                covered = sum(1 for v in c_set if src_min <= v <= src_max)
                score   = covered / len(c_set) if c_set else None
            else:
                score = None
        except Exception:
            score = None

        scores.append(score)

    return pd.Series(scores, index=cand_df.index, dtype=float)


def _score_directional_gte(src: dict, cand_df: pd.DataFrame,
                           field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Directional scoring: candidate must meet or exceed source value.

    modes:
      "step"  — 1.0 if cand >= src, partial_score if within tolerance, 0.0 below
      "ratio" — 1.0 if cand >= src (- tolerance), cand/src ratio if below

    v2: fully vectorized with numpy — no .apply() lambda loop.
    """
    mode      = params.get("mode", "ratio")
    tolerance = params.get("tolerance", 0.0)

    src_val = _num(src.get(field_key))
    if src_val is None:
        return pd.Series(np.nan, index=cand_df.index)

    cand_arr = pd.to_numeric(cand_df[field_key], errors="coerce").values.astype(float)
    null_mask = np.isnan(cand_arr)

    if mode == "step":
        partial = params.get("partial_score", 0.5)
        scores = np.where(cand_arr >= src_val, 1.0,
                 np.where(cand_arr >= src_val - tolerance, partial, 0.0))
    else:  # ratio
        if src_val > 0:
            ratio  = np.maximum(0.0, cand_arr / src_val)
            scores = np.where(cand_arr >= src_val - tolerance, 1.0, ratio)
        else:
            # src_val == 0: cannot evaluate ratio — return NaN for all
            return pd.Series(np.nan, index=cand_df.index)

    scores = np.where(null_mask, np.nan, scores)
    return pd.Series(scores, index=cand_df.index, dtype=float)


def _score_oc_compat(src: dict, cand_df: pd.DataFrame,
                     field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Output circuit compatibility via config matrix.

    v2: uses pd.Series.map(dict) — ~10x faster than .apply(lambda) at scale.
    """
    matrix  = cfg["compatibility_matrices"]["output_circuit"]["matrix"]
    default = cfg["compatibility_matrices"]["output_circuit"]["default_score"]
    src_val = str(src.get(field_key) or "").strip()
    src_row = matrix.get(src_val, {})

    cand_clean = cand_df[field_key].astype(str).str.strip()
    null_mask  = cand_df[field_key].isna() | cand_clean.isin(["", "nan", "None"])

    scores = cand_clean.map(src_row)           # NaN for keys not in matrix
    scores = scores.fillna(default)            # apply default for unknown types
    scores = scores.where(~null_mask, np.nan)  # NaN for truly null candidates
    return scores.astype(float)


def _score_conn_compat(src: dict, cand_df: pd.DataFrame,
                       field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Connection type compatibility via config matrix.

    v2: uses pd.Series.map(dict) — same approach as _score_oc_compat.
    """
    matrix  = cfg["compatibility_matrices"]["connection_type"]["matrix"]
    default = cfg["compatibility_matrices"]["connection_type"]["default_score"]
    src_val = str(src.get(field_key) or "").strip()
    src_row = matrix.get(src_val, {})

    cand_clean = cand_df[field_key].astype(str).str.strip()
    null_mask  = cand_df[field_key].isna() | cand_clean.isin(["", "nan", "None"])

    scores = cand_clean.map(src_row)
    scores = scores.fillna(default)
    scores = scores.where(~null_mask, np.nan)
    return scores.astype(float)


def _score_housing_diameter(src: dict, cand_df: pd.DataFrame,
                             field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Housing diameter proximity scoring.
    Full score within tight band, linear degradation to loose band,
    further degradation beyond loose band.

    v2: fully vectorized with numpy.
    """
    sp      = cfg["scoring_params"]
    tight   = sp["housing_diameter_tight_mm"]
    loose   = sp["housing_diameter_loose_mm"]
    src_val = _num(src.get(field_key))

    if src_val is None:
        return pd.Series(np.nan, index=cand_df.index)

    cand_arr  = pd.to_numeric(cand_df[field_key], errors="coerce").values.astype(float)
    null_mask = np.isnan(cand_arr)
    diff      = np.abs(cand_arr - src_val)

    linear = 1.0 - (diff - tight) / (loose - tight) * 0.4
    beyond = np.maximum(0.0, 1.0 - diff / 30.0)

    scores = np.where(diff <= tight, 1.0,
             np.where(diff <= loose, linear, beyond))
    scores = np.where(null_mask, np.nan, scores)
    return pd.Series(scores, index=cand_df.index, dtype=float)


def _score_bore_diameter(src: dict, cand_df: pd.DataFrame,
                         field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Bore diameter proximity scoring. Tighter tolerance than housing.

    v2: fully vectorized with numpy.
    """
    sp      = cfg["scoring_params"]
    tight   = sp["bore_diameter_tight_mm"]
    loose   = sp["bore_diameter_loose_mm"]
    src_val = _num(src.get(field_key))

    if src_val is None:
        return pd.Series(np.nan, index=cand_df.index)

    cand_arr  = pd.to_numeric(cand_df[field_key], errors="coerce").values.astype(float)
    null_mask = np.isnan(cand_arr)
    diff      = np.abs(cand_arr - src_val)

    beyond = np.maximum(0.0, 1.0 - diff / 15.0)

    scores = np.where(diff <= tight, 1.0,
             np.where(diff <= 0.5,   0.9,
             np.where(diff <= loose,  0.6, beyond)))
    scores = np.where(null_mask, np.nan, scores)
    return pd.Series(scores, index=cand_df.index, dtype=float)


def _score_voltage_overlap(src: dict, cand_df: pd.DataFrame,
                           field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Supply voltage range overlap scoring.
    Score = overlap length / source range length (clamped 0–1).

    v2: fully vectorized with numpy.
    """
    s1 = _num(src.get("supply_voltage_min_v"))
    s2 = _num(src.get("supply_voltage_max_v"))

    if s1 is None or s2 is None or s2 <= s1:
        return pd.Series(np.nan, index=cand_df.index)

    c1       = pd.to_numeric(cand_df["supply_voltage_min_v"], errors="coerce").values.astype(float)
    c2       = pd.to_numeric(cand_df["supply_voltage_max_v"], errors="coerce").values.astype(float)
    null_mask = np.isnan(c1) | np.isnan(c2)

    overlap = (np.minimum(s2, c2) - np.maximum(s1, c1)) / (s2 - s1 + 1e-9)
    scores  = np.clip(overlap, 0.0, 1.0)
    scores  = np.where(null_mask, np.nan, scores)
    return pd.Series(scores, index=cand_df.index, dtype=float)


def _score_exact_match(src: dict, cand_df: pd.DataFrame,
                       field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Exact string match. Match=1.0, mismatch=0.5 (different technology can still
    be functionally equivalent in most industrial contexts).

    v2: vectorized with numpy.
    """
    src_val   = str(src.get(field_key) or "").strip().lower()
    cand_clean = cand_df[field_key].astype(str).str.strip().str.lower()
    null_mask  = cand_df[field_key].isna() | cand_clean.isin(["", "nan", "none"])

    scores = np.where(cand_clean == src_val, 1.0, 0.5)
    scores = np.where(null_mask, np.nan, scores)
    return pd.Series(scores, index=cand_df.index, dtype=float)


def _score_connector_pins(src: dict, cand_df: pd.DataFrame,
                          field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Pin count proximity. Exact=1.0, linear degradation up to max_diff.

    v2: vectorized with numpy.
    """
    max_diff = cfg["scoring_params"]["connector_pins_max_diff"]
    src_val  = _num(src.get(field_key))

    if src_val is None:
        return pd.Series(np.nan, index=cand_df.index)

    cand_arr  = pd.to_numeric(cand_df[field_key], errors="coerce").values.astype(float)
    null_mask = np.isnan(cand_arr)

    scores = np.where(cand_arr == src_val, 1.0,
             np.maximum(0.0, 1.0 - np.abs(cand_arr - src_val) / max_diff))
    scores = np.where(null_mask, np.nan, scores)
    return pd.Series(scores, index=cand_df.index, dtype=float)


SCORING_REGISTRY = {
    "cpr_list_intersection":  _score_cpr,
    "directional_gte":        _score_directional_gte,
    "oc_compat_matrix":       _score_oc_compat,
    "conn_compat_matrix":     _score_conn_compat,
    "housing_diameter_score": _score_housing_diameter,
    "bore_diameter_score":    _score_bore_diameter,
    "voltage_range_overlap":  _score_voltage_overlap,
    "exact_match_score":      _score_exact_match,
    "connector_pins_score":   _score_connector_pins,
}


# ─────────────────────────────────────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def score_candidates(src: dict, cand_df: pd.DataFrame, cfg: dict,
                     custom_weights: dict | None = None) -> pd.DataFrame:
    """
    Vectorized T2 + T3 scoring across the entire candidate DataFrame.
    Dispatches each field to its registered scoring method.

    custom_weights (optional): {"tier2": {"field": w, ...}, "tier3": {"field": w, ...}}
    Values must already be normalized to sum to 1.0 per tier.
    """
    t2_cfg = {
        f: {**fc, "weight": custom_weights["tier2"].get(f, fc["weight"])
            if custom_weights and "tier2" in custom_weights else fc["weight"]}
        for f, fc in cfg["tier2"].items()
    }
    t3_cfg = {
        f: {**fc, "weight": custom_weights["tier3"].get(f, fc["weight"])
            if custom_weights and "tier3" in custom_weights else fc["weight"]}
        for f, fc in cfg["tier3"].items()
    }

    t2_scores = {}
    for field, fc in t2_cfg.items():
        fn = SCORING_REGISTRY[fc["method"]]
        t2_scores[field] = fn(src, cand_df, field, fc.get("params", {}), cfg)

    # ── Cable-conditional T2 weight redistribution ────────────────────────────
    # When both source and candidate use specific (non-cable) connector types,
    # T1 exact_match_except_cable already enforces an exact match — every
    # surviving candidate has the same connector type as the source, so the
    # T2 connection_type score would be a uniform 1.0 and adds no discriminating
    # power.  Setting those scores to NaN triggers _weighted_score's null-
    # redistribution: the 0.15 weight flows proportionally to the other T2
    # fields (CPR, IP, output circuit, housing, bore), giving them more signal.
    # When cable is involved on either side, the score is kept — the matrix
    # produces meaningful partial scores (cable→M12=0.3, cable→cable=1.0).
    _src_conn = str(src.get("connection_type_canonical") or "").strip().lower()
    if "connection_type_canonical" in t2_scores and _src_conn not in ("cable", ""):
        _cand_conn = (
            cand_df["connection_type_canonical"]
            .fillna("").astype(str).str.strip().str.lower()
        )
        # True where candidate is also a specific (non-cable, non-empty) connector
        _both_non_cable = ~_cand_conn.isin(["cable", "", "nan", "none"])
        # where(cond=~_both_non_cable, other=nan): keep score when cable involved,
        # set NaN when both sides are specific connectors (triggers redistribution)
        t2_scores["connection_type_canonical"] = (
            t2_scores["connection_type_canonical"].where(~_both_non_cable, other=np.nan)
        )

    t2 = _weighted_score(t2_scores, {f: c["weight"] for f, c in t2_cfg.items()})

    t3_scores = {}
    for field, fc in t3_cfg.items():
        fn = SCORING_REGISTRY[fc["method"]]
        t3_scores[field] = fn(src, cand_df, field, fc.get("params", {}), cfg)

    t3 = _weighted_score(t3_scores, {f: c["weight"] for f, c in t3_cfg.items()})

    result = cand_df.copy()
    for f, s in t2_scores.items():
        result[f"sc_t2_{f}"] = s
    for f, s in t3_scores.items():
        result[f"sc_t3_{f}"] = s

    result["t2_score"]    = t2.round(4)
    result["t3_score"]    = t3.round(4)
    result["total_score"] = (
        cfg["tier2_weight"] * t2 + cfg["tier3_weight"] * t3
    ).round(4)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# DEDUP
# ─────────────────────────────────────────────────────────────────────────────

def dedup_by_family(scored: pd.DataFrame) -> pd.DataFrame:
    """Keep the highest-scoring row per product_family."""
    return (
        scored
        .sort_values("total_score", ascending=False)
        .groupby("product_family", sort=False)
        .first()
        .reset_index()
        .sort_values("total_score", ascending=False)
    )


# ─────────────────────────────────────────────────────────────────────────────
# RESULTS DISPLAY (CLI only)
# ─────────────────────────────────────────────────────────────────────────────

def _sym(s) -> str:
    if s is None or (isinstance(s, float) and math.isnan(s)): return "⬜"
    if s >= 0.95:  return "✅"
    if s >= 0.80:  return "🟢"
    if s >= 0.60:  return "🟡"
    if s >= 0.35:  return "🟠"
    return "🔴"


def _fmt(v) -> str:
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f): return "–"
        return f"{f:.2f}"
    except (TypeError, ValueError):
        return str(v)[:20] if v else "–"


def print_results(src: dict, scored: pd.DataFrame, top_n: int, cfg: dict) -> None:
    families      = dedup_by_family(scored)
    total_families = len(families)

    print(f"\n{'='*70}")
    print(f"SOURCE: {src.get('part_number')}  "
          f"[{src.get('manufacturer')} / {src.get('product_family')}]")
    print(f"  shaft={src.get('shaft_type')}  "
          f"IP{src.get('ip_rating')}  "
          f"{src.get('output_circuit_canonical')}  "
          f"conn={src.get('connection_type_canonical')}  "
          f"ø{_fmt(src.get('shaft_bore_diameter_mm'))}mm  "
          f"Tmax={_fmt(src.get('operating_temp_max_c'))}°C")
    print(f"{'='*70}")
    print(f"TOP {min(top_n, total_families)} FAMILIES  "
          f"({total_families} unique, {len(scored):,} total candidates)\n")

    t2_fields = list(cfg["tier2"].keys())
    t3_fields = list(cfg["tier3"].keys())

    for rank, row in enumerate(families.head(top_n).itertuples(), 1):
        bar = "█" * int(getattr(row, "total_score", 0) * 20)
        print(f"  #{rank:>2}  {row.part_number:<42}  "
              f"Score: {row.total_score:.3f}  [{bar:<20}]")
        print(f"       {row.manufacturer} / {row.product_family}")
        print(f"       T2={row.t2_score:.3f}  T3={row.t3_score:.3f}")

        field_rows = []
        for f in t2_fields:
            s      = getattr(row, f"sc_t2_{f}", None)
            src_v  = src.get(f, "–")
            cand_v = getattr(row, f, "–")
            field_rows.append((s if s is not None else 1.0, f, src_v, cand_v, s, "T2"))

        for f in t3_fields:
            s = getattr(row, f"sc_t3_{f}", None)
            if f == "supply_voltage":
                src_v  = (f"{_fmt(src.get('supply_voltage_min_v'))}"
                          f"–{_fmt(src.get('supply_voltage_max_v'))}V")
                cand_v = (f"{_fmt(getattr(row, 'supply_voltage_min_v', None))}"
                          f"–{_fmt(getattr(row, 'supply_voltage_max_v', None))}V")
            else:
                src_v  = src.get(f, "–")
                cand_v = getattr(row, f, "–")
            field_rows.append((s if s is not None else 1.0, f, src_v, cand_v, s, "T3"))

        field_rows.sort(key=lambda x: x[0])
        for _, f, sv, cv, s, tier in field_rows:
            sv        = str(sv)[:22] if sv is not None else "–"
            cv        = str(cv)[:22] if cv is not None else "–"
            score_str = f"{s:.2f}" if s is not None else "n/a"
            print(f"       {_sym(s)} [{tier}] {f:<35} {sv:<24} -> {cv:<24} ({score_str})")
        print()


def print_pair_result(
    src:             dict,
    tgt_raw:         dict,
    scored:          pd.DataFrame,
    t1_exclusions:   list[dict],
    cfg:             dict,
    source_pn_input: str = "",
    target_pn_input: str = "",
) -> None:
    """
    Print a human-readable T1/T2/T3 breakdown for a single source↔target pair.

    T1 section shows pass/fail for every configured hard-stop rule.
    T2/T3 sections show field scores sorted worst→best (most actionable first).
    Final section shows the weighted total score.
    Printed to stdout — no return value.
    """
    failed_fields = {ex["field"] for ex in t1_exclusions}
    sep = "=" * 74

    print(f"\n{sep}")
    print("  PAIR SCORE")
    print(sep)
    print(f"  SOURCE : {source_pn_input or src.get('part_number')}"
          f"  [{src.get('manufacturer')} / {src.get('product_family')}]")
    print(f"  TARGET : {target_pn_input or tgt_raw.get('part_number')}"
          f"  [{tgt_raw.get('manufacturer')} / {tgt_raw.get('product_family')}]")
    print(sep)

    # ── T1 Hard Stops ──────────────────────────────────────────────────────────
    print("\n  T1 HARD STOPS")
    print("  " + "─" * 70)
    for rule in cfg["tier1_hard_stops"]:
        field   = rule["field"]
        passed  = field not in failed_fields
        icon    = "✅" if passed else "❌"
        src_v   = str(src.get(field) or "—")[:24]
        tgt_v   = str(tgt_raw.get(field) or "—")[:24]
        cond    = rule.get("params", {}).get("condition", "")
        cond_s  = f" [{cond}]" if cond else ""
        result  = "PASS" if passed else "FAIL"
        print(f"    {icon}  {result}  {field:<34}{cond_s:<16}"
              f"src={src_v:<26} tgt={tgt_v}")

    if scored.empty:
        # T1 failed — no score to show
        print(f"\n  ⛔  T1 FAILED — scoring aborted.")
        for ex in t1_exclusions:
            print(f"       Rule '{ex['field']}' / '{ex['rule']}' "
                  f"eliminated the target.")
        print(f"\n{sep}\n")
        return

    row         = scored.iloc[0]
    t2_score    = _safe_score(row.get("t2_score"))    or 0.0
    t3_score    = _safe_score(row.get("t3_score"))    or 0.0
    total_score = _safe_score(row.get("total_score")) or 0.0
    tw2         = cfg["tier2_weight"]
    tw3         = cfg["tier3_weight"]

    # ── T2 Scoring ─────────────────────────────────────────────────────────────
    print(f"\n  T2 SCORING  (weight {tw2:.0%} of total)")
    print("  " + "─" * 70)
    t2_rows = []
    for field, fc in cfg["tier2"].items():
        s     = _safe_score(row.get(f"sc_t2_{field}"))
        src_v = _pair_fmt(src,     field)
        tgt_v = _pair_fmt(tgt_raw, field)
        t2_rows.append((s if s is not None else -1.0, s, field, fc["weight"], src_v, tgt_v))
    t2_rows.sort()   # worst (lowest score) first; None (-1) sorts to top
    for _, s, field, w, sv, tv in t2_rows:
        score_s = f"{s:.3f}" if s is not None else " n/a"
        print(f"    {_sym(s)}  w={w:.2f}  {field:<34}"
              f"src: {sv:<22}  tgt: {tv:<22}  ({score_s})")
    print(f"    {'─'*60}")
    print(f"    T2 score : {t2_score:.4f}")

    # ── T3 Scoring ─────────────────────────────────────────────────────────────
    print(f"\n  T3 SCORING  (weight {tw3:.0%} of total)")
    print("  " + "─" * 70)
    t3_rows = []
    for field, fc in cfg["tier3"].items():
        s     = _safe_score(row.get(f"sc_t3_{field}"))
        src_v = _pair_fmt(src,     field)
        tgt_v = _pair_fmt(tgt_raw, field)
        t3_rows.append((s if s is not None else -1.0, s, field, fc["weight"], src_v, tgt_v))
    t3_rows.sort()
    for _, s, field, w, sv, tv in t3_rows:
        score_s = f"{s:.3f}" if s is not None else " n/a"
        print(f"    {_sym(s)}  w={w:.2f}  {field:<34}"
              f"src: {sv:<22}  tgt: {tv:<22}  ({score_s})")
    print(f"    {'─'*60}")
    print(f"    T3 score : {t3_score:.4f}")

    # ── Final Score ────────────────────────────────────────────────────────────
    bar = "█" * int(total_score * 30)
    print(f"\n  {'─'*70}")
    print(f"  TOTAL SCORE : {total_score:.4f}  ({total_score*100:.1f}%)")
    print(f"  [{bar:<30}]")
    print(f"  = {tw2:.0%}×T2({t2_score:.4f}) + {tw3:.0%}×T3({t3_score:.4f})")
    print(f"\n{sep}\n")


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def _build_no_match_reason(src: dict, t1_exclusions: list[dict],
                           sql_count: int, target_mfr: str) -> dict:
    """
    Build a human-readable no-match reason for the UI.

    Inspects SQL pre-filter result and T1 Python exclusions to determine
    the most specific reason for 0 candidates.

    Returns a dict with keys:
      "code"    — machine-readable reason code
      "message" — short human-readable message (1 sentence)
      "detail"  — optional longer explanation
    """
    shaft_type   = str(src.get("shaft_type")   or "").strip()
    output_class = str(src.get("output_voltage_class") or "").strip()
    bore_mm      = src.get("shaft_bore_diameter_mm")

    # ── SQL returned 0: target manufacturer has no encoders matching basic criteria
    if sql_count == 0:
        if output_class == "analog":
            return {
                "code":    "no_analog_output",
                "message": f"{target_mfr.title()} does not offer SinCos/analog output encoders.",
                "detail":  "No replacements are available. Consider a digital output (RS422 or Push-Pull) equivalent instead.",
            }
        return {
            "code":    "no_sql_candidates",
            "message": f"No {target_mfr.title()} encoders found matching shaft type '{shaft_type}' and output class '{output_class}'.",
            "detail":  "The target catalog may not have equivalent encoders for this configuration.",
        }

    # ── Python T1 eliminated all: find the rule that caused the final wipeout
    # The last exclusion in the list is the one that eliminated the remaining pool.
    if t1_exclusions:
        last = t1_exclusions[-1]
        field = last["field"]

        if field == "shaft_bore_diameter_mm" and bore_mm is not None:
            bore_str = f"{bore_mm:.4g} mm"
            if shaft_type in ("hollow_blind", "hollow_thru"):
                return {
                    "code":    "bore_no_match",
                    "message": f"No {target_mfr.title()} equivalent for {bore_str} hollow bore.",
                    "detail":  (
                        f"{target_mfr.title()} hollow encoders may not offer this bore size. "
                        "Try a nearby standard size or check the catalog manually."
                    ),
                }
            return {
                "code":    "bore_no_match",
                "message": f"No {target_mfr.title()} equivalent for {bore_str} solid shaft bore.",
                "detail":  "The target catalog may not offer this exact shaft diameter.",
            }

        if field == "housing_diameter_mm":
            housing = src.get("housing_diameter_mm")
            return {
                "code":    "housing_no_match",
                "message": f"Source housing diameter ({housing:.4g} mm) has no {target_mfr.title()} equivalent within tolerance.",
                "detail":  "No standard replacement found at this housing size. Consider a different form factor.",
            }

        if field == "output_voltage_class":
            return {
                "code":    "voltage_class_incompatible",
                "message": f"Output voltage class '{output_class}' is electrically incompatible with available {target_mfr.title()} candidates.",
                "detail":  "TTL and HTL outputs are not interchangeable. Check if a different output type is acceptable.",
            }

        if "shaft" in field:
            return {
                "code":    "shaft_type_no_match",
                "message": f"{target_mfr.title()} has no {shaft_type.replace('_', ' ')} encoders in this configuration.",
                "detail":  "The target catalog does not offer this shaft type combination.",
            }

        # Generic T1 fallback
        return {
            "code":    "t1_no_match",
            "message": f"No {target_mfr.title()} candidates passed compatibility checks ({field}).",
            "detail":  f"T1 rule '{field}' eliminated all {last['total_before']} remaining candidates.",
        }

    # Fallback — shouldn't reach here but handle gracefully
    return {
        "code":    "no_candidates",
        "message": f"No compatible {target_mfr.title()} encoders found.",
        "detail":  "No candidates survived the pre-filtering stage.",
    }


def match(part_number: str,
          source_mfr:     str,
          target_mfr:     str,
          top_n:          int  = 10,
          config_path:    str | Path = DEFAULT_CONFIG_PATH,
          custom_weights: dict | None = None,
          ) -> tuple[dict, pd.DataFrame, dict | None]:
    """
    Main entry point for encoder cross-reference matching.

    v2 changes:
      - Uses get_cached_connection() — no connection setup overhead per call.
        The connection is NEVER closed inside this function.
      - Config loaded once and cached at module level — no repeated JSON parse.
      - src_housing_mm passed to fetch_candidates() for SQL-side size pre-filter.

    Returns:
        (src_dict, scored_DataFrame)
        scored_DataFrame has all Silver columns plus sc_t2_*, sc_t3_*,
        t2_score, t3_score, total_score columns.
        Empty DataFrame if no candidates pass T1.
    """
    cfg = _get_cached_config(config_path)

    # Use the long-lived singleton — no open/close overhead per request.
    # IMPORTANT: do NOT call con.close() here.
    con = get_cached_connection()

    # Step 1 — Fetch source part
    src = fetch_part(con, part_number, source_mfr)
    if src is None:
        raise ValueError(
            f"Part '{part_number}' not found in manufacturer='{source_mfr}'."
        )

    print(f"\nSource: {part_number}  [{source_mfr}]")
    print(f"  shaft={src.get('shaft_type')}  "
          f"IP{src.get('ip_rating')}  "
          f"{src.get('output_circuit_canonical')}  "
          f"conn={src.get('connection_type_canonical')}")

    # Step 2 — SQL T1 pre-filter
    src_ip = src.get("ip_rating")
    try:
        src_ip_int = int(src_ip) if src_ip is not None and str(src_ip) != "nan" else None
    except (ValueError, TypeError):
        src_ip_int = None

    # Pass housing diameter for SQL-side size pre-filter (±25 mm, NULL kept)
    src_housing_mm = src.get("housing_diameter_mm")

    candidates = fetch_candidates(
        con,
        shaft_type           = str(src.get("shaft_type") or ""),
        output_voltage_class = str(src.get("output_voltage_class") or ""),
        target_manufacturer  = target_mfr,
        src_ip_rating        = src_ip_int,
        src_housing_mm       = src_housing_mm,
    )
    print(f"  SQL candidates (T1 filter): {len(candidates):,}")

    sql_count = len(candidates)
    if candidates.empty:
        print("  No candidates passed SQL T1 filter.")
        reason = _build_no_match_reason(src, [], sql_count=0, target_mfr=target_mfr)
        return src, pd.DataFrame(), reason

    # Step 3 — Python T1 (hollow bore tolerance + config rules)
    candidates, t1_exclusions = apply_t1_python_rules(src, candidates, cfg)
    print(f"  Candidates after Python T1: {len(candidates):,}")

    if candidates.empty:
        print("  No candidates passed Python T1 rules.")
        reason = _build_no_match_reason(src, t1_exclusions, sql_count=sql_count,
                                        target_mfr=target_mfr)
        return src, pd.DataFrame(), reason

    # Step 4 — T2 / T3 scoring
    print(f"  Scoring {len(candidates):,} candidates ...", end="", flush=True)
    scored = score_candidates(src, candidates, cfg, custom_weights=custom_weights)
    print(" done.")

    return src, scored, None


def match_pair(
    source_pn:      str,
    source_mfr:     str,
    target_pn:      str,
    target_mfr:     str,
    config_path:    str | Path = DEFAULT_CONFIG_PATH,
    custom_weights: dict | None = None,
) -> tuple[dict, dict, pd.DataFrame, list[dict]]:
    """
    Score one specific target part against one specific source part.

    Unlike match(), which fetches the full manufacturer catalog and scores
    all candidates, this function fetches exactly two parts from Silver and
    returns a single comparison result. Intended for testing and validation.

    Flow:
      1. fetch_part(source) — applies manufacturer decoder + CPR override
         (e.g. Kübler '8.7000.1242.2048' decodes PPR=2048, overrides cpr_values)
      2. fetch_part(target) — Stage 1 exact part_number match
         (works for Posital since Silver stores real scraped part numbers)
      3. apply_t1_python_rules() — all 5 T1 hard stops from config
         (bypasses SQL pre-filter; Python T1 is the authoritative check)
      4. score_candidates() — full T2/T3 scoring on the single-row DataFrame

    Returns:
        (src_dict, tgt_raw_dict, scored_df, t1_exclusions)
        scored_df is a one-row DataFrame if T1 passes, empty if T1 fails.
        t1_exclusions is a list of dicts for rules that fired (empty on pass).

    Raises:
        ValueError if either part is not found in Silver.
    """
    cfg = _get_cached_config(config_path)
    con = get_cached_connection()

    src = fetch_part(con, source_pn, source_mfr)
    if src is None:
        raise ValueError(
            f"Source part '{source_pn}' not found in '{source_mfr}'."
        )

    tgt = fetch_part(con, target_pn, target_mfr)
    if tgt is None:
        raise ValueError(
            f"Target part '{target_pn}' not found in '{target_mfr}'."
        )

    print(f"\nPair score: [{source_mfr}] {source_pn}")
    print(f"        vs: [{target_mfr}] {target_pn}")

    tgt_df = pd.DataFrame([tgt])

    # Run all 5 Python T1 rules — no SQL pre-filter since we fetched directly.
    tgt_df, t1_exclusions = apply_t1_python_rules(src, tgt_df, cfg)

    if tgt_df.empty:
        print("  T1 FAILED — no score computed.")
        return src, tgt, pd.DataFrame(), t1_exclusions

    scored = score_candidates(src, tgt_df, cfg, custom_weights=custom_weights)
    total  = round(float(scored.iloc[0]["total_score"]), 4)
    print(f"  T1 passed — total score: {total:.4f} ({total*100:.1f}%)")

    return src, tgt, scored, t1_exclusions


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Encoder cross-reference matcher")

    ap.add_argument("--find-parts",    action="store_true")
    ap.add_argument("--mfr",           default=None)
    ap.add_argument("--family",        default=None)
    ap.add_argument("--fragment",      default=None)

    ap.add_argument("--part",        default=None, help="Source part number")
    ap.add_argument("--source",      default=None, help="Source manufacturer")
    ap.add_argument("--target",      default=None, help="Target manufacturer (or target mfr when --target-part is used)")
    ap.add_argument("--target-part", default=None,
                    help="Specific target part number — activates pair scoring mode "
                         "(scores one source vs one target, skips full catalog search)")
    ap.add_argument("--top",    type=int, default=10)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    args = ap.parse_args()

    if args.find_parts:
        if not args.mfr:
            ap.error("--find-parts requires --mfr")
        from db_load import get_connection, find_parts
        con = get_connection()
        try:
            df = find_parts(con, args.mfr, args.family, args.fragment)
        finally:
            con.close()

        if df.empty:
            print("No parts found.")
        else:
            print(f"\n{len(df)} part(s) found\n")
            pd.set_option("display.max_colwidth", 45)
            pd.set_option("display.width", 160)
            print(df.to_string(index=False))
        return

    # ── Pair mode: score one specific source vs one specific target ────────────
    if args.target_part:
        if not args.part or not args.source or not args.target:
            ap.error("Pair mode requires --part, --source, and --target (as target manufacturer).")
        cfg = _get_cached_config(args.config)
        src, tgt_raw, scored, t1_excl = match_pair(
            source_pn   = args.part,
            source_mfr  = args.source,
            target_pn   = args.target_part,
            target_mfr  = args.target,
            config_path = args.config,
        )
        print_pair_result(
            src             = src,
            tgt_raw         = tgt_raw,
            scored          = scored,
            t1_exclusions   = t1_excl,
            cfg             = cfg,
            source_pn_input = args.part,
            target_pn_input = args.target_part,
        )
        return

    # ── Standard catalog-search mode ───────────────────────────────────────────
    if not args.part or not args.source or not args.target:
        ap.error("Match mode requires --part, --source, and --target.")

    cfg            = _get_cached_config(args.config)
    src, scored, _ = match(args.part, args.source, args.target, args.top, args.config)

    if not scored.empty:
        print_results(src, scored, args.top, cfg)
    else:
        print("No results.")


if __name__ == "__main__":
    main()