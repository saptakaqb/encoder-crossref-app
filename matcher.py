"""
matcher.py
==========
Configurable encoder cross-reference scoring engine.

Scoring policy (tiers, weights, fields, compatibility matrices) is driven
entirely by matcher_config.json — no hardcoded weights in this file.

Architecture:
  Step 1  SQL (db_load)   — T1 hard stops + manufacturer/shaft/voltage-class
                            partition pruning → candidate DataFrame
  Step 2  Python T1       — hollow bore diameter tolerance check (requires
                            numeric logic not expressible in pure SQL)
  Step 3  Python T2/T3    — vectorized scoring via registered method dispatch
  Step 4  Dedup           — best-scoring row per product_family
  Step 5  Return          — ranked families with per-field score breakdown

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

import pandas as pd
import numpy as np

from db_load import get_connection, fetch_part, fetch_candidates

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG_PATH = Path(__file__).parent / "matcher_config.json"

# Silver schema column names used in multi-field scoring methods
_CPR_FIELDS    = ("cpr_values", "is_programmable", "ppr_range_min", "ppr_range_max")
_VOLTAGE_FIELDS = ("supply_voltage_min_v", "supply_voltage_max_v")


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG LOADER + VALIDATOR
# ─────────────────────────────────────────────────────────────────────────────

def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    """
    Load and validate matcher_config.json.
    Raises ValueError with a clear message on any misconfiguration.
    """
    with open(path) as f:
        cfg = json.load(f)

    errors = []

    # Weight sum checks
    t2_sum = sum(v["weight"] for v in cfg["tier2"].values())
    t3_sum = sum(v["weight"] for v in cfg["tier3"].values())
    tw_sum = cfg["tier2_weight"] + cfg["tier3_weight"]

    if abs(t2_sum - 1.0) > 0.001:
        errors.append(f"tier2 weights sum to {t2_sum:.4f}, expected 1.0")
    if abs(t3_sum - 1.0) > 0.001:
        errors.append(f"tier3 weights sum to {t3_sum:.4f}, expected 1.0")
    if abs(tw_sum - 1.0) > 0.001:
        errors.append(f"tier2_weight + tier3_weight = {tw_sum:.4f}, expected 1.0")

    # Method name checks (validated against registries after they are defined)
    cfg["_path"] = str(path)

    if errors:
        raise ValueError("matcher_config.json is invalid:\n  " + "\n  ".join(errors))

    return cfg


def _validate_registries(cfg: dict) -> None:
    """Called after registries are defined. Checks all method/rule names exist."""
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
    """Returns boolean Series: True = candidate passes, False = excluded."""
    field   = rule["field"]
    src_val = str(src.get(field) or "").strip()
    return cand_df[field].astype(str).str.strip() == src_val


def _t1_within_tolerance_pct(src: dict, cand_df: pd.DataFrame, rule: dict) -> pd.Series:
    """
    Numeric tolerance check. Returns True (pass) or False (exclude).
    condition='hollow_only': skips rule entirely for solid shaft rows —
    returns all True so solid-shaft candidates are never filtered here.
    """
    params    = rule.get("params", {})
    field     = rule["field"]
    condition = params.get("condition", "")
    tol_pct   = params.get("tolerance_pct", 10) / 100.0

    # condition=hollow_only: only apply when source is a hollow shaft
    if condition == "hollow_only":
        src_shaft = str(src.get("shaft_type") or "").strip()
        if src_shaft not in ("hollow_blind", "hollow_thru"):
            return pd.Series(True, index=cand_df.index)

    src_val = _num(src.get(field))
    if src_val is None or src_val == 0:
        return pd.Series(True, index=cand_df.index)   # can't evaluate — pass

    cand_vals = _to_numeric(cand_df[field])
    return cand_vals.apply(
        lambda c: True  if pd.isna(c)
        else      True  if abs(c - src_val) / src_val <= tol_pct
        else      False
    )


def _t1_forbidden_pairs(src: dict, cand_df: pd.DataFrame, rule: dict) -> pd.Series:
    """Excludes candidates where (source_val, candidate_val) is a forbidden pair."""
    field   = rule["field"]
    pairs   = rule.get("params", {}).get("pairs", [])
    src_val = str(src.get(field) or "").strip()

    forbidden_cand_vals = {pair[1] for pair in pairs if str(pair[0]) == src_val}
    if not forbidden_cand_vals:
        return pd.Series(True, index=cand_df.index)   # no forbidden pairs for this source

    return ~cand_df[field].astype(str).str.strip().isin(forbidden_cand_vals)


T1_RULE_REGISTRY = {
    "exact_match":           _t1_exact_match,
    "within_tolerance_pct":  _t1_within_tolerance_pct,
    "forbidden_pairs":       _t1_forbidden_pairs,
}


def apply_t1_python_rules(src: dict, cand_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    Apply all T1 hard stops from config in Python.
    Returns filtered DataFrame (excluded rows dropped entirely).
    SQL already handled shaft_type + output_voltage_class — this function
    catches any rules that SQL couldn't express (e.g. tolerance-based).
    """
    mask = pd.Series(True, index=cand_df.index)
    for rule in cfg["tier1_hard_stops"]:
        rule_fn  = T1_RULE_REGISTRY[rule["rule"]]
        rule_mask = rule_fn(src, cand_df, rule)
        excluded  = (~rule_mask).sum()
        if excluded:
            print(f"    T1 [{rule['field']} / {rule['rule']}]: excluded {excluded:,} candidates")
        mask &= rule_mask

    return cand_df[mask].copy()


# ─────────────────────────────────────────────────────────────────────────────
# T2 / T3 SCORING METHODS
# Each method: (src, cand_df, field_key, params, cfg) → pd.Series of float|None
# ─────────────────────────────────────────────────────────────────────────────

def _score_cpr(src: dict, cand_df: pd.DataFrame,
               field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    CPR list intersection scoring.

    Source list vs candidate:
      - Candidate programmable → coverage = proportion of src values in cand range
      - Both have discrete lists → intersection recall = |src ∩ cand| / |src|
      - Source has list, candidate has range only → 0.5 × recall (uncertain coverage)
      - Both programmable → range overlap ratio
    """
    src_json = src.get("cpr_values")
    src_prog = str(src.get("is_programmable", "")).strip().lower() in ("true", "1")
    src_min  = _num(src.get("ppr_range_min"))
    src_max  = _num(src.get("ppr_range_max"))
    src_list = None
    if src_json:
        try:
            src_list = json.loads(src_json)
        except (json.JSONDecodeError, TypeError):
            pass

    scores = []
    for _, row in cand_df.iterrows():
        cand_json = row.get("cpr_values")
        cand_prog = str(row.get("is_programmable", "")).strip().lower() in ("true", "1")
        cand_min  = _num(row.get("ppr_range_min"))
        cand_max  = _num(row.get("ppr_range_max"))
        cand_list = None
        if cand_json:
            try:
                cand_list = json.loads(cand_json)
            except (json.JSONDecodeError, TypeError):
                pass

        score = None
        try:
            if cand_prog and cand_min is not None and cand_max is not None:
                # Programmable candidate covers any value in its range
                if src_list:
                    covered = [v for v in src_list if cand_min <= v <= cand_max]
                    score   = len(covered) / len(src_list)
                elif src_prog and src_min is not None and src_max is not None:
                    # Both programmable — range overlap
                    overlap = max(0, min(src_max, cand_max) - max(src_min, cand_min))
                    score   = min(1.0, overlap / max(src_max - src_min, 1))
                else:
                    score = None
            elif src_list and cand_list:
                # Both discrete — intersection recall
                intersection = len(set(src_list) & set(cand_list))
                score        = intersection / len(src_list)
            elif src_list and cand_min is not None and cand_max is not None:
                # Source discrete, candidate range only — penalised (not guaranteed discrete)
                covered = [v for v in src_list if cand_min <= v <= cand_max]
                score   = 0.5 * len(covered) / len(src_list)
            else:
                score = None
        except Exception:
            score = None

        scores.append(score)

    return pd.Series(scores, index=cand_df.index)


def _score_directional_gte(src: dict, cand_df: pd.DataFrame,
                           field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Directional scoring: candidate must meet or exceed source value.

    modes:
      "step"  — 1.0 if cand >= src, partial_score if within tolerance, 0.0 below
      "ratio" — 1.0 if cand >= src (- tolerance), cand/src ratio if below
    """
    mode      = params.get("mode", "ratio")
    tolerance = params.get("tolerance", 0.0)

    src_val = _num(src.get(field_key))
    if src_val is None:
        return pd.Series([None] * len(cand_df), index=cand_df.index, dtype=float)

    cand_vals = _to_numeric(cand_df[field_key])

    if mode == "step":
        partial = params.get("partial_score", 0.5)
        return cand_vals.apply(lambda c:
            None if pd.isna(c)
            else 1.0 if c >= src_val
            else partial if c >= src_val - tolerance
            else 0.0
        )
    else:  # ratio
        return cand_vals.apply(lambda c:
            None if pd.isna(c)
            else 1.0 if c >= src_val - tolerance
            else max(0.0, c / src_val) if src_val > 0
            else None
        )


def _score_oc_compat(src: dict, cand_df: pd.DataFrame,
                     field_key: str, params: dict, cfg: dict) -> pd.Series:
    """Output circuit compatibility via config matrix."""
    matrix  = cfg["compatibility_matrices"]["output_circuit"]["matrix"]
    default = cfg["compatibility_matrices"]["output_circuit"]["default_score"]
    src_val = str(src.get(field_key) or "").strip()
    src_row = matrix.get(src_val, {})

    return cand_df[field_key].apply(
        lambda c: src_row.get(str(c).strip(), default)
        if pd.notna(c) and str(c).strip() else None
    )


def _score_conn_compat(src: dict, cand_df: pd.DataFrame,
                       field_key: str, params: dict, cfg: dict) -> pd.Series:
    """Connection type compatibility via config matrix."""
    matrix  = cfg["compatibility_matrices"]["connection_type"]["matrix"]
    default = cfg["compatibility_matrices"]["connection_type"]["default_score"]
    src_val = str(src.get(field_key) or "").strip()
    src_row = matrix.get(src_val, {})

    return cand_df[field_key].apply(
        lambda c: src_row.get(str(c).strip(), default)
        if pd.notna(c) and str(c).strip() else None
    )


def _score_housing_diameter(src: dict, cand_df: pd.DataFrame,
                             field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Housing diameter proximity scoring.
    Full score within tight band, linear degradation to loose band,
    further degradation beyond loose band.
    """
    sp      = cfg["scoring_params"]
    tight   = sp["housing_diameter_tight_mm"]
    loose   = sp["housing_diameter_loose_mm"]
    src_val = _num(src.get(field_key))

    if src_val is None:
        return pd.Series([None] * len(cand_df), index=cand_df.index, dtype=float)

    cand_vals = _to_numeric(cand_df[field_key])
    return cand_vals.apply(lambda c:
        None if pd.isna(c)
        else 1.0 if abs(c - src_val) <= tight
        else (1.0 - (abs(c - src_val) - tight) / (loose - tight) * 0.4)
             if abs(c - src_val) <= loose
        else max(0.0, 1.0 - abs(c - src_val) / 30.0)
    )


def _score_bore_diameter(src: dict, cand_df: pd.DataFrame,
                         field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Bore diameter proximity scoring. Tighter tolerance than housing
    — mechanical fit requires closer match.
    """
    sp      = cfg["scoring_params"]
    tight   = sp["bore_diameter_tight_mm"]
    loose   = sp["bore_diameter_loose_mm"]
    src_val = _num(src.get(field_key))

    if src_val is None:
        return pd.Series([None] * len(cand_df), index=cand_df.index, dtype=float)

    cand_vals = _to_numeric(cand_df[field_key])
    return cand_vals.apply(lambda c:
        None if pd.isna(c)
        else 1.0 if abs(c - src_val) <= tight
        else 0.9 if abs(c - src_val) <= 0.5
        else 0.6 if abs(c - src_val) <= loose
        else max(0.0, 1.0 - abs(c - src_val) / 15.0)
    )


def _score_voltage_overlap(src: dict, cand_df: pd.DataFrame,
                           field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Supply voltage range overlap scoring.
    field_key is 'supply_voltage' — reads _min_v and _max_v from both sides.
    Score = overlap length / source range length (clamped 0–1).
    """
    s1 = _num(src.get("supply_voltage_min_v"))
    s2 = _num(src.get("supply_voltage_max_v"))

    if s1 is None or s2 is None or s2 <= s1:
        return pd.Series([None] * len(cand_df), index=cand_df.index, dtype=float)

    c1_series = _to_numeric(cand_df["supply_voltage_min_v"])
    c2_series = _to_numeric(cand_df["supply_voltage_max_v"])

    return pd.Series([
        None if (pd.isna(c1) or pd.isna(c2))
        else min(1.0, max(0.0,
            (min(s2, float(c2)) - max(s1, float(c1))) / (s2 - s1 + 1e-9)
        ))
        for c1, c2 in zip(c1_series, c2_series)
    ], index=cand_df.index)


def _score_exact_match(src: dict, cand_df: pd.DataFrame,
                       field_key: str, params: dict, cfg: dict) -> pd.Series:
    """
    Exact string match. Match=1.0, mismatch=0.5 (not 0.0 — different technology
    can still be functionally equivalent in most industrial contexts).
    """
    src_val = str(src.get(field_key) or "").strip().lower()
    return cand_df[field_key].apply(
        lambda c: 1.0 if pd.notna(c) and str(c).strip().lower() == src_val
        else 0.5 if pd.notna(c) and str(c).strip()
        else None
    )


def _score_connector_pins(src: dict, cand_df: pd.DataFrame,
                          field_key: str, params: dict, cfg: dict) -> pd.Series:
    """Pin count proximity. Exact=1.0, linear degradation up to max_diff."""
    max_diff = cfg["scoring_params"]["connector_pins_max_diff"]
    src_val  = _num(src.get(field_key))

    if src_val is None:
        return pd.Series([None] * len(cand_df), index=cand_df.index, dtype=float)

    cand_vals = _to_numeric(cand_df[field_key])
    return cand_vals.apply(lambda c:
        None if pd.isna(c)
        else 1.0 if c == src_val
        else max(0.0, 1.0 - abs(c - src_val) / max_diff)
    )


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
    Overrides the weights in cfg without modifying cfg.
    Returns cand_df augmented with score columns.
    """
    # Merge custom weights into a working copy — never mutate cfg
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

    # ── T2 ────────────────────────────────────────────────────────────────────
    t2_scores = {}
    for field, fc in t2_cfg.items():
        fn = SCORING_REGISTRY[fc["method"]]
        t2_scores[field] = fn(src, cand_df, field, fc.get("params", {}), cfg)

    t2 = _weighted_score(t2_scores, {f: c["weight"] for f, c in t2_cfg.items()})

    # ── T3 ────────────────────────────────────────────────────────────────────
    t3_scores = {}
    for field, fc in t3_cfg.items():
        fn = SCORING_REGISTRY[fc["method"]]
        t3_scores[field] = fn(src, cand_df, field, fc.get("params", {}), cfg)

    t3 = _weighted_score(t3_scores, {f: c["weight"] for f, c in t3_cfg.items()})

    # ── Attach to DataFrame ───────────────────────────────────────────────────
    result = cand_df.copy()
    for f, s in t2_scores.items():
        result[f"sc_t2_{f}"] = s   # sc_ prefix avoids itertuples namedtuple underscore renaming
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
# RESULTS DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

def _sym(s) -> str:
    import math
    if s is None or (isinstance(s, float) and math.isnan(s)): return "⬜"
    if s >= 0.95:  return "✅"
    if s >= 0.80:  return "🟢"
    if s >= 0.60:  return "🟡"
    if s >= 0.35:  return "🟠"
    return "🔴"


def _fmt(v) -> str:
    import math
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

        # Collect field rows, sort worst-first
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
            print(f"       {_sym(s)} [{tier}] {f:<35} {sv:<24} → {cv:<24} ({score_str})")
        print()


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def match(part_number: str,
          source_mfr:     str,
          target_mfr:     str,
          top_n:          int  = 10,
          config_path:    str | Path = DEFAULT_CONFIG_PATH,
          custom_weights: dict | None = None,
          ) -> tuple[dict, pd.DataFrame]:
    """
    Main entry point for encoder cross-reference matching.

    Returns:
        (src_dict, scored_DataFrame)
        scored_DataFrame has all Silver columns plus sc_t2_*, sc_t3_*,
        t2_score, t3_score, total_score columns.
        Empty DataFrame if no candidates pass T1.
    """
    cfg = load_config(config_path)
    _validate_registries(cfg)

    con = get_connection()
    try:
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

        # Step 2 — SQL T1 pre-filter (shaft_type + output_voltage_class + manufacturer + IP floor)
        src_ip = src.get("ip_rating")
        try:
            src_ip_int = int(src_ip) if src_ip is not None and str(src_ip) != "nan" else None
        except (ValueError, TypeError):
            src_ip_int = None

        candidates = fetch_candidates(
            con,
            shaft_type           = str(src.get("shaft_type") or ""),
            output_voltage_class = str(src.get("output_voltage_class") or ""),
            target_manufacturer  = target_mfr,
            src_ip_rating        = src_ip_int,
        )
        print(f"  SQL candidates (shaft+voltage_class+mfr filter): {len(candidates):,}")

    finally:
        con.close()

    if candidates.empty:
        print("  No candidates passed SQL T1 filter.")
        return src, pd.DataFrame()

    # Step 3 — Python T1 (hollow bore tolerance + any other config rules)
    candidates = apply_t1_python_rules(src, candidates, cfg)
    print(f"  Candidates after Python T1: {len(candidates):,}")

    if candidates.empty:
        print("  No candidates passed Python T1 rules.")
        return src, pd.DataFrame()

    # Step 4 — T2 / T3 scoring
    print(f"  Scoring {len(candidates):,} candidates ...", end="", flush=True)
    scored = score_candidates(src, candidates, cfg, custom_weights=custom_weights)
    print(" done.")

    return src, scored


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Encoder cross-reference matcher")

    # -- find-parts mode (part discovery, no matching)
    ap.add_argument("--find-parts",    action="store_true",
                    help="Browse available part numbers instead of running a match.")
    ap.add_argument("--mfr",           default=None,
                    help="Manufacturer filter for --find-parts (kubler|epc|sick)")
    ap.add_argument("--family",        default=None,
                    help="Product family filter for --find-parts  e.g. KIS40")
    ap.add_argument("--fragment",      default=None,
                    help="Part number fragment filter for --find-parts  e.g. 755A")

    # -- match mode
    ap.add_argument("--part",   default=None, help="Source part number")
    ap.add_argument("--source", default=None, help="Source manufacturer (kubler|epc|sick)")
    ap.add_argument("--target", default=None, help="Target manufacturer (kubler|epc|sick)")
    ap.add_argument("--top",    type=int, default=10, help="Top N families to display")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG_PATH),
                    help="Path to matcher_config.json")
    args = ap.parse_args()

    # ── find-parts mode ───────────────────────────────────────────────────────
    if args.find_parts:
        if not args.mfr:
            ap.error("--find-parts requires --mfr")
        from db_load import get_connection, find_parts
        con = get_connection()
        try:
            df = find_parts(con,
                            manufacturer  = args.mfr,
                            family        = args.family,
                            part_fragment = args.fragment)
        finally:
            con.close()

        if df.empty:
            print("No parts found matching the given filters.")
        else:
            print(f"\n{len(df)} part(s) found in Silver [manufacturer={args.mfr}"
                  + (f", family={args.family}" if args.family else "")
                  + (f", fragment='{args.fragment}'" if args.fragment else "")
                  + "]\n")
            pd.set_option("display.max_colwidth", 45)
            pd.set_option("display.width", 160)
            print(df.to_string(index=False))
        return

    # ── match mode ────────────────────────────────────────────────────────────
    if not args.part or not args.source or not args.target:
        ap.error("Match mode requires --part, --source, and --target. "
                 "Use --find-parts --mfr <mfr> [--family <family>] to browse parts.")

    cfg         = load_config(args.config)
    src, scored = match(args.part, args.source, args.target, args.top, args.config)

    if not scored.empty:
        print_results(src, scored, args.top, cfg)
    else:
        print("No results.")


if __name__ == "__main__":
    main()