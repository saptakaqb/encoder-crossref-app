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
    "sensing_method":           "Sensing Method",
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
# Maps canonical Silver field → exact field name from each manufacturer's data.
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

    if field == "supply_voltage":
        # Multi-field: reads supply_voltage_min_v + supply_voltage_max_v
        v_min = _safe_float(data.get("supply_voltage_min_v"))
        v_max = _safe_float(data.get("supply_voltage_max_v"))
        if v_min is not None and v_max is not None:
            return f"{v_min:g}–{v_max:g} V"
        return "—"

    if field == "shaft_type":
        m = {"solid":"Solid shaft","hollow_blind":"Hollow bore (blind)","hollow_thru":"Hollow bore (through)"}
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


def serialize_source(src: dict) -> dict:
    """Convert Silver source row to the frontend source format."""
    cpr_raw = src.get("cpr_values")
    cpr_list = []
    try:
        cpr_list = json.loads(str(cpr_raw)) if cpr_raw else []
    except Exception:
        pass

    return {
        "part_number":               src.get("part_number", ""),
        "manufacturer":              MFR_FULL_NAMES.get(src.get("manufacturer", "").lower(), src.get("manufacturer", "")),
        "family":                    src.get("product_family", ""),
        "shaft_type":                src.get("shaft_type", ""),
        "shaft_bore_diameter_mm":    _safe_float(src.get("shaft_bore_diameter_mm")),
        "ip_rating":                 _safe_int(src.get("ip_rating")),
        "output_circuit_canonical":  src.get("output_circuit_canonical", ""),
        "connection_type_canonical": src.get("connection_type_canonical", ""),
        "connector_pins":            _safe_int(src.get("connector_pins")),
        "housing_diameter_mm":       _safe_float(src.get("housing_diameter_mm")),
        "supply_voltage_min_v":      _safe_float(src.get("supply_voltage_min_v")),
        "supply_voltage_max_v":      _safe_float(src.get("supply_voltage_max_v")),
        "operating_temp_max_c":      _safe_float(src.get("operating_temp_max_c")),
        "sensing_method":            src.get("sensing_method", ""),
        "cpr_values":                cpr_list,
        "shock_resistance_ms2":      _safe_float(src.get("shock_resistance_ms2")),
        "vibration_resistance_ms2":  _safe_float(src.get("vibration_resistance_ms2")),
        "shaft_load_radial_n":       _safe_float(src.get("shaft_load_radial_n")),
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

    product_url, url_type = get_product_url(manufacturer, part_number, family)

    # CPR overlap
    cpr_covered = _cpr_overlap(src_cpr, row)

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

    return {
        "rank":             rank,
        "part_number":      part_number,
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
        "t2":               t2,
        "t3":               t3,
        "extra":            extra,
    }