"""
serializers.py
==============
Converts matcher.py output (pandas DataFrame rows + source dict)
into the JSON format expected by EncoderMatch.jsx result cards.

AQB Solutions | May 2026
"""

import json
import math
from typing import Any, Optional

from url_lookup import get_product_url, MFR_FULL_NAMES

# ── Field labels (match frontend MOCK_DATA exactly) ───────────────────────
FIELD_LABELS = {
    # T2
    "cpr_values":                "PPR Coverage",
    "ip_rating":                 "IP Rating",
    "connection_type_canonical": "Connection Type",
    "output_circuit_canonical":  "Output Circuit",
    "housing_diameter_mm":       "Housing Diameter",
    "shaft_bore_diameter_mm":    "Bore Diameter",
    # T3
    "supply_voltage":            "Supply Voltage",
    "sensing_method":            "Sensing Method",
    "operating_temp_max_c":      "Max Operating Temp",
    "shock_resistance_ms2":      "Shock Resistance",
    "shaft_load_radial_n":       "Radial Shaft Load",
    "vibration_resistance_ms2":  "Vibration Resistance",
    "connector_pins":            "Connector Pins",
    "shaft_type":               "Shaft Type",
    "output_voltage_class":      "Signal Class",
    "is_programmable":          "Programmable",
    "shaft_load_axial_n":       "Axial Shaft Load",
    "operating_temp_min_c":     "Min Operating Temp",
    "num_output_channels":      "Output Channels",
    "has_index":                "Index Pulse",
    "pulse_frequency_max_kHz":  "Max Pulse Frequency",
    "power_consumption_max_mA": "Power Consumption",
    "reverse_polarity_protection": "Reverse Polarity Prot.",
    "short_circuit_protection": "Short-Circuit Prot.",
    "flange_type_canonical":    "Flange Type",
    "housing_material":         "Housing Material",
    "flange_material":          "Flange Material",
    "shaft_material":           "Shaft Material",
    "max_speed_rpm":            "Max Speed",
    "startup_torque_nm":        "Starting Torque",
    "moment_of_inertia_gcm2":   "Moment of Inertia",
    "weight_kg":                "Weight",
    "bearing_life_rev":         "Bearing Life",
    "mttfd_years":              "MTTFd",
}


# ── Native manufacturer field names (all Silver fields) ─────────────────────
# Maps canonical Silver field -> exact field name from each manufacturer's data.
NATIVE_FIELD_NAMES = {
    "kubler": {
        "cpr_values":               "Pulses / Revolution",
        "ppr_range_min":            "Min. Pulses / Revolution",
        "ppr_range_max":            "Max. Pulses / Revolution",
        "is_programmable":          "Programmable",
        "output_circuit_canonical": "Output Type",
        "output_voltage_class":     "Signal Level",
        "supply_voltage":           "Supply Voltage",
        "supply_voltage_min_v":     "Supply Voltage Min",
        "supply_voltage_max_v":     "Supply Voltage Max",
        "num_output_channels":      "No. of Channels",
        "has_index":                "Reference Pulse",
        "pulse_frequency_max_kHz":  "Output Frequency",
        "power_consumption_max_mA": "Power Consumption",
        "reverse_polarity_protection": "Reverse Polarity Protection",
        "short_circuit_protection": "Short-Circuit Protection",
        "housing_diameter_mm":      "Housing Ø (mm)",
        "flange_type_canonical":    "Flange Type",
        "housing_material":         "Housing Material",
        "flange_material":          "Flange Material",
        "shaft_bore_diameter_mm":   "Shaft Ø (mm)",
        "shaft_material":           "Shaft Material",
        "shaft_load_radial_n":      "Radial Force",
        "shaft_load_axial_n":       "Axial Force",
        "ip_rating":                "Protection Class",
        "operating_temp_min_c":     "Min. Operating Temp.",
        "operating_temp_max_c":     "Max. Operating Temp.",
        "shock_resistance_ms2":     "Shock Resistance",
        "vibration_resistance_ms2": "Vibration Resistance",
        "max_speed_rpm":            "Max. Operating Speed",
        "connection_type_canonical":"Connection",
        "connector_pins":           "No. of Pins",
        "startup_torque_nm":        "Starting Torque",
        "moment_of_inertia_gcm2":   "Moment of Inertia",
        "weight_kg":                "Weight",
        "bearing_life_rev":         "Bearing Lifetime",
        "mttfd_years":              "MTTFd",
        "sensing_method":           "Sensing",
        "shaft_type":               "Mechanical Type",
    },
    "encoder products company": {
        "cpr_values":               "Pulses Per Revolution",
        "ppr_range_min":            "Min. PPR",
        "ppr_range_max":            "Max. PPR",
        "is_programmable":          "Programmable",
        "output_circuit_canonical": "Output",
        "output_voltage_class":     "Signal Type",
        "supply_voltage":           "Supply Voltage",
        "supply_voltage_min_v":     "Supply Voltage Min",
        "supply_voltage_max_v":     "Supply Voltage Max",
        "num_output_channels":      "Channels",
        "has_index":                "Index",
        "pulse_frequency_max_kHz":  "Frequency Response",
        "power_consumption_max_mA": "Current Consumption",
        "reverse_polarity_protection": "Reverse Polarity",
        "short_circuit_protection": "Short Circuit Protection",
        "housing_diameter_mm":      "Housing Diameter",
        "flange_type_canonical":    "Flange",
        "housing_material":         "Housing Material",
        "flange_material":          "Flange Material",
        "shaft_bore_diameter_mm":   "Shaft Size",
        "shaft_material":           "Shaft Material",
        "shaft_load_radial_n":      "Shaft Load Radial",
        "shaft_load_axial_n":       "Shaft Load Axial",
        "ip_rating":                "Ingress Protection",
        "operating_temp_min_c":     "Min. Temperature",
        "operating_temp_max_c":     "Max. Temperature",
        "shock_resistance_ms2":     "Shock",
        "vibration_resistance_ms2": "Vibration",
        "max_speed_rpm":            "Max Speed",
        "connection_type_canonical":"Termination",
        "connector_pins":           "Number of Pins",
        "startup_torque_nm":        "Starting Torque",
        "moment_of_inertia_gcm2":   "Rotor Inertia",
        "weight_kg":                "Weight",
        "bearing_life_rev":         "Bearing Life",
        "mttfd_years":              "MTTF",
        "sensing_method":           "Technology",
        "shaft_type":               "Shaft Type",
    },
    "sick": {
        "cpr_values":               "Pulses per revolution",
        "ppr_range_min":            "Min. Pulses per revolution",
        "ppr_range_max":            "Max. Pulses per revolution",
        "is_programmable":          "Programmable/configurable",
        "output_circuit_canonical": "Communication interface",
        "output_voltage_class":     "Output voltage",
        "supply_voltage":           "Supply voltage",
        "supply_voltage_min_v":     "Supply voltage min",
        "supply_voltage_max_v":     "Supply voltage max",
        "num_output_channels":      "Number of signal channels",
        "has_index":                "Reference signal, number",
        "pulse_frequency_max_kHz":  "Output frequency",
        "power_consumption_max_mA": "Power consumption",
        "reverse_polarity_protection": "Reverse polarity protection",
        "short_circuit_protection": "Short-circuit protection",
        "housing_diameter_mm":      "Housing diameter",
        "flange_type_canonical":    "Flange type / stator coupling",
        "housing_material":         "Housing material",
        "flange_material":          "Flange material",
        "shaft_bore_diameter_mm":   "Shaft diameter",
        "shaft_material":           "Shaft material",
        "shaft_load_radial_n":      "Permissible shaft loading",
        "shaft_load_axial_n":       "Permissible shaft loading (axial)",
        "ip_rating":                "Enclosure rating",
        "operating_temp_min_c":     "Operating temperature min",
        "operating_temp_max_c":     "Operating temperature max",
        "shock_resistance_ms2":     "Resistance to shocks",
        "vibration_resistance_ms2": "Resistance to vibration",
        "max_speed_rpm":            "Operating speed",
        "connection_type_canonical":"Connection type",
        "connector_pins":           "Pins",
        "startup_torque_nm":        "Start up torque",
        "moment_of_inertia_gcm2":   "Moment of inertia of the rotor",
        "weight_kg":                "Weight",
        "bearing_life_rev":         "Bearing lifetime",
        "mttfd_years":              "MTTFD",
        "sensing_method":           "Technology",
        "shaft_type":               "Mechanical design",
    },
    "posital": {
        "cpr_values":               "Pulses per Revolution",
        "ppr_range_min":            "PPR Range Min",
        "ppr_range_max":            "PPR Range Max",
        "is_programmable":          "Interface",
        "output_circuit_canonical": "Output Driver",
        "output_voltage_class":     "Output Level",
        "supply_voltage":           "Supply Voltage",
        "supply_voltage_min_v":     "Supply Voltage Min",
        "supply_voltage_max_v":     "Supply Voltage Max",
        "num_output_channels":      "Channels",
        "has_index":                "Index",
        "pulse_frequency_max_kHz":  "Maximum Frequency Response",
        "power_consumption_max_mA": "Power Consumption",
        "reverse_polarity_protection": "Reverse Polarity Protection",
        "short_circuit_protection": "Short Circuit Protection",
        "housing_diameter_mm":      "Flange Diameter",
        "flange_type_canonical":    "Flange Type",
        "housing_material":         "Housing Material",
        "flange_material":          "Flange Material",
        "shaft_bore_diameter_mm":   "Shaft Diameter",
        "shaft_material":           "Shaft Material",
        "shaft_load_radial_n":      "Max. Shaft Load (Radial)",
        "shaft_load_axial_n":       "Max. Shaft Load (Axial)",
        "ip_rating":                "Protection Class",
        "operating_temp_min_c":     "Min Temperature",
        "operating_temp_max_c":     "Max Temperature",
        "shock_resistance_ms2":     "Shock Resistance",
        "vibration_resistance_ms2": "Vibration Resistance",
        "max_speed_rpm":            "Max. Permissible Mechanical Speed",
        "connection_type_canonical":"Connection Type",
        "connector_pins":           "Connector Pins",
        "startup_torque_nm":        "Friction Torque",
        "moment_of_inertia_gcm2":   "Rotor Inertia",
        "weight_kg":                "Weight",
        "bearing_life_rev":         "Minimum Mechanical Lifetime",
        "mttfd_years":              "MTTF",
        "sensing_method":           "Technology",
        "shaft_type":               "Shaft Type",
    },
    "baumer": {
        "cpr_values":               "Pulses per revolution",
        "ppr_range_min":            "Min. Pulses per revolution",
        "ppr_range_max":            "Max. Pulses per revolution",
        "is_programmable":          "Programmable",
        "output_circuit_canonical": "Output stages",
        "output_voltage_class":     "Signal Level",
        "supply_voltage":           "Voltage supply",
        "supply_voltage_min_v":     "Voltage supply min",
        "supply_voltage_max_v":     "Voltage supply max",
        "num_output_channels":      "Output signals",
        "has_index":                "Reference signal",
        "pulse_frequency_max_kHz":  "Output frequency",
        "power_consumption_max_mA": "Consumption w/o load",
        "reverse_polarity_protection": "Reverse polarity protection",
        "short_circuit_protection": "Short-circuit proof",
        "housing_diameter_mm":      "Size (flange)",
        "flange_type_canonical":    "Flange",
        "housing_material":         "Material (housing)",
        "flange_material":          "Material (flange)",
        "shaft_bore_diameter_mm":   "Shaft type",
        "shaft_material":           "Material (shaft)",
        "shaft_load_radial_n":      "Admitted shaft load (radial)",
        "shaft_load_axial_n":       "Admitted shaft load (axial)",
        "ip_rating":                "Protection EN 60529",
        "operating_temp_min_c":     "Operating temperature min",
        "operating_temp_max_c":     "Operating temperature max",
        "shock_resistance_ms2":     "Shock resistance",
        "vibration_resistance_ms2": "Vibration resistance",
        "max_speed_rpm":            "Operating speed",
        "connection_type_canonical":"Connection",
        "connector_pins":           "No. of pins",
        "startup_torque_nm":        "Operating torque",
        "moment_of_inertia_gcm2":   "Rotor moment of inertia",
        "weight_kg":                "Weight approx.",
        "sensing_method":           "Sensing method",
        "shaft_type":               "Shaft type",
    },
}

def _native_label(manufacturer: str, field: str) -> str:
    """Return the manufacturer's native field name, or the canonical label as fallback."""
    mfr_key = manufacturer.lower().strip()
    return (
        NATIVE_FIELD_NAMES.get(mfr_key, {}).get(field)
        or FIELD_LABELS.get(field, field)
    )


def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    v = _safe_float(val)
    return None if v is None else int(v)


def _safe_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    try:
        return bool(val)
    except Exception:
        return False


def _fmt_field(data: dict, field: str) -> str:
    """Format a Silver field value as a human-readable string for the UI."""

    # supply_voltage is a compound field with no single "supply_voltage" key in Silver.
    # It must be handled BEFORE the generic null guard (data.get("supply_voltage") is
    # always None, so the null guard would return "—" before reaching this block).
    if field == "supply_voltage":
        v_min = _safe_float(data.get("supply_voltage_min_v"))
        v_max = _safe_float(data.get("supply_voltage_max_v"))
        if v_min is not None and v_max is not None:
            return f"{v_min:g}–{v_max:g} V"
        return "—"

    val = data.get(field)

    # Nulls
    if val is None:
        return "—"
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return "—"

    # Field-specific formatting
    if field == "ip_rating":
        v = _safe_int(val)
        return f"IP{v}" if v is not None else "—"

    if field in ("housing_diameter_mm", "shaft_bore_diameter_mm"):
        v = _safe_float(val)
        return f"{v:.1f} mm" if v is not None else "—"

    if field == "operating_temp_max_c":
        v = _safe_float(val)
        return f"{v:.0f} °C" if v is not None else "—"

    if field in ("shock_resistance_ms2", "vibration_resistance_ms2"):
        v = _safe_float(val)
        return f"{v:,.0f} m/s²" if v is not None else "—"

    if field == "shaft_load_radial_n":
        v = _safe_float(val)
        return f"{v:.0f} N" if v is not None else "—"

    if field == "connector_pins":
        v = _safe_int(val)
        return f"{v} pins" if v is not None else "—"

    if field == "cpr_values":
        try:
            raw = str(val)
            vals = json.loads(raw)
            if isinstance(vals, list) and vals:
                return f"{len(vals)} values ({min(vals)}–{max(vals)})"
        except Exception:
            pass
        return str(val)

    if field == "shaft_type":
        m = {"solid":"Solid shaft","hollow_blind":"Hollow bore (blind)","hollow_thru":"Hollow bore (through)"}
        return m.get(str(val).lower(), str(val)) if val else "—"

    if field == "output_voltage_class":
        # Normalise legacy "low" (some Bronze2 CSVs stored HTL/TTL as low/high)
        m = {"ttl":"TTL","low":"TTL","universal":"Universal","high":"Universal","analog":"Analog"}
        return m.get(str(val).lower(), str(val)) if val else "—"

    if field == "is_programmable":
        if isinstance(val, bool): return "Yes" if val else "No"
        if str(val).lower() in ("true","1"): return "Yes"
        if str(val).lower() in ("false","0"): return "No"
        return "—"

    if field == "has_index":
        if isinstance(val, bool): return "Yes" if val else "No"
        return "Yes" if str(val).lower() in ("true","1","yes") else "No"

    if field in ("reverse_polarity_protection", "short_circuit_protection"):
        if isinstance(val, bool): return "Yes" if val else "No"
        return "Yes" if str(val).lower() in ("true","1","yes") else "No"

    if field == "max_speed_rpm":
        v = _safe_float(val)
        return f"{v:,.0f} RPM" if v is not None else "—"

    if field == "startup_torque_nm":
        v = _safe_float(val)
        return f"{v:.3f} Nm" if v is not None else "—"

    if field == "moment_of_inertia_gcm2":
        v = _safe_float(val)
        return f"{v:.2f} g·cm²" if v is not None else "—"

    if field == "weight_kg":
        v = _safe_float(val)
        return f"{v:.3f} kg" if v is not None else "—"

    if field == "pulse_frequency_max_kHz":
        v = _safe_float(val)
        return f"{v:,.0f} kHz" if v is not None else "—"

    if field == "power_consumption_max_mA":
        v = _safe_float(val)
        return f"{v:.0f} mA" if v is not None else "—"

    if field == "shaft_load_axial_n":
        v = _safe_float(val)
        return f"{v:.0f} N" if v is not None else "—"

    if field == "operating_temp_min_c":
        v = _safe_float(val)
        return f"{v:.0f} °C" if v is not None else "—"

    if field == "num_output_channels":
        return str(val) if val not in (None, "", "nan") else "—"

    # Generic fallback — round floats to 2 decimal places
    if isinstance(val, float):
        return f"{val:.2f}"
    return str(val) if val != "" else "—"


def _cpr_overlap(src_cpr: list, cand_row: dict) -> list:
    """Compute which source CPR values are covered by the candidate."""
    if _safe_bool(cand_row.get("is_programmable")):
        # Programmable: covers everything in range
        r_min = _safe_float(cand_row.get("ppr_range_min"))
        r_max = _safe_float(cand_row.get("ppr_range_max"))
        if r_min is not None and r_max is not None:
            return [v for v in src_cpr if r_min <= v <= r_max]
        return src_cpr  # assume full coverage if range unknown

    try:
        raw = str(cand_row.get("cpr_values", "[]"))
        cand_set = set(json.loads(raw))
        return [v for v in src_cpr if v in cand_set]
    except Exception:
        return []


def _kubler_kis40_kih40_display_code(
    family:      str,
    row:         dict,
    cpr_covered: list,
) -> str:
    """
    Reverse-encode a KIS40 or KIH40 Silver row into a real Kübler order code.

    Pattern: 8.{FAMILY}.{a}{b}{c}{d}.{PPPP}
      a = flange   KIS40: always "1" (only option)
                   KIH40: default "5" (stator coupling — most common stock type)
      b = bore     reverse-looked-up from shaft_bore_diameter_mm
      c = output   resolved from output_circuit_canonical + supply voltage range
      d = connect  M12+pins resolved uniquely; cable defaults to "2" (radial 2m)

    Ambiguities handled by picking the stock/standard code:
      Push-Pull 10-30V → "4" (with inverted, all stock types)
      Open Collector 10-30V → "3" (with inverted, standard)
      Cable direction (axial vs radial) → "2" radial (Path A default)
      KIH40 flange (spring element vs stator coupling) → "5" stator coupling

    PPR: cpr_covered[0] if available; else first entry in Silver cpr_values;
         else "XXXX".
    """
    fam = family.upper()

    # ── a: flange ─────────────────────────────────────────────────────────
    a = "1" if fam == "KIS40" else "5"

    # ── b: bore ───────────────────────────────────────────────────────────
    _KIS40_BORE_REV = {6.0: "3", 6.35: "5", 8.0: "6"}
    _KIH40_BORE_REV = {6.0: "2", 6.35: "3", 8.0: "4"}
    bore_rev  = _KIS40_BORE_REV if fam == "KIS40" else _KIH40_BORE_REV
    bore_mm   = _safe_float(row.get("shaft_bore_diameter_mm"))
    b = bore_rev.get(round(bore_mm, 2), "X") if bore_mm is not None else "X"

    # ── c: output circuit resolved by canonical + supply voltage range ─────
    # KIS40 and KIH40 share identical output codes (confirmed from datasheets).
    # Voltage range disambiguates codes that share the same canonical type:
    #   Push-Pull  5-30V  → "B"  (unique)
    #   Push-Pull  10-30V → "4"  (stock default; "8" = same spec, no inverted)
    #   RS422      5V     → "6"  (unique: v_min == v_max == 5)
    #   RS422      5-30V  → "C"  (unique)
    #   OC NPN     5-30V  → "A"  (unique)
    #   OC NPN     10-30V → "3"  (stock default; "7" = same spec, no inverted)
    circuit = (row.get("output_circuit_canonical") or "").lower()
    v_min   = _safe_float(row.get("supply_voltage_min_v"))
    v_max   = _safe_float(row.get("supply_voltage_max_v"))

    def _near(a, b):
        return a is not None and b is not None and abs(a - b) < 0.5

    is_5v_only = _near(v_min, 5.0) and _near(v_max, 5.0)
    is_5_30v   = _near(v_min, 5.0) and _near(v_max, 30.0)

    if "push" in circuit:
        c = "B" if is_5_30v else "4"
    elif "rs422" in circuit or "ttl" in circuit:
        c = "6" if is_5v_only else "C"
    elif "open" in circuit or "collector" in circuit:
        c = "A" if is_5_30v else "3"
    else:
        c = "X"

    # ── d: connection type ────────────────────────────────────────────────
    conn = (row.get("connection_type_canonical") or "").lower()
    pins = _safe_int(row.get("connector_pins"))

    if "m12" in conn and pins == 5:
        d = "4"
    elif "m12" in conn and pins == 8:
        d = "6"
    else:
        d = "2"    # cable: default radial 2m PVC (Path A)

    # ── PPR ───────────────────────────────────────────────────────────────
    ppr = None
    if cpr_covered:
        try:
            ppr = int(cpr_covered[0])
        except (TypeError, ValueError):
            pass
    if ppr is None:
        try:
            vals = json.loads(str(row.get("cpr_values", "[]")))
            if vals:
                ppr = int(vals[0])
        except Exception:
            pass

    ppr_str = f"{ppr:04d}" if ppr is not None else "XXXX"

    return f"8.{fam}.{a}{b}{c}{d}.{ppr_str}"


# ═══════════════════════════════════════════════════════════════════════════════
# Kübler display codes — Path A (4-segment) and Path B (K-series)
#
# Generated display codes appear in the result-card bold header (display_order_code).
# KIS40 / KIH40 are handled by the dedicated function above; this block covers
# all remaining Kübler families.
#
# Where Silver lacks a field needed to reconstruct the original order code
# exactly, a documented default is applied — see _KUBLER_DISPLAY_DEFAULTS.
# ═══════════════════════════════════════════════════════════════════════════════

_KUBLER_DISPLAY_DEFAULTS: dict[str, str] = {
    # ── Path A: cable / connection ─────────────────────────────────────────
    "cable_direction": (
        "Cable exit direction (axial vs radial) is not stored in Silver. "
        "Defaults to radial standard-length cable where multiple cable codes exist."
    ),
    # ── Path A: output-circuit ambiguities ────────────────────────────────
    "inverted_signal_pp_oc": (
        "Push-Pull / Open-Collector 10-30 V has two order codes: "
        "with inverted signal (e.g. '4'/'3' on KIS40) and without (e.g. '8'/'7'). "
        "Silver canonical is identical for both. Defaults to 'with inverted signal' "
        "(the more common stock type). Affects: KIS40, KIH40, 5803, 5805, 5823, 5825."
    ),
    "sendix_pp_5_30v_us_variant": (
        "Push-Pull 5-30 V on Sendix 5000/5020/7000/7020 has two codes: "
        "'2' (European standard) and '8' (US variant). Same Silver canonical. "
        "Defaults to '2' (European standard)."
    ),
    "a020_pp_ambiguity": (
        "A020 Push-Pull 10-30 V maps to codes '2' and '3' (same Silver canonical). "
        "Push-Pull 5-30 V maps to '5' and 'A'. Defaults to '2' and '5' respectively."
    ),
    "2400_pp_inverted": (
        "2400/2420 Push-Pull 5-24 V codes '1' (with inverted) and '2' (without) "
        "share the same canonical. Push-Pull 8-30 V codes '3' and '4' similarly. "
        "Defaults to '1' and '3' (with inverted signal)."
    ),
    # ── Path A: flange ambiguities ────────────────────────────────────────
    "flange_clamping_vs_synchro": (
        "Where a housing diameter + IP rating corresponds to both a clamping flange "
        "and a synchro flange, Silver stores only the housing diameter and IP — the "
        "flange type itself is not recorded. "
        "Defaults: Sendix 5000 ø58 mm → '7' (clamping); "
        "Sendix 5006 ø58 mm → '7' (clamping); "
        "5803/5805 ø58 mm → '1' (clamping); "
        "5804 ø58 mm → '1' (clamping)."
    ),
    "5834fs2_flexible_vs_rigid": (
        "5834FS2 has flexible torque-stop ('9' IP65 / 'J' IP67) and rigid torque-stop "
        "('A' IP65 / 'K' IP67) with the same housing + IP in Silver. "
        "Defaults to flexible."
    ),
    "5020_spring_vs_torque": (
        "5020 with housing_diameter_mm=None could be a spring element ('1' IP67 / '2' IP65) "
        "or a torque-stop ('3' IP67 / '4' IP65). Silver stores None for both mounting types. "
        "Defaults to spring element."
    ),
    "5823_5824_flange_ambiguity": (
        "5823/5824 flanges with the same housing_diameter_mm differ in bore type "
        "(through vs blind hollow), which Silver normalises to hollow_thru for all rows. "
        "Defaults to lower-numbered flange code ('1' for None/58 mm housing, '3' for 65 mm)."
    ),
    # ── Path A: informational-only flanges ────────────────────────────────
    "kis50_flange": (
        "KIS50 flange is informational only (clamping '8' vs synchro 'B'). "
        "Not stored in Silver. Defaults to '8' (clamping, from datasheet sample 8.KIS50.8314.1024)."
    ),
    "kih50_flange": (
        "KIH50 flange is informational only (spring element '2', torque stop '4', "
        "stator coupling 'D'). Not stored in Silver. Defaults to '2' (spring element, "
        "from datasheet sample 8.KIH50.2312.1024)."
    ),
    "a020_flange": (
        "A020 flange is informational only. Not stored in Silver. "
        "Defaults to '3' (from datasheet sample 8.A020.351A.2048)."
    ),
    "kih40_flange": (
        "KIH40 flange (stator coupling '5' vs spring element '2') is not stored in Silver. "
        "Defaults to '5' (stator coupling — most common stock type)."
    ),
    # ── Path A: bore edge cases ───────────────────────────────────────────
    "5814fs2_featherkey": (
        "5814FS2 bore codes '2' (plain flat) and 'A' (with feather key) "
        "both decode to 10 mm. Silver stores only bore diameter. Defaults to '2' (plain flat)."
    ),
    "5834fs3_tapered_bore": (
        "5834FS3 bore codes '3' and 'K' are both 10 mm hollow_thru in Silver. "
        "Defaults to '3' (standard through bore)."
    ),
    # ── Path B: K-series defaults (fields absent from Silver) ────────────
    "k_series_version_code": (
        "K-series segment-3 version code (e.g. S1, S3, H1, H2) is not stored in Silver. "
        "Defaults: solid shaft → 'S1'; hollow shaft → 'H1'."
    ),
    "k_series_mounting_code": (
        "K-series segment-3 mounting/flange code is not stored in Silver. "
        "Defaults: K58I solid → 'C5'; K58I / K58I-PR hollow → '65'; K80I / K80I-PR → '18'."
    ),
    "k_series_position_code": (
        "K-series segment-4 connector position (axial/radial/left/top) is not stored in Silver. "
        "Defaults to 'R' (radial) — most common catalogue configuration."
    ),
    "k_series_cable_medium": (
        "K-series segment-4 cable medium code (1=PVC, 2=TPE, 3=PUR, C=connector-housing) "
        "is not stored in Silver. Defaults to 'C' for connector-type connections, "
        "'1' (PVC cable) for cable-exit connections."
    ),
    "k_series_special_assignment": (
        "K-series M12/M23/MIL connectors have standard-assignment (2/3/4/D/E) and "
        "special-assignment (5/6/–/H/J) variants with the same Silver canonical. "
        "Defaults to standard assignment."
    ),
}


# ─── Shared low-level helpers ─────────────────────────────────────────────────

def _kub_near(a: Optional[float], b: float, tol: float = 0.5) -> bool:
    """Float proximity test. tol=0.5 is appropriate for supply-voltage matching."""
    return a is not None and abs(a - b) < tol


def _kub_ppr(cpr_covered: list, row: dict, width: int = 4) -> str:
    """Return PPR as a zero-padded string (width=4 for Path A, 5 for K-series)."""
    ppr = None
    if cpr_covered:
        try:
            ppr = int(cpr_covered[0])
        except (TypeError, ValueError):
            pass
    if ppr is None:
        try:
            vals = json.loads(str(row.get("cpr_values", "[]")))
            if vals:
                ppr = int(vals[0])
        except Exception:
            pass
    if ppr is None:
        return "X" * width
    return f"{ppr:0{width}d}"


def _kub_circuit(row: dict) -> str:
    """Normalise output_circuit_canonical to a short lookup key."""
    c = (row.get("output_circuit_canonical") or "").lower()
    if "push" in c:
        return "PP"
    if "rs422" in c or "ttl" in c:
        return "RS422"
    if "open" in c or "collector" in c:
        return "OC"
    if "sin" in c or "cos" in c:
        return "SC"
    return ""


def _kub_vclass(row: dict) -> str:
    """Classify supply voltage range into a canonical token for map lookup."""
    v_min = _safe_float(row.get("supply_voltage_min_v"))
    v_max = _safe_float(row.get("supply_voltage_max_v"))
    if _kub_near(v_min, 5.0) and _kub_near(v_max, 5.0):    return "5V"
    if _kub_near(v_min, 5.0) and _kub_near(v_max, 24.0):   return "5_24V"
    if _kub_near(v_min, 5.0) and _kub_near(v_max, 30.0):   return "5_30V"
    if _kub_near(v_min, 8.0) and _kub_near(v_max, 30.0):   return "8_30V"
    if _kub_near(v_min, 10.0) and _kub_near(v_max, 30.0):  return "10_30V"
    return ""


def _kub_out(row: dict, out_rev: dict) -> str:
    """Reverse-map (circuit, voltage_class) → single order-code character."""
    return out_rev.get((_kub_circuit(row), _kub_vclass(row)), "X")


def _kub_conn(row: dict, conn_rev: dict) -> str:
    """Reverse-map (connection_type_canonical.lower(), pins) → single order-code character.

    Two-stage lookup:
    1. Exact (conn, pins) match — handles M12/M23/MIL correctly.
    2. (conn, None) fallback — handles connector_pins stored as 0 instead of None
       in Silver (observed for cable-exit rows from several manufacturer ETLs).
    """
    conn = (row.get("connection_type_canonical") or "").lower()
    pins = _safe_int(row.get("connector_pins"))
    code = conn_rev.get((conn, pins))
    if code is None:
        code = conn_rev.get((conn, None), "X")
    return code


def _kub_flange_hi(row: dict, rev: dict, default: str) -> str:
    """Reverse flange from (housing_diameter_mm, ip_rating) — housing_ip mode."""
    housing = _safe_float(row.get("housing_diameter_mm"))
    ip      = _safe_int(row.get("ip_rating"))
    # First pass: match both housing and IP
    for (k_h, k_ip), code in rev.items():
        h_ok = (k_h is None and housing is None) or (
            k_h is not None and housing is not None and abs(housing - k_h) < 0.5
        )
        if h_ok and k_ip == ip:
            return code
    # Fallback: match housing only (handles missing IP in Silver)
    for (k_h, _), code in rev.items():
        h_ok = (k_h is None and housing is None) or (
            k_h is not None and housing is not None and abs(housing - k_h) < 0.5
        )
        if h_ok:
            return code
    return default


def _kub_flange_h(row: dict, rev: dict, default: str) -> str:
    """Reverse flange from housing_diameter_mm only — housing_only mode."""
    housing = _safe_float(row.get("housing_diameter_mm"))
    for k_h, code in rev.items():
        h_ok = (k_h is None and housing is None) or (
            k_h is not None and housing is not None and abs(housing - k_h) < 0.5
        )
        if h_ok:
            return code
    return default


def _kub_bore(row: dict, rev: dict) -> str:
    """Nearest-match bore code (tol=0.02 mm — distinguishes 9.5 vs 9.525 mm)."""
    b = _safe_float(row.get("shaft_bore_diameter_mm"))
    if b is None:
        return "X"
    best, dist = "X", float("inf")
    for k, v in rev.items():
        d = abs(b - k)
        if d < dist and d < 0.02:
            best, dist = v, d
    return best


def _kub_bore_ip(row: dict, rev: dict) -> str:
    """Reverse bore from (bore_mm, ip_rating) — shaft_bore_with_ip families."""
    b  = _safe_float(row.get("shaft_bore_diameter_mm"))
    ip = _safe_int(row.get("ip_rating"))
    if b is None:
        return "X"
    best, dist = "X", float("inf")
    for (k_b, k_ip), v in rev.items():
        if k_ip == ip:
            d = abs(b - k_b)
            if d < dist and d < 0.02:
                best, dist = v, d
    return best


def _kub_bore_type(row: dict, rev: dict) -> str:
    """Reverse bore from (bore_mm, shaft_type) — shaft_bore_with_type families."""
    b  = _safe_float(row.get("shaft_bore_diameter_mm"))
    st = row.get("shaft_type", "hollow_thru")
    if b is None:
        return "X"
    best, dist = "X", float("inf")
    for (k_b, k_st), v in rev.items():
        if k_st == st:
            d = abs(b - k_b)
            if d < dist and d < 0.02:
                best, dist = v, d
    return best


# ─── Output reverse maps ──────────────────────────────────────────────────────
# Key: (circuit_key, voltage_class) → order-code character.
# Lines marked (*) = Silver canonical is identical for multiple codes; pick shown.

_OR_KIH50 = {                        # KIS50, KIH50
    ("RS422", "5V"    ): "4",
    ("RS422", "5_30V" ): "1",
    ("PP",    "5_30V" ): "2",
    ("PP",    "10_30V"): "5",
    ("OC",    "5_30V" ): "3",
}
_OR_SENDIX = {                       # Sendix 5000, 5020, 7000, 7020
    ("RS422", "5V"    ): "4",
    ("RS422", "5_30V" ): "1",
    ("PP",    "5_30V" ): "2",        # * "8"=US variant, same canonical
    ("PP",    "10_30V"): "5",
    ("OC",    "5_30V" ): "3",
}
_OR_A020 = {                         # A020 hollow ø95 mm
    ("RS422", "5V"    ): "1",
    ("RS422", "10_30V"): "4",
    ("PP",    "10_30V"): "2",        # * "3"=same canonical
    ("PP",    "5_30V" ): "5",        # * "A"=same canonical
    ("SC",    "5V"    ): "8",
    ("SC",    "10_30V"): "9",
}
_OR_SINCOS = {                       # 5804/5824, 5814/5834, 5814FS2/FS3, 5834FS2/FS3
    ("SC",    "5V"    ): "1",
    ("SC",    "10_30V"): "2",
}
_OR_5803 = {                         # 5803, 5805 (high-temp shaft)
    ("RS422", "5V"    ): "4",
    ("RS422", "10_30V"): "5",
    ("PP",    "10_30V"): "6",        # * "7"=without inverted signal
}
_OR_5823 = {                         # 5823, 5825 (high-temp hollow)
    ("RS422", "5V"    ): "1",
    ("RS422", "10_30V"): "4",
    ("PP",    "10_30V"): "3",        # * "2"=same canonical
}
_OR_5006 = {                         # 5006, 5026
    ("PP",    "5_30V" ): "2",
    ("PP",    "10_30V"): "5",
    ("RS422", "5V"    ): "4",
}
_OR_2400 = {                         # 2400, 2420
    ("PP",    "5_24V" ): "1",        # * "2"=without inverted signal
    ("PP",    "8_30V" ): "3",        # * "4"=without inverted signal
    ("RS422", "5V"    ): "6",
}
_OR_2430 = {("RS422", "5V"): "6"}   # 2430, 2440 — RS422/5 V only


# ─── Connection reverse maps ──────────────────────────────────────────────────
# Key: (connection_type_canonical.lower(), connector_pins) → order-code character.
# Lines marked (*) = multiple codes exist; radial / standard-assignment chosen.

_CR_KIS50 = {
    ("cable", None): "2",    # * radial 1 m (vs "1"=axial)
    ("m12",   5   ): "R",    # radial M12 5-pin
    ("m12",   8   ): "4",    # radial M12 8-pin
    ("m23",   12  ): "8",    # radial M23 12-pin
}
_CR_KIH50 = {
    ("cable", None): "1",    # radial 1 m PVC (* "E"=tangential)
    ("m12",   5   ): "R",
    ("m12",   8   ): "2",
    ("m23",   12  ): "4",
}
_CR_A020 = {
    ("cable", None): "1",    # axial cable — only cable option for A020
    ("m23",   12  ): "2",
    ("m12",   8   ): "E",
}
_CR_5000 = {
    ("cable",  None): "2",   # * radial 2 m
    ("m12",    5   ): "R",
    ("m12",    8   ): "4",   # * radial (vs "3"=axial, "L"=variant)
    ("m23",    12  ): "8",   # * radial (vs "7"=axial, "M"=variant)
    ("ms/mil", 7   ): "W",
    ("ms/mil", 10  ): "Y",
    ("ms/mil", 6   ): "9",
    ("d-sub",  9   ): "N",
}
_CR_5020 = {
    ("cable",  None): "1",   # * radial 1 m (vs "A"=special-length, "E"=tangential)
    ("m12",    5   ): "R",
    ("m12",    8   ): "2",   # * standard (vs "H","L"=same type)
    ("m23",    12  ): "4",   # * standard (vs "M"=same type)
    ("ms/mil", 7   ): "6",
    ("ms/mil", 10  ): "7",
    ("d-sub",  9   ): "N",
}
_CR_5804 = {                 # 5804 — cable + M23 only
    ("cable", None): "2",    # * radial
    ("m23",   12  ): "5",    # radial M23 12-pin
}
_CR_5823 = {                 # 5823, 5824 — cable + M23 only
    ("cable", None): "1",
    ("m23",   12  ): "2",
}
_CR_5803 = {                 # 5803 — cable + M23 + MIL
    ("cable",  None): "2",   # * radial
    ("m23",    12  ): "5",
    ("ms/mil", 7   ): "W",
    ("ms/mil", 10  ): "Y",
}
_CR_5805 = {                 # 5805 — cable + M12/8 + M23
    ("cable", None): "2",    # * radial
    ("m12",   8   ): "G",    # radial M12 8-pin
    ("m23",   12  ): "5",
}
_CR_5825 = {                 # 5825 — cable + M12/8 + M23
    ("cable", None): "1",
    ("m12",   8   ): "C",
    ("m23",   12  ): "2",
}
_CR_5814 = {                 # Sendix 5814 — cable + M12/8 only
    ("cable", None): "2",    # * radial
    ("m12",   8   ): "6",    # radial M12 8-pin
}
_CR_5814FS = {               # 5814FS2, 5814FS3 — cable + M12/8 + M23
    ("cable", None): "2",    # * radial
    ("m12",   8   ): "6",
    ("m23",   12  ): "4",
}
_CR_5834 = {                 # Sendix 5834 — cable + M12/8 (* tangential cable ignored)
    ("cable", None): "2",
    ("m12",   8   ): "6",
}
_CR_5834FS = {               # 5834FS2, 5834FS3 — cable + M12/8 + M23
    ("cable", None): "2",    # * radial (vs "E"=tangential)
    ("m12",   8   ): "6",
    ("m23",   12  ): "4",
}
_CR_5006 = {("m12", 8): "4"}    # 5006 — M12/8-pin hardcoded in order template
_CR_5026 = {("m12", 8): "2"}    # 5026 — M12/8-pin hardcoded in order template
_CR_CABLE = {("cable", None): "2"}   # 7000, 7020, 2400-series — radial cable only


# ─── Flange reverse maps — housing_ip mode ───────────────────────────────────
# Key: (housing_diameter_mm_or_None, ip_rating) → flange code.
# Where multiple codes share the same (housing, IP), first listed is preferred.

_FR_5000 = {
    (50.8,  67): "5",   (50.8,  65): "6",
    (58.0,  67): "7",   (58.0,  65): "8",   # clamping; * "A"/"B"=synchro same spec
    (52.3,  67): "3",   (52.3,  65): "4",
    (63.5,  67): "C",   (63.5,  65): "D",   # * "E"/"F"=servo-US same spec
    (115.0, 67): "G",
}
_FR_5020 = {
    (None,  67): "1",   (None,  65): "2",   # spring element; * "3"/"4"=torque-stop
    (65.0,  67): "7",   (65.0,  65): "8",
    (63.0,  67): "C",   (63.0,  65): "D",
    (57.2,  67): "5",   (57.2,  65): "6",
}
_FR_5006 = {
    (58.0,  67): "7",   # clamping; * "A"=synchro same spec
    (63.5,  67): "C",
}
_FR_5026 = {
    (None,  67): "1",
    (63.0,  67): "C",
}
_FR_5803 = {
    (58.0,  65): "1",   # clamping; * "2"=synchro same spec
    (63.5,  65): "P",   # * "M"=square same spec
}
_FR_5804  = {(58.0, 65): "1"}   # * "2"=synchro same (housing, IP)
_FR_5814  = {(58.0, 65): "1"}   # only option
_FR_5814FS2 = {(58.0, 65): "1", (58.0, 67): "3"}
_FR_5834  = {(58.0, 65): "1", (63.0, 65): "5"}
_FR_5834FS2 = {
    (58.0, 65): "9",   # flexible torque-stop; * "A"=rigid same spec
    (58.0, 67): "J",   # flexible torque-stop; * "K"=rigid same spec
    (63.0, 65): "B",
    (63.0, 67): "L",
}
_FR_7020 = {(70.0, 67): "1", (65.0, 67): "5"}
_FR_2400 = {(24.0, 65): "1", (28.0, 65): "3", (30.0, 65): "2"}

# ─── Flange reverse maps — housing_only mode ─────────────────────────────────
# For families where IP comes from the bore slot, not the flange slot.
# Key: housing_diameter_mm_or_None → flange code.

_FH_5823 = {None: "1", 65.0: "3"}   # IP from bore; * "2"/"4"=same housing (blind bore)
_FH_5824 = {58.0: "1", 65.0: "3"}   # IP from bore; * "2"/"4"=same housing (blind bore)


# ─── Bore reverse maps ────────────────────────────────────────────────────────
# Simple: {bore_mm: code}  — used with _kub_bore() (tol=0.02 mm).
# Note: 9.5 mm (metric) and 9.525 mm (3/8") are 25 µm apart; well above tol.

_BR_KIS50  = {6.0:"1", 8.0:"6", 10.0:"3", 12.0:"5", 9.525:"8"}  # * "D"=10mm measuring-wheel
_BR_KIH50  = {8.0:"9", 9.52:"4", 10.0:"3", 12.0:"5", 12.75:"6", 14.0:"A", 15.0:"8"}
_BR_A020   = {20.0:"C", 24.0:"6", 25.0:"5", 28.0:"3", 30.0:"A",
              38.0:"2", 40.0:"B", 42.0:"1", 25.4:"4"}
_BR_5000   = {6.0:"1", 6.35:"2", 8.0:"6", 9.5:"4", 9.525:"8", 10.0:"3", 11.0:"B", 12.0:"5"}
_BR_5020   = {6.0:"1", 6.35:"2", 8.0:"9", 9.525:"4", 10.0:"3", 12.0:"5",
              12.7:"6", 14.0:"A", 15.0:"8", 15.875:"7"}
_BR_5006   = {6.0:"1", 9.525:"8", 10.0:"3"}
_BR_5026   = {6.35:"2", 9.525:"4", 10.0:"3", 12.0:"5", 12.7:"6", 15.0:"8"}
_BR_5803   = {6.0:"1", 9.525:"P", 10.0:"2"}
_BR_5804   = {6.0:"1", 10.0:"2"}
_BR_5814   = {10.0: "2"}
_BR_5814FS2 = {10.0: "2"}               # * "A"=feather-key, same bore diameter
_BR_5834FS3 = {10.0:"3", 12.0:"4", 14.0:"5"}  # * "K"=tapered also 10mm → "3"
_BR_7000   = {10.0:"2", 12.0:"1"}
_BR_7020   = {12.0:"1", 14.0:"2"}
_BR_2400   = {4.0:"1", 5.0:"3", 6.0:"2", 6.35:"4"}  # * "6"=6mm-with-flat same bore
_BR_2420   = {4.0:"1", 6.0:"2", 6.35:"4"}
_BR_2430   = {4.0:"1", 5.0:"3", 6.0:"2"}
_BR_2440   = {4.0:"1", 6.0:"2"}

# Bore+IP combined: {(bore_mm, ip_rating): code} — shaft_bore_with_ip families.
# IP is 40 (no seal) or 66 (with seal) — NOT 65/67.
_BRI_5823 = {
    (6.0,  40): "1",  (6.0,  66): "2",
    (8.0,  40): "3",  (8.0,  66): "4",
    (10.0, 40): "5",  (10.0, 66): "6",
    (12.0, 40): "7",  (12.0, 66): "8",
}

# Bore+shaft_type combined: {(bore_mm, shaft_type): code} — shaft_bore_with_type families.
_BRT_5834 = {
    (10.0,  "hollow_thru"): "3",
    (12.0,  "hollow_thru"): "4",
    (14.0,  "hollow_thru"): "5",
    (15.0,  "hollow_thru"): "6",
    (9.525, "hollow_thru"): "8",
    (12.7,  "hollow_thru"): "9",
    (10.0,  "solid"      ): "K",
}
_BRT_5834FS2 = {
    (10.0, "hollow_thru"): "3",
    (12.0, "hollow_thru"): "4",
    (14.0, "hollow_thru"): "5",
    (10.0, "solid"      ): "K",
}


# ─── Path A family configuration table ───────────────────────────────────────
# Key = product_family from Silver, uppercased.
# bore_mode: "simple" | "with_ip" | "with_type"
# flange_mode: "fixed" | "housing_ip" | "housing_only"

_PATH_A_CFG: dict[str, dict] = {
    # ── Base compact encoders ─────────────────────────────────────────────
    "KIS50": dict(prefix="8", flange_mode="fixed",      flange_arg="8",       flange_default="8",
                  bore_mode="simple",    bore_arg=_BR_KIS50,  out_rev=_OR_KIH50,  conn_rev=_CR_KIS50),
    "KIH50": dict(prefix="8", flange_mode="fixed",      flange_arg="2",       flange_default="2",
                  bore_mode="simple",    bore_arg=_BR_KIH50,  out_rev=_OR_KIH50,  conn_rev=_CR_KIH50),
    "A020":  dict(prefix="8", flange_mode="fixed",      flange_arg="3",       flange_default="3",
                  bore_mode="simple",    bore_arg=_BR_A020,   out_rev=_OR_A020,   conn_rev=_CR_A020),
    # ── Sendix 5000/5020 ─────────────────────────────────────────────────
    "SENDIX 5000": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5000,  flange_default="7",
                        bore_mode="simple",    bore_arg=_BR_5000,   out_rev=_OR_SENDIX, conn_rev=_CR_5000),
    "SENDIX 5020": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5020,  flange_default="1",
                        bore_mode="simple",    bore_arg=_BR_5020,   out_rev=_OR_SENDIX, conn_rev=_CR_5020),
    # ── Sendix 5006/5026 (IP67, M12/8 hardcoded) ─────────────────────────
    "SENDIX 5006": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5006,  flange_default="7",
                        bore_mode="simple",    bore_arg=_BR_5006,   out_rev=_OR_5006,   conn_rev=_CR_5006),
    "SENDIX 5026": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5026,  flange_default="1",
                        bore_mode="simple",    bore_arg=_BR_5026,   out_rev=_OR_5006,   conn_rev=_CR_5026),
    # ── High-temperature 5803/5823 series ────────────────────────────────
    "5803": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5803,  flange_default="1",
                 bore_mode="simple",    bore_arg=_BR_5803,   out_rev=_OR_5803,   conn_rev=_CR_5803),
    "5823": dict(prefix="8", flange_mode="housing_only", flange_arg=_FH_5823, flange_default="1",
                 bore_mode="with_ip",   bore_arg=_BRI_5823,  out_rev=_OR_5823,   conn_rev=_CR_5823),
    # ── SinCos 5804/5824 series ───────────────────────────────────────────
    "5804": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5804,  flange_default="1",
                 bore_mode="simple",    bore_arg=_BR_5804,   out_rev=_OR_SINCOS, conn_rev=_CR_5804),
    "5824": dict(prefix="8", flange_mode="housing_only", flange_arg=_FH_5824, flange_default="1",
                 bore_mode="with_ip",   bore_arg=_BRI_5823,  out_rev=_OR_SINCOS, conn_rev=_CR_5823),
    # ── High-resolution 5805/5825 series ─────────────────────────────────
    "5805": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5803,  flange_default="1",
                 bore_mode="simple",    bore_arg=_BR_5803,   out_rev=_OR_5803,   conn_rev=_CR_5805),
    "5825": dict(prefix="8", flange_mode="housing_only", flange_arg=_FH_5824, flange_default="1",
                 bore_mode="with_ip",   bore_arg=_BRI_5823,  out_rev=_OR_5823,   conn_rev=_CR_5825),
    # ── Sendix SinCos 5814/5834 ──────────────────────────────────────────
    "SENDIX 5814": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5814,   flange_default="1",
                        bore_mode="simple",    bore_arg=_BR_5814,    out_rev=_OR_SINCOS,  conn_rev=_CR_5814),
    "SENDIX 5834": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5834,   flange_default="1",
                        bore_mode="with_type", bore_arg=_BRT_5834,   out_rev=_OR_SINCOS,  conn_rev=_CR_5834),
    # ── Safety SinCos 5814FS2/FS3 (SIL2/SIL3) ───────────────────────────
    "5814FS2": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5814FS2, flange_default="1",
                    bore_mode="simple",    bore_arg=_BR_5814FS2, out_rev=_OR_SINCOS,  conn_rev=_CR_5814FS),
    "5814FS3": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5814FS2, flange_default="1",
                    bore_mode="simple",    bore_arg=_BR_5814FS2, out_rev=_OR_SINCOS,  conn_rev=_CR_5814FS),
    # ── Safety SinCos 5834FS2/FS3 (hollow) ──────────────────────────────
    "5834FS2": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5834FS2, flange_default="9",
                    bore_mode="with_type", bore_arg=_BRT_5834FS2, out_rev=_OR_SINCOS, conn_rev=_CR_5834FS),
    "5834FS3": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_5834FS2, flange_default="9",
                    bore_mode="simple",    bore_arg=_BR_5834FS3,  out_rev=_OR_SINCOS, conn_rev=_CR_5834FS),
    # ── ATEX 7000/7020 ───────────────────────────────────────────────────
    "SENDIX 7000": dict(prefix="8", flange_mode="fixed",      flange_arg="1",       flange_default="1",
                        bore_mode="simple",    bore_arg=_BR_7000,   out_rev=_OR_SENDIX, conn_rev=_CR_CABLE),
    "SENDIX 7020": dict(prefix="8", flange_mode="housing_ip",  flange_arg=_FR_7020,  flange_default="1",
                        bore_mode="simple",    bore_arg=_BR_7020,   out_rev=_OR_SENDIX, conn_rev=_CR_CABLE),
    # ── Miniature 2400-series ─────────────────────────────────────────────
    "2400": dict(prefix="05", flange_mode="housing_ip",  flange_arg=_FR_2400,  flange_default="1",
                 bore_mode="simple",    bore_arg=_BR_2400,   out_rev=_OR_2400,   conn_rev=_CR_CABLE),
    "2420": dict(prefix="05", flange_mode="fixed",       flange_arg="1",       flange_default="1",
                 bore_mode="simple",    bore_arg=_BR_2420,   out_rev=_OR_2400,   conn_rev=_CR_CABLE),
    "2430": dict(prefix="8",  flange_mode="housing_ip",  flange_arg=_FR_2400,  flange_default="1",
                 bore_mode="simple",    bore_arg=_BR_2430,   out_rev=_OR_2430,   conn_rev=_CR_CABLE),
    "2440": dict(prefix="8",  flange_mode="fixed",       flange_arg="1",       flange_default="1",
                 bore_mode="simple",    bore_arg=_BR_2440,   out_rev=_OR_2430,   conn_rev=_CR_CABLE),
}


def _path_a_display_code(
    fam_upper:   str,
    row:         dict,
    cpr_covered: list,
) -> Optional[str]:
    """
    Build a Path-A 4-segment Kübler display code driven by _PATH_A_CFG.
    Pattern: {prefix}.{FAMILY_TOKEN}.{a}{b}{c}{d}.{PPPP}
    Returns None if family is not in the config table.
    """
    cfg = _PATH_A_CFG.get(fam_upper)
    if cfg is None:
        return None

    prefix    = cfg["prefix"]
    fam_token = fam_upper.replace("SENDIX ", "") if fam_upper.startswith("SENDIX ") else fam_upper

    # a: flange
    mode = cfg["flange_mode"]
    if mode == "fixed":
        a = cfg["flange_arg"]
    elif mode == "housing_ip":
        a = _kub_flange_hi(row, cfg["flange_arg"], cfg["flange_default"])
    else:
        a = _kub_flange_h(row, cfg["flange_arg"], cfg["flange_default"])

    # b: bore
    bmode = cfg["bore_mode"]
    if bmode == "simple":
        b = _kub_bore(row, cfg["bore_arg"])
    elif bmode == "with_ip":
        b = _kub_bore_ip(row, cfg["bore_arg"])
    else:
        b = _kub_bore_type(row, cfg["bore_arg"])

    # c: output   d: connection
    c = _kub_out(row, cfg["out_rev"])
    d = _kub_conn(row, cfg["conn_rev"])

    ppr_s = _kub_ppr(cpr_covered, row, width=4)

    return f"{prefix}.{fam_token}.{a}{b}{c}{d}.{ppr_s}"


# ─── Path B: K-series display codes ──────────────────────────────────────────
# Pattern: {FAMILY}.{seg1}.{PPR:05d}.{seg3}.{seg4}
#   seg1 = O[PR]{interface}                          (3–5 chars)
#   seg3 = {supply}{version(2)}{mounting(2)}{bore(2)} (7 chars total)
#   seg4 = {ip_code(2)}{position}{i_conn}{k_conn}    (5 chars total)
#
# Defaults (all documented in _KUBLER_DISPLAY_DEFAULTS):
#   version:  S1 (solid) / H1 (hollow)
#   mounting: C5 (K58I solid) · 65 (K58I/K58I-PR hollow) · 18 (K80I/K80I-PR)
#   position: R (radial)
#   i_conn:   C (connector) / 1 (cable)
#   k_conn:   standard-assignment code chosen over special-assignment

_K58I_SBR: dict[float, str] = {       # K58I solid bore → 2-char code
    6.0:"06", 6.35:"1A", 8.0:"08", 9.525:"2A", 10.0:"10", 11.0:"11", 12.0:"12",
}
_K58I_HBR: dict[float, str] = {       # K58I/K58I-PR hollow bore → 2-char code
    6.0:"06", 6.35:"1A",  8.0:"08",  9.525:"2A", 10.0:"10",  12.0:"12",
    12.7:"3A", 14.0:"14", 15.0:"15", 15.875:"4A",16.0:"16",  19.05:"5A",
    20.0:"20", 22.0:"22", 22.23:"6A",24.0:"24",  25.0:"25",  25.4:"7A",
}
_K80I_BRV: dict[float, str] = {       # K80I/K80I-PR bore → 2-char code (hollow only)
    14.0:"14",  15.0:"15",  15.875:"4A", 16.0:"16",  18.0:"18",  19.05:"5A",
    20.0:"20",  22.225:"6A",25.0:"25",   25.4:"7A",  28.0:"28",  28.575:"8A",
    30.0:"30",  31.75:"9A", 32.0:"32",   35.0:"35",  38.0:"38",  40.0:"40",  42.0:"42",
}
# K-series connector reverse: (conn.lower(), pins) → (i_conn, k_conn)
_K_CONN_REV: dict = {
    ("cable",   None): ("1", "1"),
    ("m12",     8   ): ("C", "2"),   # * "5"=special assignment
    ("m12",     5   ): ("C", "3"),   # * "6"=special assignment
    ("m23",     12  ): ("C", "4"),
    ("ms/mil",  7   ): ("C", "D"),   # * "H"=special assignment
    ("ms/mil",  10  ): ("C", "E"),   # * "J"=special assignment
}


def _kubler_kseries_display_code(
    family:      str,
    row:         dict,
    cpr_covered: list,
) -> Optional[str]:
    """
    Build a K-series 5-segment display code from a Silver row.
    Returns None if the bore is unknown (cannot form a valid code).

    Verified against samples:
      K58I.OPP.01024.2S1C510.65RC2   (solid ø10mm, PP/5-30V, IP65, M12/8-pin)
      K58I.OPP.01024.2H1657A.65RC4   (hollow ø25.4mm, PP/5-30V, IP65, M23/12-pin)
      K80I.OPP.02048.2H11838.65RC4   (hollow ø38mm, PP/5-30V, IP65, M23/12-pin)
    """
    fam    = family.upper().strip()
    is_pr  = "-PR" in fam
    is_k80 = fam.startswith("K80")
    fam_tok = "K80I" if is_k80 else "K58I"

    # seg1: O[PR]{interface}
    # _kub_circuit() returns canonical keys ("RS422"); K-series order codes
    # use 2-char interface codes ("RS", "PP", "SC").
    circuit = _kub_circuit(row)
    if not circuit:
        return None
    _K_IFACE = {"RS422": "RS", "PP": "PP", "SC": "SC", "OC": "OC"}
    interface = _K_IFACE.get(circuit, circuit)
    seg1 = f"OPR{interface}" if is_pr else f"O{interface}"

    # seg2: PPR (5-digit zero-padded)
    # PR variants are fully programmable — PPR is customer-specified at order time.
    # Show XXXXX so the card makes clear the user must specify PPR when ordering.
    # Non-PR K-series have a fixed PPR per Silver row; use the normal PPR helper.
    if is_pr:
        ppr_s = "XXXXX"
    else:
        ppr_s = _kub_ppr(cpr_covered, row, width=5)

    # seg3 (7 chars): supply + version(2) + mounting(2) + bore_code(2)
    vclass = _kub_vclass(row)
    if is_pr or is_k80:
        supply = "2"                              # PR and K80 have no 5V-only option
    else:
        supply = "1" if (circuit in ("RS422", "SC") and vclass == "5V") else "2"

    shaft      = (row.get("shaft_type") or "solid").lower()
    is_hollow  = "hollow" in shaft
    if is_hollow:
        version  = "H1"
        mounting = "18" if is_k80 else "65"
    else:
        version  = "S1"
        mounting = "C5"

    bore_mm = _safe_float(row.get("shaft_bore_diameter_mm"))
    if bore_mm is None:
        return None
    bore_rev = _K80I_BRV if is_k80 else (_K58I_HBR if is_hollow else _K58I_SBR)
    bore_code, best_dist = "XX", float("inf")
    for k, v in bore_rev.items():
        d = abs(bore_mm - k)
        if d < best_dist and d < 0.02:
            bore_code, best_dist = v, d

    seg3 = f"{supply}{version}{mounting}{bore_code}"   # 1+2+2+2 = 7 ✓

    # seg4 (5 chars): ip_code(2) + position(1) + i_conn(1) + k_conn(1)
    ip      = _safe_int(row.get("ip_rating"))
    ip_code = "6A" if ip == 67 else "65"

    conn = (row.get("connection_type_canonical") or "").lower()
    pins = _safe_int(row.get("connector_pins"))
    i_conn, k_conn = _K_CONN_REV.get((conn, pins), ("C", "2"))

    seg4 = f"{ip_code}R{i_conn}{k_conn}"              # 2+1+1+1 = 5 ✓

    return f"{fam_tok}.{seg1}.{ppr_s}.{seg3}.{seg4}"


# ─── Master dispatcher ────────────────────────────────────────────────────────

def _kubler_display_code(
    family:      str,
    row:         dict,
    cpr_covered: list,
) -> Optional[str]:
    """
    Dispatch to the correct display-code generator for all Kübler families
    except KIS40/KIH40 (which retain their own dedicated function above).
    Returns None if the family is not yet supported — caller falls back to
    the Silver family name.
    """
    fam_upper = (family or "").upper().strip()
    if fam_upper in ("K58I", "K58I-PR", "K80I", "K80I-PR"):
        return _kubler_kseries_display_code(fam_upper, row, cpr_covered)
    return _path_a_display_code(fam_upper, row, cpr_covered)


def _make_display_code(
    manufacturer: str,
    part_number:  str,
    family:       str,
    cpr_covered:  list,
    row:          Optional[dict] = None,
) -> str:
    """
    Compute a human-readable order code for the result card header.

    EPC:              Strip internal 'EPC-' prefix; fill 'XXXX' PPR placeholder.
    Kübler KIS40/KIH40: Dedicated reverse-encoder (dedicated function above).
    Kübler other:     Table-driven reverse-encoder covering 29 further families.
                      Falls back to Silver family name if family not in table.
    Others:           part_number is already a meaningful code — return as-is.
    """
    mfr = manufacturer.lower().strip()

    if "encoder products" in mfr or mfr == "epc":
        code = part_number
        if code.upper().startswith("EPC-"):
            code = code[4:]
        if "XXXX" in code.upper() and cpr_covered:
            ppr  = int(cpr_covered[0])
            code = code.replace("XXXX", f"{ppr:04d}")
        return code

    if "kubler" in mfr or "kübler" in mfr:
        fam = (family or "").upper()
        if fam in ("KIS40", "KIH40") and row is not None:
            return _kubler_kis40_kih40_display_code(fam, row, cpr_covered)
        if row is not None:
            code = _kubler_display_code(family or "", row, cpr_covered)
            if code:
                return code
        return family or part_number

    return part_number


def serialize_source(src: dict, user_input_code: str = "") -> dict:
    """Convert Silver source row to the frontend source format."""
    cpr_raw = src.get("cpr_values")
    cpr_list = []
    try:
        cpr_list = json.loads(str(cpr_raw)) if cpr_raw else []
    except Exception:
        pass

    return {
        "part_number":               src.get("part_number", ""),
        "user_input_code":           user_input_code or src.get("display_order_code", "") or src.get("part_number", ""),
        "display_order_code":        src.get("display_order_code", ""),
        "manufacturer":              MFR_FULL_NAMES.get(src.get("manufacturer", "").lower(), src.get("manufacturer", "")),
        "family":                    src.get("product_family", ""),
        "shaft_type":                src.get("shaft_type", ""),
        "shaft_bore_diameter_mm":    round(_safe_float(src.get("shaft_bore_diameter_mm")), 3) if _safe_float(src.get("shaft_bore_diameter_mm")) is not None else None,
        "ip_rating":                 _safe_int(src.get("ip_rating")),
        "output_circuit_canonical":  src.get("output_circuit_canonical", ""),
        "connection_type_canonical": src.get("connection_type_canonical", ""),
        "connector_pins":            _safe_int(src.get("connector_pins")),
        "housing_diameter_mm":       round(_safe_float(src.get("housing_diameter_mm")), 1) if _safe_float(src.get("housing_diameter_mm")) is not None else None,
        "supply_voltage_min_v":      _safe_float(src.get("supply_voltage_min_v")),
        "supply_voltage_max_v":      _safe_float(src.get("supply_voltage_max_v")),
        "operating_temp_max_c":      _safe_float(src.get("operating_temp_max_c")),
        "sensing_method":            src.get("sensing_method", ""),
        "cpr_values":                cpr_list,
        "shock_resistance_ms2":      round(_safe_float(src.get("shock_resistance_ms2")), 1) if _safe_float(src.get("shock_resistance_ms2")) is not None else None,
        "vibration_resistance_ms2":  round(_safe_float(src.get("vibration_resistance_ms2")), 1) if _safe_float(src.get("vibration_resistance_ms2")) is not None else None,
        "shaft_load_radial_n":       round(_safe_float(src.get("shaft_load_radial_n")), 1) if _safe_float(src.get("shaft_load_radial_n")) is not None else None,
        "output_voltage_class":      src.get("output_voltage_class", ""),
    }


def serialize_result(
    row:      dict,
    src:      dict,
    rank:     int,
    src_cpr:  list,
    t2_cfg:   dict,
    t3_cfg:   dict,
) -> dict:
    """
    Convert one row from the scored DataFrame + source dict
    into the JSON structure the frontend result card expects.
    """
    manufacturer = row.get("manufacturer", "")
    family       = row.get("product_family", "")
    part_number  = row.get("part_number", "")
    source_ds    = row.get("source_datasheet", "")

    product_url, url_type = get_product_url(manufacturer, part_number, family, source_ds)

    # CPR overlap
    cpr_covered = _cpr_overlap(src_cpr, row)

    # Human-readable order code for the result card header
    display_code = _make_display_code(manufacturer, part_number, family, cpr_covered, row)

    # ── T2 field breakdown ─────────────────────────────────────────────────
    t2 = {}
    for field in t2_cfg:
        score_key = f"sc_t2_{field}"
        raw_score = row.get(score_key)
        score     = _safe_float(raw_score)

        # Format candidate value
        if field == "cpr_values":
            is_prog = _safe_bool(row.get("is_programmable"))
            r_min   = _safe_int(row.get("ppr_range_min"))
            r_max   = _safe_int(row.get("ppr_range_max"))
            if is_prog and r_min is not None and r_max is not None:
                cand_val = f"{r_min:,}–{r_max:,} (programmable)"
            elif r_min is not None and r_max is not None:
                cand_val = f"{r_min:,}–{r_max:,} (any integer)"
            else:
                cand_val = _fmt_field(row, field)
            src_val = _fmt_field(src, field)
        else:
            src_val  = _fmt_field(src, field)
            cand_val = _fmt_field(row, field)

        t2[field] = {
            "score":            round(score, 4) if score is not None else None,
            "src_val":          src_val,
            "cand_val":         cand_val,
            "label":            FIELD_LABELS.get(field, field),
            "src_native_label": _native_label(src.get("manufacturer", ""), field),
            "cand_native_label":_native_label(manufacturer, field),
        }

    # ── T3 field breakdown ─────────────────────────────────────────────────
    t3 = {}
    for field in t3_cfg:
        score_key = f"sc_t3_{field}"
        raw_score = row.get(score_key)
        score     = _safe_float(raw_score)

        if field == "supply_voltage":
            src_val  = _fmt_field(src,  "supply_voltage")
            cand_val = _fmt_field(row,  "supply_voltage")
        else:
            src_val  = _fmt_field(src, field)
            cand_val = _fmt_field(row, field)

        t3[field] = {
            "score":            round(score, 4) if score is not None else None,
            "src_val":          src_val,
            "cand_val":         cand_val,
            "label":            FIELD_LABELS.get(field, field),
            "src_native_label": _native_label(src.get("manufacturer", ""), field),
            "cand_native_label":_native_label(manufacturer, field),
        }

    # ── Additional fields (all Silver cols not in T2/T3 scored) ─────────────
    EXTRA_FIELDS = [
        "shaft_type", "sensing_method", "is_programmable",
        "shaft_load_axial_n", "operating_temp_min_c",
        "num_output_channels", "has_index", "pulse_frequency_max_kHz",
        "power_consumption_max_mA", "reverse_polarity_protection",
        "short_circuit_protection", "flange_type_canonical",
        "housing_material", "flange_material", "shaft_material",
        "max_speed_rpm", "startup_torque_nm", "moment_of_inertia_gcm2",
        "weight_kg", "bearing_life_rev", "mttfd_years",
    ]
    extra = {}
    for field in EXTRA_FIELDS:
        extra[field] = {
            "src_val":          _fmt_field(src, field),
            "cand_val":         _fmt_field(row, field),
            "label":            FIELD_LABELS.get(field, field),
            "src_native_label": _native_label(src.get("manufacturer", ""), field),
            "cand_native_label":_native_label(manufacturer, field),
        }

    # -- T1 hard-stop fields (always passed -- candidate survived pre-scoring gate)
    # Bore is T1 only for hollow encoders; for solid shaft it is T2 scoring.
    src_shaft = src.get("shaft_type", "solid")
    T1_FIELDS = [
        ("shaft_type",           "Shaft Type"),
        ("output_voltage_class", "Output Voltage Class"),
    ]
    if src_shaft in ("hollow_blind", "hollow_thru"):
        T1_FIELDS.append(("shaft_bore_diameter_mm", "Bore Diameter"))
    t1 = {}
    for field, label in T1_FIELDS:
        t1[field] = {
            "src_val":           _fmt_field(src, field),
            "cand_val":          _fmt_field(row, field),
            "label":             FIELD_LABELS.get(field, label),
            "src_native_label":  _native_label(src.get("manufacturer", ""), field),
            "cand_native_label": _native_label(manufacturer, field),
            "passed":            True,
        }

    return {
        "rank":             rank,
        "part_number":      part_number,
        "display_order_code": display_code,
        "manufacturer":     manufacturer.upper(),
        "manufacturer_full": MFR_FULL_NAMES.get(manufacturer.lower(), manufacturer),
        "family":           family,
        "total_score":      round(_safe_float(row.get("total_score")) or 0, 4),
        "t2_score":         round(_safe_float(row.get("t2_score"))    or 0, 4),
        "t3_score":         round(_safe_float(row.get("t3_score"))    or 0, 4),
        "product_url":      product_url,
        "url_type":         url_type,
        "is_programmable":  _safe_bool(row.get("is_programmable")),
        "ppr_range_min":    _safe_int(row.get("ppr_range_min")),
        "ppr_range_max":    _safe_int(row.get("ppr_range_max")),
        "cpr_covered":      cpr_covered,
        "cpr_total":        len(src_cpr),
        "t1":               t1,
        "t2":               t2,
        "t3":               t3,
        "extra":            extra,
    }