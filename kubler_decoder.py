"""
kubler_decoder.py
=================
Decode real Kübler order codes into Silver-queryable parameters.

Architecture
------------
Two parsing paths, dispatched from decode_kubler_order_code():

  Path A — Simple 4-segment codes (numeric prefix):
    "8.A020.351A.2048"  ->  prefix.family.opts.ppr
    Families: A020, A02H, KIS40, KIH40, 2400, 2420, Sendix 5xxx, 7xxx …

  Path B — K-series 5-segment codes (no numeric prefix):
    "K58I.OPP.01024.2S1C510.65RC2"         (standard)
    "K58I.OPRPP.01024.2S1C510.65RC2"        (Performance — PR in seg1)
    Families: K58I, K58I-PR, K80I

K58I solid vs hollow disambiguation:
  seg3[1:3] (version code) determines shaft type — NOT a map-first-wins fallback.
  Bore codes 06/08/10/12/1A/2A overlap between solid and hollow maps.
  Version codes: H1/H2/C1/C2 -> hollow_thru; S1/S3/etc. -> solid.

K58I vs K58I-PR disambiguation:
  seg1[1:3] == "PR" -> Performance encoder.
  interface_code = seg1[3:] instead of seg1[1:].
  silver_family overridden to "K58I-PR"; PR-specific decoder used.

Public API
----------
  decode_kubler_order_code(part_number) -> KublerDecodedSpec | None
  validate_decoders()  -> bool   (call at API startup)

AQB Solutions | May 2026
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Family aliases ─────────────────────────────────────────────────────────────
# Maps the token as it appears in the order code -> Silver product_family value.

KUBLER_FAMILY_ALIASES: dict[str, str] = {
    "A020": "A020",
    "A02H": "A02H",
    "5000": "Sendix 5000",
    "5006": "Sendix 5006",
    "5020": "Sendix 5020",
    "5026": "Sendix 5026",
    "5803": "5803",
    "5804": "5804",
    "5805": "5805",
    "5814": "Sendix 5814",
    "5823": "5823",
    "5824": "5824",
    "5825": "5825",
    "5834": "Sendix 5834",
    "5814FS2": "5814FS2",
    "5814FS3": "5814FS3",
    "5834FS2": "5834FS2",
    "5834FS3": "5834FS3",
    "7000": "Sendix 7000",
    "7020": "Sendix 7020",
    "7100": "Sendix 7100",
    "7120": "Sendix 7120",
    "KIS40": "KIS40",
    "KIH40": "KIH40",
    "KIS50": "KIS50",
    "KIH50": "KIH50",
    "2400": "2400",
    "2420": "2420",
    "2430": "2430",
    "2440": "2440",
    "KIS40": "KIS40",
    "KIH40": "KIH40",
    "KIS50": "KIS50",
    "KIH50": "KIH50",
    "K58I":    "K58I",
    "K58I-PR": "K58I-PR",
    "K80I":    "K80I",
    "K80I-PR": "K80I-PR",
    "H120":    "H120",
}

# K-series families (no numeric prefix — dispatched to Path B)
_K_SERIES_FAMILIES = {"K58I", "K80I"}

# Version codes in seg3[1:3] that indicate a hollow through-shaft variant.
# Cannot use "try shaft map first" — bore codes 06/08/10/12/1A/2A exist in both maps.
_HOLLOW_VERSION_CODES = {"H1", "H2", "C1", "C2"}


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class KublerDecodedSpec:
    """
    Result of decoding a real Kübler order code.

    decode_success = True  -> all hardware params decoded; fetch_part runs
                             the targeted Silver SQL query.
    decode_success = False -> partial (family + ppr known, no hardware params);
                             fetch_part falls back to PPR-aware family lookup
                             with the normalised silver_family name.
    """
    raw_code:      str
    family_token:  str
    silver_family: str

    # Hardware params -> targeted Silver SQL
    shaft_bore_mm:             Optional[float] = None
    shaft_type_override:       Optional[str]   = None   # "solid"/"hollow_thru"
    output_circuit_canonical:  Optional[str]   = None
    output_voltage_class:      Optional[str]   = None
    supply_voltage_min_v:      Optional[float] = None
    supply_voltage_max_v:      Optional[float] = None
    connection_type_canonical: Optional[str]   = None
    connector_pins:            Optional[int]   = None
    ip_rating:                 Optional[int]   = None

    # Specific PPR -> overrides cpr_values in matcher to [ppr]
    ppr: Optional[int] = None

    decode_success: bool = False
    decode_notes:   list = field(default_factory=list)


# ════════════════════════════════════════════════════════════════════════════════
# PATH A — Simple 4-segment families  (8.FAMILY.opts.ppr)
# ════════════════════════════════════════════════════════════════════════════════

# ── A020 maps ──────────────────────────────────────────────────────────────────
# Slot order verified from datasheet: a=flange, b=shaft_bore, c=output, d=connection
# (Bronze1 order_code_template has this WRONG — do not use it.)

_A020_BORE_MAP: dict[str, float] = {
    "C": 20.0, "6": 24.0, "5": 25.0, "3": 28.0,
    "A": 30.0, "2": 38.0, "B": 40.0, "1": 42.0, "4": 25.4,
}

_A020_OUTPUT_MAP: dict[str, dict] = {
    "1": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
    "4": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "2": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "5": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    "3": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "A": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    "8": {"output_circuit_canonical": "Sin/Cos",   "output_voltage_class": "analog",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
    "9": {"output_circuit_canonical": "Sin/Cos",   "output_voltage_class": "analog",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
}

_A020_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable", "connector_pins": None},
    "A": {"connection_type_canonical": "cable", "connector_pins": None},
    "2": {"connection_type_canonical": "M23",   "connector_pins": 12},
    "E": {"connection_type_canonical": "M12",   "connector_pins": 8},
}

# ── Sendix 5000 / 5020 shared output map ──────────────────────────────────────
# Output codes are identical between 5000 (shaft) and 5020 (hollow) — one shared map.
# Note: code "8" (push-pull without capacitor, US version) maps to same canonical
# as code "2" — both are Push-Pull universal.

_SENDIX_OUTPUT_MAP: dict[str, dict] = {
    "4": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
    "1": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    "2": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    "5": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "8": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    "3": {"output_circuit_canonical": "Open Collector", "output_voltage_class": "HTL",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
}

# ── Sendix 5000 (shaft) maps ───────────────────────────────────────────────────
# Slot order confirmed from datasheet image: a=flange, b=shaft, c=output, d=connection
# Flange encodes both housing_diameter_mm and ip_rating — handled by "flange" slot type.

_5000_FLANGE_MAP: dict[str, dict] = {
    # Standard European flanges
    "5": {"housing_diameter_mm": 50.8, "ip_rating": 67},   # synchro
    "6": {"housing_diameter_mm": 50.8, "ip_rating": 65},   # synchro
    "7": {"housing_diameter_mm": 58.0, "ip_rating": 67},   # clamping
    "8": {"housing_diameter_mm": 58.0, "ip_rating": 65},   # clamping
    "A": {"housing_diameter_mm": 58.0, "ip_rating": 67},   # synchro 58mm
    "B": {"housing_diameter_mm": 58.0, "ip_rating": 65},   # synchro 58mm
    "C": {"housing_diameter_mm": 63.5, "ip_rating": 67},   # square □63.5mm
    "D": {"housing_diameter_mm": 63.5, "ip_rating": 65},   # square □63.5mm
    "G": {"housing_diameter_mm": 115.0,"ip_rating": 67},   # Euro flange
    # US versions (footnote 3)
    "1": {"housing_diameter_mm": 50.8, "ip_rating": 67},   # servo ø50.8mm
    "2": {"housing_diameter_mm": 50.8, "ip_rating": 65},   # servo ø50.8mm
    "3": {"housing_diameter_mm": 52.3, "ip_rating": 67},   # square □52.3mm
    "4": {"housing_diameter_mm": 52.3, "ip_rating": 65},   # square □52.3mm
    "E": {"housing_diameter_mm": 63.5, "ip_rating": 67},   # servo ø63.5mm
    "F": {"housing_diameter_mm": 63.5, "ip_rating": 65},   # servo ø63.5mm
}

_5000_BORE_MAP: dict[str, float] = {
    "1": 6.0,
    "2": 6.35,    # ø 1/4 x 5/8"
    "6": 8.0,
    "3": 10.0,
    "4": 9.5,     # ø 3/8 x 5/8"
    "5": 12.0,
    "7": 6.35,    # ø 1/4 x 7/8" (US version)
    "8": 9.525,   # ø 3/8 x 7/8" (US version)
    "B": 11.0,    # with feather key (only with flange G)
}

_5000_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable",   "connector_pins": None},
    "2": {"connection_type_canonical": "cable",   "connector_pins": None},
    "P": {"connection_type_canonical": "M12",     "connector_pins": 5},
    "R": {"connection_type_canonical": "M12",     "connector_pins": 5},
    "3": {"connection_type_canonical": "M12",     "connector_pins": 8},
    "4": {"connection_type_canonical": "M12",     "connector_pins": 8},
    "7": {"connection_type_canonical": "M23",     "connector_pins": 12},
    "8": {"connection_type_canonical": "M23",     "connector_pins": 12},
    "Y": {"connection_type_canonical": "MS/MIL",  "connector_pins": 10},
    "W": {"connection_type_canonical": "MS/MIL",  "connector_pins": 7},
    "9": {"connection_type_canonical": "MS/MIL",  "connector_pins": 6},
    "L": {"connection_type_canonical": "M12",     "connector_pins": 8},
    "M": {"connection_type_canonical": "M23",     "connector_pins": 12},
    "N": {"connection_type_canonical": "D-Sub",   "connector_pins": 9},
}

# ── Sendix 5020 (hollow shaft) maps ───────────────────────────────────────────
# Flange encodes IP + housing. Spring element / torque stop flanges have
# housing_diameter_mm=None — no standard housing OD for these mounting types.

_5020_FLANGE_MAP: dict[str, dict] = {
    "1": {"housing_diameter_mm": None, "ip_rating": 67},   # spring element, long
    "2": {"housing_diameter_mm": None, "ip_rating": 65},   # spring element, long
    "3": {"housing_diameter_mm": None, "ip_rating": 67},   # torque stop, long
    "4": {"housing_diameter_mm": None, "ip_rating": 65},   # torque stop, long
    "7": {"housing_diameter_mm": 65.0, "ip_rating": 67},   # stator coupling ø65mm
    "8": {"housing_diameter_mm": 65.0, "ip_rating": 65},   # stator coupling ø65mm
    "C": {"housing_diameter_mm": 63.0, "ip_rating": 67},   # stator coupling ø63mm
    "D": {"housing_diameter_mm": 63.0, "ip_rating": 65},   # stator coupling ø63mm
    "5": {"housing_diameter_mm": 57.2, "ip_rating": 67},   # US version ø57.2mm
    "6": {"housing_diameter_mm": 57.2, "ip_rating": 65},   # US version ø57.2mm
}

_5020_BORE_MAP: dict[str, float] = {
    "1": 6.0,
    "2": 6.35,    # ø 1/4"
    "9": 8.0,     # NOTE: code "9" maps to 8mm — not a typo
    "4": 9.525,   # ø 3/8"
    "3": 10.0,
    "5": 12.0,
    "6": 12.7,    # ø 1/2"
    "A": 14.0,
    "8": 15.0,
    "7": 15.875,  # ø 5/8"
}

_5020_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable",   "connector_pins": None},
    "A": {"connection_type_canonical": "cable",   "connector_pins": None},
    "E": {"connection_type_canonical": "cable",   "connector_pins": None},
    "R": {"connection_type_canonical": "M12",     "connector_pins": 5},
    "2": {"connection_type_canonical": "M12",     "connector_pins": 8},
    "4": {"connection_type_canonical": "M23",     "connector_pins": 12},
    "6": {"connection_type_canonical": "MS/MIL",  "connector_pins": 7},
    "7": {"connection_type_canonical": "MS/MIL",  "connector_pins": 10},
    "H": {"connection_type_canonical": "M12",     "connector_pins": 8},
    "L": {"connection_type_canonical": "M12",     "connector_pins": 8},
    "M": {"connection_type_canonical": "M23",     "connector_pins": 12},
    "N": {"connection_type_canonical": "D-Sub",   "connector_pins": 9},
}


# ── Sendix 5804 / 5824 maps (SinCos output) ──────────────────────────────────
# SinCos (sine wave) output encoders. Both output codes are always "analog"
# class — JSON incorrectly labels them TTL/HTL; hardcoded correctly here.
# 5804: solid shaft, IP65 fixed.
# 5824: hollow shaft, bore+IP combined (same pattern as 5823), housing from flange.

_5804_FLANGE_MAP: dict[str, dict] = {
    "1": {"housing_diameter_mm": 58.0, "ip_rating": 65},   # clamping ø58mm
    "2": {"housing_diameter_mm": 58.0, "ip_rating": 65},   # synchro ø58mm
}

_5804_SHAFT_BORE_MAP: dict[str, float] = {
    "1": 6.0,     # ø6 x 10mm with flat
    "2": 10.0,    # ø10 x 20mm with flat
}

# Shared SinCos output map for 5804 and 5824.
# output_voltage_class always "analog" for SinCos — JSON TTL/HTL values are wrong.
_5804_5824_OUTPUT_MAP: dict[str, dict] = {
    "1": {"output_circuit_canonical": "Sin/Cos", "output_voltage_class": "analog",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
    "2": {"output_circuit_canonical": "Sin/Cos", "output_voltage_class": "analog",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
}

# 5804 connection map — same codes as 5803 (reusing)
_5804_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable", "connector_pins": None},   # axial 1m TPE
    "A": {"connection_type_canonical": "cable", "connector_pins": None},   # axial special
    "2": {"connection_type_canonical": "cable", "connector_pins": None},   # radial 1m TPE
    "B": {"connection_type_canonical": "cable", "connector_pins": None},   # radial special
    "3": {"connection_type_canonical": "M23",   "connector_pins": 12},     # axial M23 12-pin
    "5": {"connection_type_canonical": "M23",   "connector_pins": 12},     # radial M23 12-pin
}

# 5824 flange map — flanges 2&4 are blind hollow shaft in the datasheet, but Silver
# stores all 5824 rows as hollow_thru (same ETL behaviour as 5823). All set to hollow_thru.
# Housing values: 58mm for spring element (1&2), 65mm for stator coupling (3&4).
# Note: unlike 5823 which had housing=None for spring element, 5824 JSON has housing=58mm.
_5824_FLANGE_MAP: dict[str, dict] = {
    "1": {"housing_diameter_mm": 58.0, "ip_rating": None, "shaft_type": "hollow_thru"},
    "2": {"housing_diameter_mm": 58.0, "ip_rating": None, "shaft_type": "hollow_thru"},
    "3": {"housing_diameter_mm": 65.0, "ip_rating": None, "shaft_type": "hollow_thru"},
    "4": {"housing_diameter_mm": 65.0, "ip_rating": None, "shaft_type": "hollow_thru"},
}

# 5824 bore+IP map — identical to 5823 (same pattern, same codes)
# Reusing _5823_BORE_IP_MAP directly in the decoder entry.
# 5824 connection map — same as 5823 (1=cable, A=cable special, 2=M23 12-pin)
# Reusing _5823_CONNECTION_MAP directly in the decoder entry.


# ── Sendix 5805 / 5825 maps (high resolution) ────────────────────────────────
# High-resolution optical encoders (PPR range 6000-36000).
# Same structure as 5803/5823 respectively, with M12 connector options added.
# 5805 reuses 5803 flange/bore/output maps.
# 5825 reuses 5824 flange map, 5823 bore+IP map and output map.

# 5805 connection map — same as 5803 but adds M12 8-pin options (T=axial, G=radial)
_5805_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable",  "connector_pins": None},   # axial 1m PUR
    "A": {"connection_type_canonical": "cable",  "connector_pins": None},   # axial special
    "2": {"connection_type_canonical": "cable",  "connector_pins": None},   # radial 1m PUR
    "B": {"connection_type_canonical": "cable",  "connector_pins": None},   # radial special
    "3": {"connection_type_canonical": "M23",    "connector_pins": 12},     # axial M23 12-pin
    "5": {"connection_type_canonical": "M23",    "connector_pins": 12},     # radial M23 12-pin
    "T": {"connection_type_canonical": "M12",    "connector_pins": 8},      # axial M12 8-pin
    "G": {"connection_type_canonical": "M12",    "connector_pins": 8},      # radial M12 8-pin
}

# 5825 connection map — same as 5823 but adds M12 8-pin (C=radial)
_5825_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable",  "connector_pins": None},   # radial 1m PVC
    "A": {"connection_type_canonical": "cable",  "connector_pins": None},   # radial special PVC
    "2": {"connection_type_canonical": "M23",    "connector_pins": 12},     # radial M23 12-pin
    "C": {"connection_type_canonical": "M12",    "connector_pins": 8},      # radial M12 8-pin
}


# ── Sendix 5814FS2 / 5834FS2 maps (SinCos, safety SIL2/PLd) ──────────────────
# Safety-rated SinCos encoders. Flange encodes both housing and IP.
# 5814FS2: solid shaft, IP65/IP67 selectable via flange.
# 5834FS2: hollow/tapered shaft, bore K (tapered) = solid via shaft_bore_with_type.
# Output always "analog" — JSON says TTL/HTL (wrong). Reuses _5814_5834_OUTPUT_MAP.

_5814FS2_FLANGE_MAP: dict[str, dict] = {
    "1": {"housing_diameter_mm": 58.0, "ip_rating": 65},   # clamping IP65
    "3": {"housing_diameter_mm": 58.0, "ip_rating": 67},   # clamping IP67
}

_5814FS2_SHAFT_BORE_MAP: dict[str, float] = {
    "2": 10.0,    # 10x20mm with flat
    "A": 10.0,    # 10x20mm with feather key (same diameter)
}

_5814FS2_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable", "connector_pins": None},   # axial 1m PVC
    "A": {"connection_type_canonical": "cable", "connector_pins": None},   # axial special
    "2": {"connection_type_canonical": "cable", "connector_pins": None},   # radial 1m PVC
    "B": {"connection_type_canonical": "cable", "connector_pins": None},   # radial special
    "3": {"connection_type_canonical": "M23",   "connector_pins": 12},     # axial M23 12-pin
    "4": {"connection_type_canonical": "M23",   "connector_pins": 12},     # radial M23 12-pin
    "5": {"connection_type_canonical": "M12",   "connector_pins": 8},      # axial M12 8-pin
    "6": {"connection_type_canonical": "M12",   "connector_pins": 8},      # radial M12 8-pin
}

_5834FS2_FLANGE_MAP: dict[str, dict] = {
    "9": {"housing_diameter_mm": 58.0, "ip_rating": 65},   # torque stop FS flexible IP65
    "J": {"housing_diameter_mm": 58.0, "ip_rating": 67},   # torque stop FS flexible IP67
    "A": {"housing_diameter_mm": 58.0, "ip_rating": 65},   # torque stop FS rigid IP65
    "K": {"housing_diameter_mm": 58.0, "ip_rating": 67},   # torque stop FS rigid IP67
    "B": {"housing_diameter_mm": 63.0, "ip_rating": 65},   # stator coupling ø63mm IP65
    "L": {"housing_diameter_mm": 63.0, "ip_rating": 67},   # stator coupling ø63mm IP67
}

# 5834FS2 bore — K (tapered) = solid; all others = hollow_thru (shaft_bore_with_type slot)
_5834FS2_BORE_MAP: dict[str, dict] = {
    "3": {"diameter_mm": 10.0, "shaft_type": "hollow_thru"},
    "4": {"diameter_mm": 12.0, "shaft_type": "hollow_thru"},
    "5": {"diameter_mm": 14.0, "shaft_type": "hollow_thru"},
    "K": {"diameter_mm": 10.0, "shaft_type": "solid"},     # tapered shaft
}

_5834FS2_CONNECTION_MAP: dict[str, dict] = {
    "2": {"connection_type_canonical": "cable", "connector_pins": None},   # radial 1m PVC
    "B": {"connection_type_canonical": "cable", "connector_pins": None},   # radial special
    "E": {"connection_type_canonical": "cable", "connector_pins": None},   # tangential 1m PVC
    "F": {"connection_type_canonical": "cable", "connector_pins": None},   # tangential special
    "4": {"connection_type_canonical": "M23",   "connector_pins": 12},     # radial M23 12-pin
    "6": {"connection_type_canonical": "M12",   "connector_pins": 8},      # radial M12 8-pin
}


# ── Sendix 5814FS3 / 5834FS3 maps (SinCos, SIL3/PLe) ────────────────────────
# SIL3/PLe safety-rated SinCos encoders.
# 5814FS3: identical maps to 5814FS2 — all reused directly.
# 5834FS3: almost identical to 5834FS2, with one key difference:
#   bore K (tapered shaft) is hollow_thru in Silver for FS3 (not solid like FS2).
#   Silver confirms 192 rows all hollow_thru — use regular shaft_bore slot.
# Flange map reused from 5834FS2 — same codes, same housing/IP values.

_5834FS3_BORE_MAP: dict[str, float] = {
    "3": 10.0,    # through hollow shaft ø10mm
    "4": 12.0,    # through hollow shaft ø12mm
    "5": 14.0,    # through hollow shaft ø14mm
    "K": 10.0,    # tapered shaft ø10mm — Silver stores as hollow_thru for FS3
}


# ── Sendix 5814 / 5834 maps (SinCos, Sendix series) ──────────────────────────
# Silver families: "Sendix 5814" and "Sendix 5834" (both WITH "Sendix" prefix —
# unlike 5803/5804/5805 series which have no prefix).
# SinCos output — output_voltage_class always "analog" (JSON says TTL/HTL: wrong).
# 5814: extremely constrained — only 1 flange (code 1) and 1 shaft (code 2).
# 5834: bore code K (tapered shaft) = solid; all other bores = hollow_thru.

_5814_FLANGE_MAP: dict[str, dict] = {
    "1": {"housing_diameter_mm": 58.0, "ip_rating": 65},   # clamping ø58mm (only option)
}

_5814_SHAFT_BORE_MAP: dict[str, float] = {
    "2": 10.0,    # ø10 x 20mm with flat (only option)
}

# SinCos output map shared by 5814 and 5834.
# output_voltage_class always "analog" — JSON TTL/HTL values are wrong.
_5814_5834_OUTPUT_MAP: dict[str, dict] = {
    "1": {"output_circuit_canonical": "Sin/Cos", "output_voltage_class": "analog",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
    "2": {"output_circuit_canonical": "Sin/Cos", "output_voltage_class": "analog",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
}

_5814_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable", "connector_pins": None},   # axial 1m PVC
    "A": {"connection_type_canonical": "cable", "connector_pins": None},   # axial special
    "2": {"connection_type_canonical": "cable", "connector_pins": None},   # radial 1m PVC
    "B": {"connection_type_canonical": "cable", "connector_pins": None},   # radial special
    "5": {"connection_type_canonical": "M12",   "connector_pins": 8},      # axial M12 8-pin
    "6": {"connection_type_canonical": "M12",   "connector_pins": 8},      # radial M12 8-pin
}

_5834_FLANGE_MAP: dict[str, dict] = {
    "1": {"housing_diameter_mm": 58.0, "ip_rating": 65},   # spring element, long ø58mm
    "5": {"housing_diameter_mm": 63.0, "ip_rating": 65},   # stator coupling ø63mm
}

# 5834 bore map uses "shaft_bore_with_type" slot — bore K (tapered) is solid,
# all other bores are hollow_thru. Default shaft_type on decoder is hollow_thru.
_5834_BORE_MAP: dict[str, dict] = {
    "3": {"diameter_mm": 10.0,   "shaft_type": "hollow_thru"},
    "4": {"diameter_mm": 12.0,   "shaft_type": "hollow_thru"},
    "5": {"diameter_mm": 14.0,   "shaft_type": "hollow_thru"},
    "6": {"diameter_mm": 15.0,   "shaft_type": "hollow_thru"},
    "8": {"diameter_mm": 9.525,  "shaft_type": "hollow_thru"},   # ø3/8"
    "9": {"diameter_mm": 12.7,   "shaft_type": "hollow_thru"},   # ø1/2"
    "K": {"diameter_mm": 10.0,   "shaft_type": "solid"},         # tapered shaft (flange 5 only)
}

_5834_CONNECTION_MAP: dict[str, dict] = {
    "2": {"connection_type_canonical": "cable", "connector_pins": None},   # radial 1m PVC
    "B": {"connection_type_canonical": "cable", "connector_pins": None},   # radial special
    "E": {"connection_type_canonical": "cable", "connector_pins": None},   # tangential 1m PVC
    "F": {"connection_type_canonical": "cable", "connector_pins": None},   # tangential special
    "6": {"connection_type_canonical": "M12",   "connector_pins": 8},      # radial M12 8-pin
}


# ── Sendix 5006 / 5026 maps ───────────────────────────────────────────────────
# IP67 only (no IP65 variant). Connection is M12 8-pin only — hardcoded in
# order template (5006: slot d always "4"; 5026: slot d always "2").
# Output codes identical for both families: 2=PP/5-30V, 5=PP/10-30V, 4=RS422/5V.

_5006_FLANGE_MAP: dict[str, dict] = {
    "7": {"housing_diameter_mm": 58.0, "ip_rating": 67},   # clamping flange ø58mm
    "A": {"housing_diameter_mm": 58.0, "ip_rating": 67},   # synchro flange ø58mm
    "C": {"housing_diameter_mm": 63.5, "ip_rating": 67},   # square flange □63.5mm
}

_5006_SHAFT_BORE_MAP: dict[str, float] = {
    "1": 6.0,     # ø6 x 10mm with flat
    "3": 10.0,    # ø10 x 20mm
    "8": 9.525,   # ø3/8" x 7/8"
}

_5026_FLANGE_MAP: dict[str, dict] = {
    # Spring element (flange 1): no fixed housing OD — None used for consistency with 5020.
    # Stator coupling (flange C): ø63mm confirmed from datasheet and Silver housing_max=63.
    "1": {"housing_diameter_mm": None, "ip_rating": 67},   # spring element, long
    "C": {"housing_diameter_mm": 63.0, "ip_rating": 67},   # stator coupling ø63mm
}

_5026_HOLLOW_BORE_MAP: dict[str, float] = {
    "2": 6.35,    # ø1/4"
    "4": 9.525,   # ø3/8"
    "3": 10.0,    # ø10mm
    "5": 12.0,    # ø12mm
    "6": 12.7,    # ø1/2"
    "8": 15.0,    # ø15mm
}

# Output map shared by 5006 and 5026 — same codes, same canonical values
_5006_5026_OUTPUT_MAP: dict[str, dict] = {
    "2": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    "5": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "4": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
}

# 5006: connection is always "4" (radial M12 8-pin — only option)
_5006_CONNECTION_MAP: dict[str, dict] = {
    "4": {"connection_type_canonical": "M12", "connector_pins": 8},
}

# 5026: connection is always "2" (radial M12 8-pin — only option)
_5026_CONNECTION_MAP: dict[str, dict] = {
    "2": {"connection_type_canonical": "M12", "connector_pins": 8},
}


# ── Sendix 5803 / 5823 maps (high temperature) ────────────────────────────────
# High-temperature optical encoders (-20°C to +110°C).
# 5803: shaft, IP65 fixed. Output codes 4/5/6/7.
# 5823: hollow shaft, IP from bore code (odd=IP40, even=IP66).
#       Flange codes 1&3=hollow_thru, 2&4=hollow_blind — shaft_type set via flange.

_5803_FLANGE_MAP: dict[str, dict] = {
    "1": {"housing_diameter_mm": 58.0,  "ip_rating": 65},  # clamping ø58mm
    "2": {"housing_diameter_mm": 58.0,  "ip_rating": 65},  # synchro ø58mm
    "P": {"housing_diameter_mm": 63.5,  "ip_rating": 65},  # synchro ø63.5mm
    "M": {"housing_diameter_mm": 63.5,  "ip_rating": 65},  # square □63.5mm
}

_5803_SHAFT_BORE_MAP: dict[str, float] = {
    "1": 6.0,     # ø6 x 10mm with flat
    "2": 10.0,    # ø10 x 20mm with flat
    "P": 9.525,   # ø3/8" x 7/8" (only with flange M or P)
}

_5803_OUTPUT_MAP: dict[str, dict] = {
    "4": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
    "5": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "6": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "7": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
}

_5803_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable",   "connector_pins": None},  # axial 1m TPE
    "A": {"connection_type_canonical": "cable",   "connector_pins": None},  # axial special
    "2": {"connection_type_canonical": "cable",   "connector_pins": None},  # radial 1m TPE
    "B": {"connection_type_canonical": "cable",   "connector_pins": None},  # radial special
    "3": {"connection_type_canonical": "M23",     "connector_pins": 12},    # axial M23 12-pin
    "5": {"connection_type_canonical": "M23",     "connector_pins": 12},    # radial M23 12-pin
    "W": {"connection_type_canonical": "MS/MIL",  "connector_pins": 7},     # radial MIL 7-pin
    "Y": {"connection_type_canonical": "MS/MIL",  "connector_pins": 10},    # radial MIL 10-pin
}

# 5823: flange encodes shaft_type (hollow_thru vs hollow_blind) and housing.
# IP is NOT in flange — it comes from bore code (shaft_bore_with_ip slot).
_5823_FLANGE_MAP: dict[str, dict] = {
    # Silver ETL stored all 5823 rows as hollow_thru (Bronze1 JSON top-level shaft_type).
    # Flanges 2 & 4 are physically blind hollow shafts but Silver has no hollow_blind rows
    # for 5823 — all flanges must decode to hollow_thru to match Silver reality.
    # Future ETL correction would split blind/thru correctly at Silver generation time.
    "1": {"housing_diameter_mm": None, "ip_rating": None, "shaft_type": "hollow_thru"},
    "2": {"housing_diameter_mm": None, "ip_rating": None, "shaft_type": "hollow_thru"},
    "3": {"housing_diameter_mm": 65.0, "ip_rating": None, "shaft_type": "hollow_thru"},
    "4": {"housing_diameter_mm": 65.0, "ip_rating": None, "shaft_type": "hollow_thru"},
}

# Bore+IP combined map for 5823. Odd codes = IP40 (no seal), even codes = IP66 (with seal).
_5823_BORE_IP_MAP: dict[str, dict] = {
    "1": {"diameter_mm": 6.0,  "ip_rating": 40},
    "2": {"diameter_mm": 6.0,  "ip_rating": 66},
    "3": {"diameter_mm": 8.0,  "ip_rating": 40},
    "4": {"diameter_mm": 8.0,  "ip_rating": 66},
    "5": {"diameter_mm": 10.0, "ip_rating": 40},
    "6": {"diameter_mm": 10.0, "ip_rating": 66},
    "7": {"diameter_mm": 12.0, "ip_rating": 40},
    "8": {"diameter_mm": 12.0, "ip_rating": 66},
}

_5823_OUTPUT_MAP: dict[str, dict] = {
    "1": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
    "4": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "3": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "2": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
}

_5823_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable", "connector_pins": None},   # radial 1m TPE
    "A": {"connection_type_canonical": "cable", "connector_pins": None},   # radial special TPE
    "2": {"connection_type_canonical": "M23",   "connector_pins": 12},     # radial M23 12-pin
}


# ── Sendix 7000 / 7020 shared maps ────────────────────────────────────────────
# ATEX/IECEx zone 1/21 encoders. Both families are IP67 only — no IP65 variant.
# Connection is cable-only (no M12/M23/MIL options) for both families.
# Output codes identical to _SENDIX_OUTPUT_MAP (codes 1,2,4,5 only — no 3 or 8).

_7000_FLANGE_MAP: dict[str, dict] = {
    # Only one flange option for 7000 — always code "1" as shown in order template.
    "1": {"housing_diameter_mm": 70.0, "ip_rating": 67},   # clamping/synchro, IP67, ø70mm
}

_7000_BORE_MAP: dict[str, float] = {
    "2": 10.0,   # ø10 x 20mm with flat
    "1": 12.0,   # ø12 x 25mm with keyway for 4x4mm key
}

_7020_FLANGE_MAP: dict[str, dict] = {
    # Both options are IP67 only — no IP65 variant for 7020.
    # Flange "1" housing=70mm confirmed from JSON additional_specs.housing_diameter_mm.
    "1": {"housing_diameter_mm": 70.0, "ip_rating": 67},   # spring element, short
    "5": {"housing_diameter_mm": 65.0, "ip_rating": 67},   # stator coupling ø65mm
}

_7020_BORE_MAP: dict[str, float] = {
    "1": 12.0,   # blind hollow shaft ø12mm (insertion depth max 41.5mm)
    "2": 14.0,   # blind hollow shaft ø14mm (insertion depth max 41.5mm)
}

# Shared cable-only connection map (7000 and 7020 — no connector options available)
_7000_7020_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable", "connector_pins": None},  # axial 2m PUR
    "2": {"connection_type_canonical": "cable", "connector_pins": None},  # radial 2m PUR
    "A": {"connection_type_canonical": "cable", "connector_pins": None},  # axial >2m PUR
    "B": {"connection_type_canonical": "cable", "connector_pins": None},  # radial >2m PUR
}


# ── 2400-series maps (miniature encoders) ─────────────────────────────────────
# Miniature optical encoders. All IP65 only, cable-only connection.
# 2400/2420 use prefix "05"; 2430/2440 use prefix "8".
# 2420/2440 = hollow_blind (insertion depth max 14mm).
#
# Flange codes are shared across all four families.
# IP is always 65 — extracted from flange map for consistency with 5000/5020 pattern.

_2400_FLANGE_MAP: dict[str, dict] = {
    "1": {"housing_diameter_mm": 24.0, "ip_rating": 65},  # ø24mm [0.94"]
    "3": {"housing_diameter_mm": 28.0, "ip_rating": 65},  # ø28mm [1.10"]
    "2": {"housing_diameter_mm": 30.0, "ip_rating": 65},  # ø30mm [1.18"]
}

# 2420 and 2440 hollow shaft: only flange "1" (ø24mm) available
_2420_FLANGE_MAP: dict[str, dict] = {
    "1": {"housing_diameter_mm": 24.0, "ip_rating": 65},
}

_2400_SHAFT_BORE_MAP: dict[str, float] = {
    "1": 4.0,     # ø4 x 10mm
    "3": 5.0,     # ø5 x 10mm with flat
    "2": 6.0,     # ø6 x 10mm
    "4": 6.35,    # ø1/4" x 10mm with flat (2400 only, footnote 1)
    "6": 6.0,     # ø6 x 10mm with flat (2400 only, footnote 1)
}

# 2430 has no 1/4" bore — subset of above
_2430_SHAFT_BORE_MAP: dict[str, float] = {
    "1": 4.0,
    "3": 5.0,
    "2": 6.0,
}

_2420_HOLLOW_BORE_MAP: dict[str, float] = {
    "1": 4.0,     # ø4mm blind hollow shaft
    "2": 6.0,     # ø6mm blind hollow shaft
    "4": 6.35,    # ø1/4" blind hollow shaft (2420 only, footnote 1)
}

# 2440 has no 1/4" bore
_2440_HOLLOW_BORE_MAP: dict[str, float] = {
    "1": 4.0,
    "2": 6.0,
}

# Output map for 2400/2420 — PP variants 1-4 differ only in inverted signal
# (informational only, same canonical). Code 6 = RS422/5V.
_2400_OUTPUT_MAP: dict[str, dict] = {
    "1": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 24.0},
    "2": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 24.0},
    "3": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 8.0,  "supply_voltage_max_v": 30.0},
    "4": {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
          "supply_voltage_min_v": 8.0,  "supply_voltage_max_v": 30.0},
    "6": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
}

# 2430/2440 output map — RS422/5V only (code 6 hardcoded in order template)
_2430_OUTPUT_MAP: dict[str, dict] = {
    "6": {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
}

# Cable-only connection map shared across all 2400-series
_2400_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable", "connector_pins": None},  # axial 2m PVC
    "A": {"connection_type_canonical": "cable", "connector_pins": None},  # axial special length
    "2": {"connection_type_canonical": "cable", "connector_pins": None},  # radial 2m PVC
    "B": {"connection_type_canonical": "cable", "connector_pins": None},  # radial special length
}


# ── KIS40 maps ─────────────────────────────────────────────────────────────────
# Path A, 4-segment: 8.KIS40.abcd.PPPP[.P03][.XXXX]
# Slot order verified from datasheet image: a=flange, b=shaft_bore, c=output_type, d=connection_type
# Flange is always "1" (only option) — informational, no map entry needed.
# P03 suffix (special signal format) and cable length (.XXXX) are trailing segments;
# silently ignored by _parse_kubler_segments which only reads parts[0..3].
# IP is always IP64 — not encoded in order code, left as None in decoded spec.
# output_voltage_class: Open Collector -> "TTL" per canonical rules (overrides JSON "HTL").

_KIS40_BORE_MAP: dict[str, float] = {
    "3": 6.0,    # ø 6 × 12.5 mm, with flat
    "5": 6.35,   # ø 1/4" × 12.5 mm, with flat
    "6": 8.0,    # ø 8 × 12.5 mm, with flat
}

_KIS40_OUTPUT_MAP: dict[str, dict] = {
    "3": {"output_circuit_canonical": "Open Collector", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "4": {"output_circuit_canonical": "Push-Pull",      "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "6": {"output_circuit_canonical": "TTL RS422",      "output_voltage_class": "TTL",
          "supply_voltage_min_v":  5.0, "supply_voltage_max_v":  5.0},
    "7": {"output_circuit_canonical": "Open Collector", "output_voltage_class": "TTL",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "8": {"output_circuit_canonical": "Push-Pull",      "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "A": {"output_circuit_canonical": "Open Collector", "output_voltage_class": "TTL",
          "supply_voltage_min_v":  5.0, "supply_voltage_max_v": 30.0},
    "B": {"output_circuit_canonical": "Push-Pull",      "output_voltage_class": "universal",
          "supply_voltage_min_v":  5.0, "supply_voltage_max_v": 30.0},
    "C": {"output_circuit_canonical": "TTL RS422",      "output_voltage_class": "TTL",
          "supply_voltage_min_v":  5.0, "supply_voltage_max_v": 30.0},
}

_KIS40_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable", "connector_pins": None},  # axial 2m PVC
    "2": {"connection_type_canonical": "cable", "connector_pins": None},  # radial 2m PVC
    "4": {"connection_type_canonical": "M12",   "connector_pins": 5},     # radial 0.5m, M12 5-pin
    "6": {"connection_type_canonical": "M12",   "connector_pins": 8},     # radial 0.5m, M12 8-pin
    "A": {"connection_type_canonical": "cable", "connector_pins": None},  # axial special length PVC
    "B": {"connection_type_canonical": "cable", "connector_pins": None},  # radial special length PVC
}

# ── KIH40 maps ─────────────────────────────────────────────────────────────────
# Slot order verified from datasheet image: a=flange, b=shaft_bore, c=output_type, d=connection_type
# shaft_type = "hollow_blind" (blind bore, insertion depth max 18 mm).
# Output and connection maps are identical to KIS40 — shared directly.
# IP is always IP64 — not encoded in order code, left as None in decoded spec.

_KIH40_BORE_MAP: dict[str, float] = {
    "2": 6.0,    # ø 6 mm blind hollow shaft
    "4": 8.0,    # ø 8 mm blind hollow shaft
    "3": 6.35,   # ø 1/4" blind hollow shaft
}

# ── KIS50 maps ─────────────────────────────────────────────────────────────────
# Path A, 4-segment: 8.KIS50.abcd.PPPP
# Slot order: a=flange, b=shaft_bore, c=output_type, d=connection_type
# shaft_type = "solid" (stainless steel shaft with flat, ø 58 mm zinc die-cast housing)
# IP65 fixed for all flange options — applied via fixed_specs.
# output_type map is identical to KIH50 — shared directly (_KIH50_OUTPUT_MAP).
# Note: bore code "8"=9.525mm and connection code "8"=M23-radial are different slots — no conflict.

_KIS50_BORE_MAP: dict[str, float] = {
    "1":  6.0,    # ø 6 × 10 mm, with flat
    "6":  8.0,    # ø 8 × 15 mm, with flat
    "3": 10.0,    # ø 10 × 20 mm, with flat
    "D": 10.0,    # ø 10 × 20 mm, on both sides (measuring wheel use) — same diameter
    "5": 12.0,    # ø 12 × 20 mm, with flat
    "8":  9.525,  # ø 3/8 × 7/8"
}

_KIS50_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable", "connector_pins": None},  # axial 1m PVC
    "2": {"connection_type_canonical": "cable", "connector_pins": None},  # radial 1m PVC
    "P": {"connection_type_canonical": "M12",   "connector_pins": 5},     # axial M12 5-pin
    "R": {"connection_type_canonical": "M12",   "connector_pins": 5},     # radial M12 5-pin
    "3": {"connection_type_canonical": "M12",   "connector_pins": 8},     # axial M12 8-pin
    "4": {"connection_type_canonical": "M12",   "connector_pins": 8},     # radial M12 8-pin
    "7": {"connection_type_canonical": "M23",   "connector_pins": 12},    # axial M23 12-pin
    "8": {"connection_type_canonical": "M23",   "connector_pins": 12},    # radial M23 12-pin
}

# ── KIH50 maps ─────────────────────────────────────────────────────────────────
# Path A, 4-segment: 8.KIH50.abcd.PPPP
# Slot order: a=flange, b=shaft_bore, c=output_type, d=connection_type
# shaft_type = "hollow_thru" (through hollow shaft, Sendix Base, ø 58 mm housing)
# IP65 is fixed for all flange options — not a separate axis. Applied via fixed_specs.
# output_voltage_class: Open Collector -> "TTL" per canonical rules (overrides JSON "HTL").

_KIH50_BORE_MAP: dict[str, float] = {
    "9":  8.0,    # ø 8 mm through hollow shaft
    "4":  9.52,   # ø 3/8" (9.52 mm) through hollow shaft
    "3": 10.0,    # ø 10 mm through hollow shaft
    "5": 12.0,    # ø 12 mm through hollow shaft
    "6": 12.75,   # ø 1/2" (12.75 mm) through hollow shaft
    "A": 14.0,    # ø 14 mm through hollow shaft
    "8": 15.0,    # ø 15 mm through hollow shaft
}

_KIH50_OUTPUT_MAP: dict[str, dict] = {
    "4": {"output_circuit_canonical": "TTL RS422",      "output_voltage_class": "TTL",
          "supply_voltage_min_v":  5.0, "supply_voltage_max_v":  5.0},
    "1": {"output_circuit_canonical": "TTL RS422",      "output_voltage_class": "TTL",
          "supply_voltage_min_v":  5.0, "supply_voltage_max_v": 30.0},
    "2": {"output_circuit_canonical": "Push-Pull",      "output_voltage_class": "universal",
          "supply_voltage_min_v":  5.0, "supply_voltage_max_v": 30.0},
    "5": {"output_circuit_canonical": "Push-Pull",      "output_voltage_class": "universal",
          "supply_voltage_min_v": 10.0, "supply_voltage_max_v": 30.0},
    "3": {"output_circuit_canonical": "Open Collector", "output_voltage_class": "TTL",
          "supply_voltage_min_v":  5.0, "supply_voltage_max_v": 30.0},
}

_KIH50_CONNECTION_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable", "connector_pins": None},  # radial 1m PVC
    "R": {"connection_type_canonical": "M12",   "connector_pins": 5},     # radial M12 5-pin
    "2": {"connection_type_canonical": "M12",   "connector_pins": 8},     # radial M12 8-pin
    "4": {"connection_type_canonical": "M23",   "connector_pins": 12},    # radial M23 12-pin
    "E": {"connection_type_canonical": "cable", "connector_pins": None},  # tangential 1m PVC
}

# ── Path A decoder registry ────────────────────────────────────────────────────
# "slots": positional order in the opts segment (from datasheet, NOT Bronze1 template)
# "flange" and similar informational axes are listed in slots but omitted from maps.

# ── Path A decoder registry ────────────────────────────────────────────────────

KUBLER_DECODERS: dict[str, dict] = {
    "A020": {
        "prefix":     "8",
        "shaft_type": "hollow_thru",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "shaft_bore":      _A020_BORE_MAP,
            "output_type":     _A020_OUTPUT_MAP,
            "connection_type": _A020_CONNECTION_MAP,
        },
        "sample":   "8.A020.351A.2048",
        "expected": {
            "shaft_bore_mm":             25.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ppr":                       2048,
        },
    },
    "KIS40": {
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        # "flange" has no map entry — always code "1", informational only.
        "maps": {
            "shaft_bore":      _KIS40_BORE_MAP,
            "output_type":     _KIS40_OUTPUT_MAP,
            "connection_type": _KIS40_CONNECTION_MAP,
        },
        # Sample from JSON stock_types; positions verified manually:
        #   opts[0]='1' -> flange (informational)
        #   opts[1]='3' -> shaft bore 6.0 mm
        #   opts[2]='4' -> Push-Pull / 10–30 V
        #   opts[3]='2' -> cable (radial 2 m PVC)
        "sample":   "8.KIS40.1342.1024",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      10.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ppr":                       1024,
        },
    },
    "KIH40": {
        "prefix":     "8",
        "shaft_type": "hollow_blind",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        # "flange" has no map entry — codes 2/5 are informational (spring element / stator coupling).
        # output_type and connection_type maps are identical to KIS40 — shared directly.
        "maps": {
            "shaft_bore":      _KIH40_BORE_MAP,
            "output_type":     _KIS40_OUTPUT_MAP,
            "connection_type": _KIS40_CONNECTION_MAP,
        },
        # Sample from JSON stock_types; positions verified manually:
        #   opts[0]='2' -> flange: spring element long (informational)
        #   opts[1]='4' -> bore 8.0 mm hollow_blind
        #   opts[2]='4' -> Push-Pull / 10–30 V
        #   opts[3]='2' -> cable (radial 2 m PVC)
        "sample":   "8.KIH40.2442.1024",
        "expected": {
            "shaft_bore_mm":             8.0,
            "shaft_type_override":       "hollow_blind",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      10.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ppr":                       1024,
        },
    },
    "KIS50": {
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        # "flange" has no map entry — codes 8/B are informational (clamping / synchro).
        # output_type map identical to KIH50 — shared directly.
        "maps": {
            "shaft_bore":      _KIS50_BORE_MAP,
            "output_type":     _KIH50_OUTPUT_MAP,
            "connection_type": _KIS50_CONNECTION_MAP,
        },
        # IP always 65 — encoded in flange type but fixed for all KIS50 variants.
        "fixed_specs": {"ip_rating": 65},
        # Sample verified manually:
        #   opts[0]='8' -> flange: clamping (informational, IP65)
        #   opts[1]='3' -> bore 10.0 mm solid
        #   opts[2]='1' -> RS422 / 5...30 V DC
        #   opts[3]='4' -> radial M12 8-pin connector
        "sample":   "8.KIS50.8314.1024",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "M12",
            "connector_pins":            8,
            "ip_rating":                 65,
            "ppr":                       1024,
        },
    },
    "KIH50": {
        "prefix":     "8",
        "shaft_type": "hollow_thru",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        # "flange" has no map entry — codes 2/4/D are informational (spring element /
        # torque stop / stator coupling). All three flanges give IP65.
        # IP65 is applied as a fixed spec (not slot-encoded).
        "maps": {
            "shaft_bore":      _KIH50_BORE_MAP,
            "output_type":     _KIH50_OUTPUT_MAP,
            "connection_type": _KIH50_CONNECTION_MAP,
        },
        # IP always 65 — encoded in flange type but fixed for all KIH50 variants.
        "fixed_specs": {"ip_rating": 65},
        # Sample constructed from expansion axes; positions verified manually:
        #   opts[0]='2' -> flange: spring element long (informational, IP65)
        #   opts[1]='3' -> bore 10.0 mm hollow_thru
        #   opts[2]='1' -> RS422 / 5...30 V DC
        #   opts[3]='2' -> radial M12 8-pin connector
        "sample":   "8.KIH50.2312.1024",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "M12",
            "connector_pins":            8,
            "ip_rating":                 65,
            "ppr":                       1024,
        },
    },

    "5000": {
        # Sendix 5000 — solid shaft, IP embedded in flange code (slot a).
        # Silver family: "Sendix 5000" (confirmed, 8910 rows).
        # slot order: a=flange, b=shaft_bore, c=output_type, d=connection_type
        # Real sample: 8.5000.7344.1024 (flange=7->58mm/IP67, bore=3->10mm, RS422/5V, M12-8)
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5000_FLANGE_MAP,
            "shaft_bore":      _5000_BORE_MAP,
            "output_type":     _SENDIX_OUTPUT_MAP,
            "connection_type": _5000_CONNECTION_MAP,
        },
        "sample":   "8.5000.7344.1024",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "M12",
            "connector_pins":            8,
            "ip_rating":                 67,
            "ppr":                       1024,
        },
    },
    "5020": {
        # Sendix 5020 — hollow through-shaft, IP embedded in flange code (slot a).
        # Silver family: "Sendix 5020" (confirmed, 4800 rows, hollow_thru).
        # slot order: a=flange, b=shaft_bore, c=output_type, d=connection_type
        # Spring element / torque stop flanges (1-4) have housing_diameter_mm=None.
        # Real sample: 8.5020.3341.1024 (flange=3->IP67/no_housing, bore=3->10mm, RS422/5V, cable)
        "prefix":     "8",
        "shaft_type": "hollow_thru",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5020_FLANGE_MAP,
            "shaft_bore":      _5020_BORE_MAP,
            "output_type":     _SENDIX_OUTPUT_MAP,
            "connection_type": _5020_CONNECTION_MAP,
        },
        "sample":   "8.5020.3341.1024",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 67,
            "ppr":                       1024,
        },
    },
    "5814FS3": {
        # Sendix 5814FS3 — solid shaft, SinCos, SIL3/PLe safety.
        # Silver: "5814FS3" (confirmed, 48 rows, solid, IP65+67, housing 58mm).
        # Identical to 5814FS2 in all map respects — reuse all FS2 maps.
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5814FS2_FLANGE_MAP,        # identical — reuse
            "shaft_bore":      _5814FS2_SHAFT_BORE_MAP,    # identical — reuse
            "output_type":     _5814_5834_OUTPUT_MAP,      # identical — reuse
            "connection_type": _5814FS2_CONNECTION_MAP,    # identical — reuse
        },
        "sample":   "8.5814FS3.122A.2048",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "Sin/Cos",
            "output_voltage_class":      "analog",
            "supply_voltage_min_v":      10.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       2048,
        },
    },
    "5834FS3": {
        # Sendix 5834FS3 — hollow shaft, SinCos, SIL3/PLe safety.
        # Silver: "5834FS3" (confirmed, 192 rows, ALL hollow_thru, IP65+67, housing 58-63mm).
        # Key difference from 5834FS2: bore K (tapered) is hollow_thru in Silver for FS3.
        # Uses regular shaft_bore slot (not shaft_bore_with_type) — no solid rows.
        # Reuses 5834FS2 flange, output, and connection maps.
        "prefix":     "8",
        "shaft_type": "hollow_thru",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5834FS2_FLANGE_MAP,        # identical — reuse
            "shaft_bore":      _5834FS3_BORE_MAP,          # new — K is hollow_thru
            "output_type":     _5814_5834_OUTPUT_MAP,      # identical — reuse
            "connection_type": _5834FS2_CONNECTION_MAP,    # identical — reuse
        },
        "sample":   "8.5834FS3.B42B.2048",
        "expected": {
            "shaft_bore_mm":             12.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "Sin/Cos",
            "output_voltage_class":      "analog",
            "supply_voltage_min_v":      10.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       2048,
        },
    },
    "5814FS2": {
        # Sendix 5814FS2 — solid shaft, SinCos, safety SIL2/PLd.
        # Silver: "5814FS2" (confirmed, 48 rows, solid, IP65+67, housing 58mm).
        # Flange encodes IP: code 1=IP65, code 3=IP67 (unlike 5814 which is always IP65).
        # Shaft A (feather key) has same diameter as shaft 2 (flat) — both 10mm.
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5814FS2_FLANGE_MAP,
            "shaft_bore":      _5814FS2_SHAFT_BORE_MAP,
            "output_type":     _5814_5834_OUTPUT_MAP,    # identical — reuse
            "connection_type": _5814FS2_CONNECTION_MAP,
        },
        "sample":   "8.5814FS2.122A.2048",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "Sin/Cos",
            "output_voltage_class":      "analog",
            "supply_voltage_min_v":      10.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       2048,
        },
    },
    "5834FS2": {
        # Sendix 5834FS2 — hollow/tapered shaft, SinCos, safety SIL2/PLd.
        # Silver: "5834FS2" (confirmed, 144 hollow_thru + 48 solid rows, IP65+67).
        # Flange encodes housing+IP (6 codes). Bore K (tapered) = solid via shaft_bore_with_type.
        "prefix":     "8",
        "shaft_type": "hollow_thru",   # default; K bore overrides to "solid"
        "slots":      ["flange", "shaft_bore_with_type", "output_type", "connection_type"],
        "maps": {
            "flange":              _5834FS2_FLANGE_MAP,
            "shaft_bore_with_type": _5834FS2_BORE_MAP,
            "output_type":         _5814_5834_OUTPUT_MAP,   # identical — reuse
            "connection_type":     _5834FS2_CONNECTION_MAP,
        },
        "sample":   "8.5834FS2.B42B.2048",
        "expected": {
            "shaft_bore_mm":             12.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "Sin/Cos",
            "output_voltage_class":      "analog",
            "supply_voltage_min_v":      10.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       2048,
        },
    },
    "5814": {
        # Sendix 5814 — solid shaft, SinCos, Sendix series.
        # Silver: "Sendix 5814" (WITH prefix, 8 rows, solid, IP65, housing 58mm).
        # Extremely constrained: only flange 1 (58mm) and shaft 2 (10mm).
        # Order template shows a=1 and b=2 hardcoded: 8.5814.12XX.XXXX.
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5814_FLANGE_MAP,
            "shaft_bore":      _5814_SHAFT_BORE_MAP,
            "output_type":     _5814_5834_OUTPUT_MAP,
            "connection_type": _5814_CONNECTION_MAP,
        },
        "sample":   "8.5814.122A.2048",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "Sin/Cos",
            "output_voltage_class":      "analog",
            "supply_voltage_min_v":      10.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       2048,
        },
    },
    "5834": {
        # Sendix 5834 — hollow/tapered shaft, SinCos, Sendix series.
        # Silver: "Sendix 5834" (WITH prefix, 84 hollow_thru + 12 solid rows).
        # Bore code K (tapered shaft) = solid; all other bores = hollow_thru.
        # shaft_bore_with_type slot resolves this automatically.
        "prefix":     "8",
        "shaft_type": "hollow_thru",   # default; K bore overrides to "solid"
        "slots":      ["flange", "shaft_bore_with_type", "output_type", "connection_type"],
        "maps": {
            "flange":              _5834_FLANGE_MAP,
            "shaft_bore_with_type": _5834_BORE_MAP,
            "output_type":         _5814_5834_OUTPUT_MAP,
            "connection_type":     _5834_CONNECTION_MAP,
        },
        "sample":   "8.5834.142B.2048",
        "expected": {
            "shaft_bore_mm":             12.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "Sin/Cos",
            "output_voltage_class":      "analog",
            "supply_voltage_min_v":      10.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       2048,
        },
    },
    "5804": {
        # Sendix 5804 — solid shaft, SinCos output. IP65 fixed.
        # Silver: "5804" (confirmed, 32 rows, solid, IP65, housing 58mm).
        # output_voltage_class always "analog" for SinCos — JSON says TTL/HTL (wrong).
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5804_FLANGE_MAP,
            "shaft_bore":      _5804_SHAFT_BORE_MAP,
            "output_type":     _5804_5824_OUTPUT_MAP,
            "connection_type": _5804_CONNECTION_MAP,
        },
        "sample":   "8.5804.111A.0512",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "Sin/Cos",
            "output_voltage_class":      "analog",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       512,
        },
    },
    "5824": {
        # Sendix 5824 — hollow shaft, SinCos output.
        # Silver: "5824" (confirmed, 256 rows, hollow_thru, IP40-66, housing 58-65mm).
        # Bore slot "shaft_bore_with_ip": same bore+IP map as 5823.
        # Flange encodes shaft_type (all hollow_thru per Silver) and housing.
        # output_voltage_class always "analog" for SinCos.
        "prefix":     "8",
        "shaft_type": "hollow_thru",
        "slots":      ["flange", "shaft_bore_with_ip", "output_type", "connection_type"],
        "maps": {
            "flange":             _5824_FLANGE_MAP,
            "shaft_bore_with_ip": _5823_BORE_IP_MAP,   # identical — reuse
            "output_type":        _5804_5824_OUTPUT_MAP,
            "connection_type":    _5823_CONNECTION_MAP, # identical — reuse
        },
        "sample":   "8.5824.111A.0512",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "Sin/Cos",
            "output_voltage_class":      "analog",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 40,
            "ppr":                       512,
        },
    },
    "5805": {
        # Sendix 5805 — solid shaft, high resolution (6000-36000 PPR).
        # Silver: "5805" (confirmed, 96 rows, solid, IP65, housing 58mm).
        # Reuses 5803 flange/bore/output maps. Connection adds M12 options T and G.
        # PPR is 5-digit zero-padded in order code (e.g. 06000, 18000, 36000).
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5803_FLANGE_MAP,        # identical — reuse
            "shaft_bore":      _5803_SHAFT_BORE_MAP,    # identical — reuse
            "output_type":     _5803_OUTPUT_MAP,        # identical — reuse
            "connection_type": _5805_CONNECTION_MAP,
        },
        "sample":   "8.5805.114A.6000",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       6000,
        },
    },
    "5825": {
        # Sendix 5825 — hollow shaft, high resolution (6000-36000 PPR).
        # Silver: "5825" (confirmed, 768 rows, hollow_thru, IP40-66, housing 58-65mm).
        # Reuses 5824 flange map, 5823 bore+IP map and output map.
        # Connection adds M12 option C (radial M12 8-pin).
        # NOTE: output code "4" on 5825 = RS422/10-30V (not 5V as on 5805).
        "prefix":     "8",
        "shaft_type": "hollow_thru",
        "slots":      ["flange", "shaft_bore_with_ip", "output_type", "connection_type"],
        "maps": {
            "flange":             _5824_FLANGE_MAP,     # identical — reuse
            "shaft_bore_with_ip": _5823_BORE_IP_MAP,   # identical — reuse
            "output_type":        _5823_OUTPUT_MAP,    # identical — reuse
            "connection_type":    _5825_CONNECTION_MAP,
        },
        "sample":   "8.5825.114A.6000",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      10.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 40,
            "ppr":                       6000,
        },
    },
    "5803": {
        # Sendix 5803 — solid shaft, high-temp (-20°C to +110°C). IP65 fixed.
        # Silver family: "Sendix 5803" (in KUBLER_FAMILY_ALIASES as "5803"->"Sendix 5803").
        # Same slot structure as 5006. Output codes 4/5/6/7 (different from 5006's 2/4/5).
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5803_FLANGE_MAP,
            "shaft_bore":      _5803_SHAFT_BORE_MAP,
            "output_type":     _5803_OUTPUT_MAP,
            "connection_type": _5803_CONNECTION_MAP,
        },
        "sample":   "8.5803.114A.0100",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       100,
        },
    },
    "5823": {
        # Sendix 5823 — hollow shaft, high-temp. Two new decode patterns:
        #   1. Flange encodes shaft_type: 1&3=hollow_thru, 2&4=hollow_blind.
        #   2. Bore slot "shaft_bore_with_ip": encodes both diameter and IP rating.
        #      Odd bore codes=IP40 (no seal), even=IP66 (with seal).
        # Silver family: "Sendix 5823".
        # Default shaft_type set to hollow_thru; overridden by flange slot during decode.
        "prefix":     "8",
        "shaft_type": "hollow_thru",
        "slots":      ["flange", "shaft_bore_with_ip", "output_type", "connection_type"],
        "maps": {
            "flange":           _5823_FLANGE_MAP,
            "shaft_bore_with_ip": _5823_BORE_IP_MAP,
            "output_type":      _5823_OUTPUT_MAP,
            "connection_type":  _5823_CONNECTION_MAP,
        },
        "sample":   "8.5823.114A.0100",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      10.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 40,
            "ppr":                       100,
        },
    },
    "5006": {
        # Sendix 5006 — solid shaft, IP67 only. M12 8-pin only (conn code "4" hardcoded).
        # Silver: "Sendix 5006" (confirmed, 27 rows, solid, IP67, housing 58-63.5mm).
        # slot order: a=flange, b=shaft_bore, c=output_type, d=connection_type
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5006_FLANGE_MAP,
            "shaft_bore":      _5006_SHAFT_BORE_MAP,
            "output_type":     _5006_5026_OUTPUT_MAP,
            "connection_type": _5006_CONNECTION_MAP,
        },
        "sample":   "8.5006.7324.1024",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "M12",
            "connector_pins":            8,
            "ip_rating":                 67,
            "ppr":                       1024,
        },
    },
    "5026": {
        # Sendix 5026 — hollow through-shaft, IP67 only. M12 8-pin only (conn code "2" hardcoded).
        # Silver: "Sendix 5026" (confirmed, 36 rows, hollow_thru, IP67, housing 50-63mm).
        # Spring element flange (1): housing=None; stator coupling (C): housing=63mm.
        # slot order: a=flange, b=shaft_bore, c=output_type, d=connection_type
        "prefix":     "8",
        "shaft_type": "hollow_thru",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _5026_FLANGE_MAP,
            "shaft_bore":      _5026_HOLLOW_BORE_MAP,
            "output_type":     _5006_5026_OUTPUT_MAP,
            "connection_type": _5026_CONNECTION_MAP,
        },
        "sample":   "8.5026.1822.1024",
        "expected": {
            "shaft_bore_mm":             15.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "M12",
            "connector_pins":            8,
            "ip_rating":                 67,
            "ppr":                       1024,
        },
    },
    "7000": {
        # Sendix 7000 — solid shaft, ATEX/IECEx zone 1/21.
        # Silver family: "Sendix 7000" (confirmed, 16 rows, solid, IP67 only).
        # Only ONE flange option (code "1" — hardcoded in order template as 8.7000.1XXX).
        # Cable-only connection — no connector variants.
        # slot order: a=flange, b=shaft_bore, c=output_type, d=connection_type
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _7000_FLANGE_MAP,
            "shaft_bore":      _7000_BORE_MAP,
            "output_type":     _SENDIX_OUTPUT_MAP,
            "connection_type": _7000_7020_CONNECTION_MAP,
        },
        "sample":   "8.7000.124A.1024",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 67,
            "ppr":                       1024,
        },
    },
    "7020": {
        # Sendix 7020 — blind hollow shaft, ATEX/IECEx zone 1/21.
        # Silver family: "Sendix 7020" (confirmed, 32 rows, hollow_blind, IP67 only).
        # shaft_type = "hollow_blind" — T1 bore tolerance applies (>1mm mismatch = hard stop).
        # Only 2 bore sizes: 12mm and 14mm.
        # Cable-only connection — no connector variants.
        # slot order: a=flange, b=shaft_bore, c=output_type, d=connection_type
        "prefix":     "8",
        "shaft_type": "hollow_blind",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _7020_FLANGE_MAP,
            "shaft_bore":      _7020_BORE_MAP,
            "output_type":     _SENDIX_OUTPUT_MAP,
            "connection_type": _7000_7020_CONNECTION_MAP,
        },
        "sample":   "8.7020.124A.2048",
        "expected": {
            "shaft_bore_mm":             14.0,
            "shaft_type_override":       "hollow_blind",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 67,
            "ppr":                       2048,
        },
    },
    "2400": {
        # Miniature encoder, solid shaft. Prefix "05" (not "8").
        # Silver: "2400", solid, IP65 only, housing 24-30mm (confirmed).
        "prefix":     "05",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _2400_FLANGE_MAP,
            "shaft_bore":      _2400_SHAFT_BORE_MAP,
            "output_type":     _2400_OUTPUT_MAP,
            "connection_type": _2400_CONNECTION_MAP,
        },
        "sample":   "05.2400.122A.1024",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      24.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       1024,
        },
    },
    "2420": {
        # Miniature encoder, blind hollow shaft. Prefix "05".
        # Silver: "2420", hollow_blind, IP65 only, housing 24mm only (confirmed).
        # Only flange "1" (ø24mm) available.
        "prefix":     "05",
        "shaft_type": "hollow_blind",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _2420_FLANGE_MAP,
            "shaft_bore":      _2420_HOLLOW_BORE_MAP,
            "output_type":     _2400_OUTPUT_MAP,
            "connection_type": _2400_CONNECTION_MAP,
        },
        "sample":   "05.2420.122A.1024",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "hollow_blind",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      24.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       1024,
        },
    },
    "2430": {
        # Miniature encoder, solid shaft, RS422 only. Prefix "8".
        # Silver: "2430", solid, IP65 only, housing 24-30mm (confirmed).
        # Output code always "6" (RS422/5V) — hardcoded in order template.
        "prefix":     "8",
        "shaft_type": "solid",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _2400_FLANGE_MAP,
            "shaft_bore":      _2430_SHAFT_BORE_MAP,
            "output_type":     _2430_OUTPUT_MAP,
            "connection_type": _2400_CONNECTION_MAP,
        },
        "sample":   "8.2430.126A.0256",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       256,
        },
    },
    "2440": {
        # Miniature encoder, blind hollow shaft, RS422 only. Prefix "8".
        # Silver: "2440", hollow_blind, IP65 only, housing 24mm only (confirmed).
        # Output code always "6" (RS422/5V) — hardcoded in order template.
        "prefix":     "8",
        "shaft_type": "hollow_blind",
        "slots":      ["flange", "shaft_bore", "output_type", "connection_type"],
        "maps": {
            "flange":          _2420_FLANGE_MAP,
            "shaft_bore":      _2440_HOLLOW_BORE_MAP,
            "output_type":     _2430_OUTPUT_MAP,
            "connection_type": _2400_CONNECTION_MAP,
        },
        "sample":   "8.2440.126A.0256",
        "expected": {
            "shaft_bore_mm":             6.0,
            "shaft_type_override":       "hollow_blind",
            "output_circuit_canonical":  "TTL RS422",
            "output_voltage_class":      "TTL",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      5.0,
            "connection_type_canonical": "cable",
            "connector_pins":            None,
            "ip_rating":                 65,
            "ppr":                       256,
        },
    },
    # Additional simple families (KIS40, KIH40, etc.) added here
    # as datasheets are confirmed.
}


def _parse_kubler_segments(part_number: str
                           ) -> "tuple[str|None, str|None, str|None, int|None]":
    """
    Split a simple Kübler code (numeric-prefix) into (prefix, family_token, opts, ppr).
    Returns (None,None,None,None) for K-series or unrecognised formats.
    """
    parts = [p for p in part_number.strip().split(".") if p]
    if len(parts) < 4:
        return None, None, None, None
    if not parts[0].isdigit():
        return None, None, None, None   # K-series starts with alpha

    prefix       = parts[0]
    family_token = parts[1]
    opts         = parts[2]
    ppr_str      = parts[3]

    ppr: Optional[int] = None
    if re.match(r"^\d{1,5}$", ppr_str):
        val = int(ppr_str)
        if 1 <= val <= 65536:
            ppr = val

    return prefix, family_token, opts, ppr


def _decode_simple_family(part_number: str,
                          family_token: str, opts: str,
                          ppr: Optional[int]) -> KublerDecodedSpec:
    """Decode a Path-A (simple 4-segment) Kübler order code."""
    silver_family = KUBLER_FAMILY_ALIASES.get(family_token, family_token)
    spec = KublerDecodedSpec(
        raw_code=part_number,
        family_token=family_token,
        silver_family=silver_family,
        ppr=ppr,
    )

    decoder = KUBLER_DECODERS.get(family_token)
    if decoder is None:
        spec.decode_success = False
        spec.decode_notes.append(
            f"No hardware decoder for '{family_token}' yet — "
            f"falling back to PPR-aware family lookup."
        )
        return spec

    spec.shaft_type_override = decoder.get("shaft_type")

    slots = decoder["slots"]
    maps  = decoder["maps"]

    if len(opts) > len(slots):
        spec.decode_success = False
        spec.decode_notes.append(
            f"Opts too long: '{opts}' has {len(opts)} chars, "
            f"expected {len(slots)} for {family_token}."
        )
        return spec

    if len(opts) < len(slots):
        spec.decode_notes.append(
            f"Partial opts: '{opts}' has {len(opts)} of {len(slots)} chars — "
            f"decoding available slots only."
        )

    notes: list[str] = []
    for i, slot_name in enumerate(slots[:len(opts)]):
        code     = opts[i]
        axis_map = maps.get(slot_name)
        if axis_map is None:
            continue

        value = axis_map.get(code)
        if value is None:
            notes.append(f"Unknown code '{code}' for slot '{slot_name}'.")
            continue

        if slot_name == "shaft_bore":
            spec.shaft_bore_mm = float(value)
        elif slot_name == "shaft_bore_with_ip":
            # Bore slot that encodes both diameter and IP rating (e.g. Sendix 5823).
            # Odd codes = IP40 (no seal), even codes = IP66 (with seal).
            spec.shaft_bore_mm = float(value["diameter_mm"])
            if value.get("ip_rating") is not None:
                spec.ip_rating = int(value["ip_rating"])
        elif slot_name == "shaft_bore_with_type":
            # Bore slot that encodes both diameter and shaft_type (e.g. Sendix 5834).
            # Used when bore code determines whether encoder is hollow or solid.
            # Example: 5834 bore K = tapered shaft = solid; all other bores = hollow_thru.
            spec.shaft_bore_mm = float(value["diameter_mm"])
            if value.get("shaft_type") is not None:
                spec.shaft_type_override = value["shaft_type"]
        elif slot_name == "flange":
            # Flange encodes housing diameter, IP rating, and optionally shaft_type.
            # housing_diameter_mm may be None for spring-element / torque-stop flanges.
            # ip_rating may be None when bore slot carries IP instead (e.g. 5823).
            # shaft_type may be set when flange determines hollow variant (e.g. 5823).
            if value.get("ip_rating") is not None:
                spec.ip_rating = int(value["ip_rating"])
            if value.get("shaft_type") is not None:
                spec.shaft_type_override = value["shaft_type"]
            # housing_diameter_mm not stored in KublerDecodedSpec — the Silver row
            # returned by _fetch_kubler_by_decoded_spec already carries it.
        elif slot_name == "output_type":
            spec.output_circuit_canonical = value["output_circuit_canonical"]
            spec.output_voltage_class     = value["output_voltage_class"]
            spec.supply_voltage_min_v     = float(value["supply_voltage_min_v"])
            spec.supply_voltage_max_v     = float(value["supply_voltage_max_v"])
        elif slot_name == "connection_type":
            spec.connection_type_canonical = value["connection_type_canonical"]
            spec.connector_pins            = value["connector_pins"]

    # Apply fixed_specs — values hardcoded at decoder level (e.g. KIS50/KIH50 ip_rating=65)
    for field_name, fixed_val in decoder.get("fixed_specs", {}).items():
        if field_name == "ip_rating" and spec.ip_rating is None:
            spec.ip_rating = int(fixed_val)

    spec.decode_notes   = notes
    spec.decode_success = spec.shaft_bore_mm is not None
    return spec


# ════════════════════════════════════════════════════════════════════════════════
# PATH B — K-series 5-segment families
# ════════════════════════════════════════════════════════════════════════════════
#
# Standard K58I / K80I segment layout:
#   0  "K58I"        family token
#   1  "OPP"         O(fixed) + interface(PP/RS/SC)              = 3 chars
#   2  "01024"       PPR — 5-digit zero-padded
#   3  "2S1C510"     supply(1) + version(2) + flange/mount(2) + bore/shaft(2) = 7 chars
#   4  "65RC2"       ip(2) + position(1) + i_conn(1) + k_conn(1) = 5 chars
#   5  "0010"        cable length in dm — optional, always stripped
#
# K58I-PR adds "PR" between O and interface in seg1:
#   1  "OPRPP"       O(fixed) + PR(fixed) + interface(PP/RS)     = 5 chars
#   seg1[1:3]=="PR" -> Performance encoder; interface_code = seg1[3:]
#
# Connection logic (seg4):
#   i (seg4[3]) = connection medium — informational
#     1=PVC cable, 2=TPE cable, 3=PUR cable, C=connector on housing
#   k (seg4[4]) = connector type -> maps to Silver fields

# ── K58I / K58I-PR shared maps ────────────────────────────────────────────────

# Output map — standard K58I (supply codes 1 and 2 available)
_K58I_OUTPUT_MAP: dict[tuple, dict] = {
    ("RS", "1"): {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
    ("RS", "2"): {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    ("PP", "2"): {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    ("PP", "1"): {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
}

# Output map — K58I-PR (supply code 2 ONLY — no 5V option on PR variant)
_K58IPR_OUTPUT_MAP: dict[tuple, dict] = {
    ("RS", "2"): {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    ("PP", "2"): {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
}

# Solid shaft bore codes -> diameter mm  (K58I and K58I-PR share identical codes)
_K58I_SHAFT_BORE_MAP: dict[str, float] = {
    "06":  6.0,
    "08":  8.0,
    "10": 10.0,
    "12": 12.0,
    "1A":  6.35,    # ø 1/4" × 5/8"
    "1B":  6.35,    # ø 1/4" × 7/8"
    "2A":  9.525,   # ø 3/8" × 5/8"
    "2B":  9.525,   # ø 3/8" × 7/8"
    "11": 11.0,     # only with version S3
}

# Hollow through-shaft bore codes -> bore ID mm
# 18 codes confirmed against Silver (product_family=K58I, shaft_type=hollow_thru).
# Codes 06/08/10/12/1A/2A overlap with solid shaft map — version code discriminates.
# K58I-PR hollow bore codes confirmed identical from JSON expansion_axes.
_K58I_HOLLOW_BORE_MAP: dict[str, float] = {
    "06":  6.0,
    "08":  8.0,
    "10": 10.0,
    "12": 12.0,
    "14": 14.0,
    "15": 15.0,
    "16": 16.0,
    "20": 20.0,
    "22": 22.0,
    "24": 24.0,
    "25": 25.0,
    "1A":  6.35,    # ø 1/4"
    "2A":  9.525,   # ø 3/8"
    "3A": 12.7,     # ø 1/2"
    "4A": 15.875,   # ø 5/8"
    "5A": 19.05,    # ø 3/4"
    "6A": 22.23,    # ø 7/8"
    "7A": 25.4,     # ø 1"
}

# IP seals — shared by K58I, K58I-PR, K80I (identical codes)
_K58I_IP_MAP: dict[str, int] = {
    "65": 65,
    "6A": 67,   # IP66/IP67 — use 67 (higher value)
}

# Connector type (k-code) — shared by K58I, K58I-PR, K80I (identical codes)
# Special-assignment variants (5,6,H,J) map to same Silver type as standard (2,3,D,E)
_K58I_CONNECTOR_MAP: dict[str, dict] = {
    "1": {"connection_type_canonical": "cable",   "connector_pins": None},
    "2": {"connection_type_canonical": "M12",     "connector_pins": 8},
    "5": {"connection_type_canonical": "M12",     "connector_pins": 8},
    "3": {"connection_type_canonical": "M12",     "connector_pins": 5},
    "6": {"connection_type_canonical": "M12",     "connector_pins": 5},
    "4": {"connection_type_canonical": "M23",     "connector_pins": 12},
    "D": {"connection_type_canonical": "MS/MIL",  "connector_pins": 7},
    "H": {"connection_type_canonical": "MS/MIL",  "connector_pins": 7},
    "E": {"connection_type_canonical": "MS/MIL",  "connector_pins": 10},
    "J": {"connection_type_canonical": "MS/MIL",  "connector_pins": 10},
}


# ── K80I maps ──────────────────────────────────────────────────────────────────
# K80I is hollow_thru only. H1/H2 version codes -> always selects hollow_bore_map.
# shaft_bore_map and hollow_bore_map both point to _K80I_BORE_MAP so the
# version-code discriminator works correctly regardless of which path is taken.

_K80I_BORE_MAP: dict[str, float] = {
    # H1 only
    "35": 35.0,
    "40": 40.0,
    "42": 42.0,
    # H2 only
    "14": 14.0,
    "15": 15.0,
    "16": 16.0,
    "18": 18.0,
    "20": 20.0,
    "25": 25.0,
    "32": 32.0,
    "4A": 15.875,   # 5/8"
    "5A": 19.05,    # 3/4"
    "6A": 22.225,   # 7/8"
    "7A": 25.4,     # 1"
    # H1 and H2 shared
    "28": 28.0,
    "30": 30.0,
    "38": 38.0,
    "8A": 28.575,   # 1 1/8"
    "9A": 31.75,    # 1 1/4"
}

# K80I output map — adds SC; Bronze1 JSON has SC output_voltage_class="universal"
# which is WRONG — SinCos is always "analog". Hardcoded correctly here.
_K80I_OUTPUT_MAP: dict[tuple, dict] = {
    ("RS", "1"): {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
    ("RS", "2"): {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    ("PP", "2"): {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    ("SC", "1"): {"output_circuit_canonical": "Sin/Cos",   "output_voltage_class": "analog",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 5.0},
    ("SC", "2"): {"output_circuit_canonical": "Sin/Cos",   "output_voltage_class": "analog",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
}


# K80I-PR output map — PP and RS only; supply code 2 ONLY (no 5V option, no SC)
_K80IPR_OUTPUT_MAP: dict[tuple, dict] = {
    ("RS", "2"): {"output_circuit_canonical": "TTL RS422", "output_voltage_class": "TTL",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
    ("PP", "2"): {"output_circuit_canonical": "Push-Pull", "output_voltage_class": "universal",
                  "supply_voltage_min_v": 5.0,  "supply_voltage_max_v": 30.0},
}


# ── K-series decoder registry ──────────────────────────────────────────────────

K_SERIES_DECODERS: dict[str, dict] = {
    "K58I": {
        # "shaft_type" = default for partial decodes where seg3 is absent.
        # When seg3 is present, version code determines shaft_type_override:
        #   H1/H2/C1/C2 -> hollow_thru; S1/S3/etc. -> solid.
        "shaft_type":      "solid",
        "shaft_bore_map":  _K58I_SHAFT_BORE_MAP,
        "hollow_bore_map": _K58I_HOLLOW_BORE_MAP,
        "output_map":      _K58I_OUTPUT_MAP,
        "ip_map":          _K58I_IP_MAP,
        "connector_map":   _K58I_CONNECTOR_MAP,
        "ppr_range":       (1, 5000),
        "sample":          "K58I.OPP.01024.2S1C510.65RC2",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "M12",
            "connector_pins":            8,
            "ip_rating":                 65,
            "ppr":                       1024,
        },
        "hollow_sample":   "K58I.OPP.01024.2H1657A.65RC4",
        "hollow_expected": {
            "shaft_bore_mm":             25.4,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "M23",
            "connector_pins":            12,
            "ip_rating":                 65,
            "ppr":                       1024,
        },
    },

    "K58I-PR": {
        # Performance encoder — detected via seg1[1:3]=="PR" in _decode_k_series.
        # Differences from K58I:
        #   - supply code 2 ONLY (5...30V DC; no 5V option)
        #   - ppr_range 1–36000 (programmable, extended range)
        #   - silver_family = "K58I-PR" (confirmed in Silver, 5040 solid + 14112 hollow rows)
        # Bore maps, IP map, connector map identical to K58I — reused.
        "shaft_type":      "solid",
        "shaft_bore_map":  _K58I_SHAFT_BORE_MAP,
        "hollow_bore_map": _K58I_HOLLOW_BORE_MAP,
        "output_map":      _K58IPR_OUTPUT_MAP,
        "ip_map":          _K58I_IP_MAP,
        "connector_map":   _K58I_CONNECTOR_MAP,
        "ppr_range":       (1, 36000),
        "sample":          "K58I.OPRPP.01024.2S1C510.65RC2",
        "expected": {
            "shaft_bore_mm":             10.0,
            "shaft_type_override":       "solid",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "M12",
            "connector_pins":            8,
            "ip_rating":                 65,
            "ppr":                       1024,
        },
        "hollow_sample":   "K58I.OPRPP.01024.2H12515.65RC2",
        "hollow_expected": {
            "shaft_bore_mm":             15.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "M12",
            "connector_pins":            8,
            "ip_rating":                 65,
            "ppr":                       1024,
        },
    },

    "K80I": {
        # Hollow thru-shaft only — no solid shaft variant.
        # K80I uses H1/H2 version codes -> hollow_bore_map always selected.
        # shaft_bore_map and hollow_bore_map both point to _K80I_BORE_MAP.
        # Shares IP map and connector map with K58I (identical codes).
        "shaft_type":      "hollow_thru",
        "shaft_bore_map":  _K80I_BORE_MAP,
        "hollow_bore_map": _K80I_BORE_MAP,
        "output_map":      _K80I_OUTPUT_MAP,
        "ip_map":          _K58I_IP_MAP,
        "connector_map":   _K58I_CONNECTOR_MAP,
        "ppr_range":       (1, 5000),
        "sample":          "K80I.OPP.02048.2H11838.65RC4",
        "expected": {
            "shaft_bore_mm":             38.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "M23",
            "connector_pins":            12,
            "ip_rating":                 65,
            "ppr":                       2048,
        },
    },

    "K80I-PR": {
        # Performance encoder — detected via seg1[1:3]=="PR" in _decode_k_series.
        # K80I-PR is hollow_thru only (no solid variant).
        # Differences from K80I standard:
        #   - supply code 2 ONLY (5...30V DC; no 5V option, no SC output)
        #   - ppr_range 1–36000 (programmable, extended range)
        #   - silver_family = "K80I-PR" (confirmed in Silver: 8064 hollow_thru rows)
        # Bore map, IP map, connector map identical to K80I — all reused.
        "shaft_type":      "hollow_thru",
        "shaft_bore_map":  _K80I_BORE_MAP,
        "hollow_bore_map": _K80I_BORE_MAP,
        "output_map":      _K80IPR_OUTPUT_MAP,
        "ip_map":          _K58I_IP_MAP,
        "connector_map":   _K58I_CONNECTOR_MAP,
        "ppr_range":       (1, 36000),
        "sample":          "K80I.OPRPP.02048.2H11838.65RC4",
        "expected": {
            "shaft_bore_mm":             38.0,
            "shaft_type_override":       "hollow_thru",
            "output_circuit_canonical":  "Push-Pull",
            "output_voltage_class":      "universal",
            "supply_voltage_min_v":      5.0,
            "supply_voltage_max_v":      30.0,
            "connection_type_canonical": "M23",
            "connector_pins":            12,
            "ip_rating":                 65,
            "ppr":                       2048,
        },
    },
}


def _decode_k_series(part_number: str) -> "KublerDecodedSpec | None":
    """
    Decode a K-series order code (Path B).

    Standard:    FAMILY.Oxx.XXXXX.XXXXXXX.XXXXX[.cable_length]
    Performance: FAMILY.OPRxx.XXXXX.XXXXXXX.XXXXX[.cable_length]
      seg1[1:3]=="PR" -> K58I-PR; interface_code = seg1[3:] instead of seg1[1:]

    Segment 3 (7 chars): supply(1) + version(2) + flange/mounting(2) + shaft/bore(2)
    Segment 4 (5 chars): ip(2) + position(1) + i_conn(1) + k_conn(1)

    Solid vs hollow disambiguation (K58I / K58I-PR):
      seg3[1:3] version code in _HOLLOW_VERSION_CODES -> hollow_thru bore map.
      All other version codes -> solid shaft bore map.
    """
    parts = [p for p in part_number.strip().split(".") if p]

    if len(parts) < 3:
        return None

    family_token = parts[0]
    if family_token not in _K_SERIES_FAMILIES:
        return None

    silver_family = KUBLER_FAMILY_ALIASES.get(family_token, family_token)
    spec = KublerDecodedSpec(
        raw_code=part_number,
        family_token=family_token,
        silver_family=silver_family,
    )

    decoder = K_SERIES_DECODERS.get(family_token)
    if decoder is None:
        spec.decode_success = False
        spec.decode_notes.append(
            f"No K-series decoder for '{family_token}' yet — "
            f"falling back to PPR-aware family lookup."
        )
        return spec

    spec.shaft_type_override = decoder["shaft_type"]
    notes: list[str] = []

    # ── Segment 1: O + [PR] + interface ─────────────────────────────────────
    seg1 = parts[1]
    if len(seg1) < 3 or seg1[0] != "O":
        spec.decode_success = False
        spec.decode_notes.append(f"Unexpected segment 1: '{seg1}' (expected O+xx).")
        return spec

    # Performance encoder detection: seg1 = "OPRPP" or "OPRRS"
    # Applies to K58I-PR and K80I-PR — lookup is dynamic on family_token.
    if seg1[1:3] == "PR":
        interface_code = seg1[3:]           # "PP" or "RS"
        pr_family  = f"{family_token}-PR"   # "K58I-PR" or "K80I-PR"
        pr_decoder = K_SERIES_DECODERS.get(pr_family)
        if pr_decoder is not None:
            decoder = pr_decoder
            spec.silver_family       = pr_family
            spec.shaft_type_override = pr_decoder["shaft_type"]
        else:
            notes.append(f"{pr_family} decoder not found — using {family_token} decoder as fallback.")
    else:
        interface_code = seg1[1:]           # "PP", "RS", or "SC"

    # ── Segment 2: PPR (5-digit zero-padded) ────────────────────────────────
    ppr_str  = parts[2]
    ppr: Optional[int] = None
    if re.match(r"^\d{1,5}$", ppr_str):
        val = int(ppr_str)
        ppr_max = decoder["ppr_range"][1]
        if 1 <= val <= ppr_max:
            ppr = val
        else:
            notes.append(f"PPR {val} outside range 1–{ppr_max}.")
    spec.ppr = ppr

    # ── Segment 3 (7 chars): supply + version + flange/mounting + shaft/bore ─
    if len(parts) > 3:
        seg3 = parts[3]
        if len(seg3) != 7:
            notes.append(
                f"Segment 3 unexpected length: '{seg3}' has {len(seg3)} chars, "
                f"expected 7 — skipping hardware params."
            )
        else:
            supply_code  = seg3[0]      # "2" (K58I-PR always 2; K58I also has 1)
            version_code = seg3[1:3]    # "S1"/"S3" = solid; "H1"/"H2"/"C1"/"C2" = hollow
            # seg3[3:5] = flange (solid) or mounting type (hollow) — informational
            shaft_code   = seg3[5:7]    # 2-char bore/shaft diameter code

            # Disambiguate solid vs hollow via version code.
            if version_code in _HOLLOW_VERSION_CODES:
                spec.shaft_type_override = "hollow_thru"
                bore_map = decoder.get("hollow_bore_map", {})
            else:
                spec.shaft_type_override = "solid"
                bore_map = decoder["shaft_bore_map"]

            # Output circuit = interface + supply combined
            output_key  = (interface_code, supply_code)
            output_vals = decoder["output_map"].get(output_key)
            if output_vals is None:
                notes.append(
                    f"Unknown output combination: interface={interface_code!r}, "
                    f"supply={supply_code!r}."
                )
            else:
                spec.output_circuit_canonical = output_vals["output_circuit_canonical"]
                spec.output_voltage_class     = output_vals["output_voltage_class"]
                spec.supply_voltage_min_v     = float(output_vals["supply_voltage_min_v"])
                spec.supply_voltage_max_v     = float(output_vals["supply_voltage_max_v"])

            # Shaft / bore diameter
            bore_mm = bore_map.get(shaft_code)
            if bore_mm is None:
                notes.append(
                    f"Unknown shaft/bore code: '{shaft_code}' "
                    f"(version={version_code!r})."
                )
            else:
                spec.shaft_bore_mm = float(bore_mm)
    else:
        notes.append("Segment 3 absent — hardware params (bore/output) not decoded.")

    # ── Segment 4 (5 chars): ip + position + i_conn + k_conn ────────────────
    if len(parts) > 4:
        seg4 = parts[4]
        if len(seg4) != 5:
            notes.append(
                f"Segment 4 unexpected length: '{seg4}' has {len(seg4)} chars, "
                f"expected 5 — skipping IP/connection."
            )
        else:
            ip_code = seg4[0:2]
            # position = seg4[2]  — informational
            # i_conn   = seg4[3]  — informational (1/2/3/C)
            k_conn   = seg4[4]

            ip_rating = decoder["ip_map"].get(ip_code)
            if ip_rating is None:
                notes.append(f"Unknown IP code: '{ip_code}'.")
            else:
                spec.ip_rating = ip_rating

            conn_vals = decoder["connector_map"].get(k_conn)
            if conn_vals is None:
                notes.append(f"Unknown connector k-code: '{k_conn}'.")
            else:
                spec.connection_type_canonical = conn_vals["connection_type_canonical"]
                spec.connector_pins            = conn_vals["connector_pins"]
    else:
        notes.append("Segment 4 absent — IP/connection not decoded.")

    spec.decode_notes   = notes
    spec.decode_success = (
        spec.shaft_bore_mm is not None or
        spec.output_circuit_canonical is not None
    )
    return spec


# ════════════════════════════════════════════════════════════════════════════════
# Main public function
# ════════════════════════════════════════════════════════════════════════════════

def decode_kubler_order_code(part_number: str) -> "KublerDecodedSpec | None":
    """
    Decode a real Kübler order code into Silver-queryable parameters.

    Dispatches to Path A (numeric-prefix) or Path B (K-series) automatically.
    K58I-PR is detected within Path B via seg1[1:3]=="PR".
    """
    first_token = part_number.strip().split(".")[0] if "." in part_number else ""
    if first_token in _K_SERIES_FAMILIES:
        return _decode_k_series(part_number)

    prefix, family_token, opts, ppr = _parse_kubler_segments(part_number)
    if family_token is None:
        return None

    silver_family = KUBLER_FAMILY_ALIASES.get(family_token)
    if silver_family is None:
        return None

    return _decode_simple_family(part_number, family_token, opts, ppr)


# ── Startup self-test ──────────────────────────────────────────────────────────

def validate_decoders() -> bool:
    """
    Decode each family's sample code and assert expected field values.
    Also tests hollow_sample/hollow_expected when present.
    Call once at API startup to catch map errors early.
    """
    all_decoders = {
        **{k: v for k, v in KUBLER_DECODERS.items()},
        **{k: v for k, v in K_SERIES_DECODERS.items()},
    }
    errors: list[str] = []

    for family, config in all_decoders.items():
        sample   = config.get("sample", "")
        expected = config.get("expected", {})
        if not sample:
            continue

        result = decode_kubler_order_code(sample)

        if result is None:
            errors.append(f"[{family}] returned None for sample {sample!r}")
            continue
        if not result.decode_success:
            errors.append(
                f"[{family}] decode_success=False for {sample!r} | "
                f"{result.decode_notes}"
            )
            continue

        for field_name, expected_val in expected.items():
            actual = getattr(result, field_name, "MISSING")
            if actual != expected_val:
                errors.append(
                    f"[{family}] {field_name}: expected {expected_val!r}, got {actual!r}"
                )

        # Hollow variant test (K58I and K58I-PR)
        hollow_sample   = config.get("hollow_sample", "")
        hollow_expected = config.get("hollow_expected", {})
        if hollow_sample:
            h_result = decode_kubler_order_code(hollow_sample)
            if h_result is None:
                errors.append(
                    f"[{family} hollow] returned None for sample {hollow_sample!r}"
                )
            elif not h_result.decode_success:
                errors.append(
                    f"[{family} hollow] decode_success=False for {hollow_sample!r} | "
                    f"{h_result.decode_notes}"
                )
            else:
                for field_name, expected_val in hollow_expected.items():
                    actual = getattr(h_result, field_name, "MISSING")
                    if actual != expected_val:
                        errors.append(
                            f"[{family} hollow] {field_name}: "
                            f"expected {expected_val!r}, got {actual!r}"
                        )

    if errors:
        for e in errors:
            print(f"  [kubler_decoder] VALIDATION ERROR: {e}")
        return False

    n = len(all_decoders)
    names = ", ".join(all_decoders.keys())
    print(f"  [kubler_decoder] {n} decoder(s) validated OK  ({names})")
    return True


# ── CLI smoke-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== kubler_decoder self-test ===\n")
    ok = validate_decoders()
    print()

    test_codes = [
        # Path A — A020
        ("8.A020.351A.2048",                  "A020: bore=25mm, RS422/5V, cable, ppr=2048"),
        ("8.A020.A52.1024",                   "A020: bore=30mm, PP/10-30V, M23, ppr=1024"),
        ("8.A020.3582.1024",                  "A020: SinCos/5V — analog class"),
        ("8.A020.35.2048",                    "A020 partial: bore only"),
        # Path B — K58I solid shaft
        ("K58I.OPP.01024.2S1C510.65RC2",      "K58I solid: PP, 10mm, IP65, M12-8, ppr=1024"),
        ("K58I.ORS.00500.1S1C506.65RC4",      "K58I solid: RS422/5V, 6mm, IP65, M23-12, ppr=500"),
        ("K58I.ORS.02048.2S1S508.6ARC2",      "K58I solid: RS422/5-30V, 8mm, IP67, M12-8, ppr=2048"),
        ("K58I.OPP.01024.2S1C510.65RC2.0030", "K58I solid: cable length suffix stripped"),
        # Path B — K58I hollow
        ("K58I.OPP.01024.2H1657A.65RC4",      "K58I hollow: PP, 25.4mm(7A), IP65, M23-12, ppr=1024"),
        ("K58I.ORS.02048.1H12510.6ARC2",      "K58I hollow: RS422/5V, 10mm, IP67, M12-8, ppr=2048"),
        # Overlap test — same bore code, different shaft type from version
        ("K58I.OPP.01024.2S1C506.65RC2",      "K58I: code 06 + version S1 -> solid 6mm"),
        ("K58I.OPP.01024.2H1C506.65RC2",      "K58I: code 06 + version H1 -> hollow 6mm"),
        # Path B — K58I-PR solid shaft
        ("K58I.OPRPP.01024.2S1C510.65RC2",    "K58I-PR solid: PP, 10mm, IP65, M12-8, ppr=1024"),
        ("K58I.OPRRS.02048.2S1C508.6ARC2",    "K58I-PR solid: RS422, 8mm, IP67, M12-8, ppr=2048"),
        # Path B — K58I-PR hollow
        ("K58I.OPRPP.01024.2H12515.65RC2",    "K58I-PR hollow: PP, 15mm, IP65, M12-8, ppr=1024"),
        ("K58I.OPRRS.05000.2H11820.65RC4",    "K58I-PR hollow: RS422, 20mm, IP65, M23-12, ppr=5000"),
        # Path B — K58I-PR partial
        ("K58I.OPRPP.01024.2S1C510",          "K58I-PR partial: bore+output, no IP/conn"),
        ("K58I.OPRRS.02048",                  "K58I-PR partial: PPR+interface only"),
        # Path B — K58I partial
        ("K58I.OPP.01024.2S1C510",            "K58I partial: bore+output, no IP/conn"),
        ("K58I.ORS.02048",                    "K58I partial: PPR+interface only"),
        # Path B — K80I
        ("K80I.OPP.02048.2H11838.65RC4",      "K80I: PP, bore=38mm, IP65, M23-12, ppr=2048"),
        # Path B — K80I-PR
        ("K80I.OPRPP.02048.2H11838.65RC4",    "K80I-PR: PP, bore=38mm, IP65, M23-12, ppr=2048"),
        ("K80I.OPRRS.01024.2H11828.65RC2",    "K80I-PR: RS422, bore=28mm, IP65, M12-8, ppr=1024"),
        ("K80I.OPRPP.05000.2H21814.6ARC1",    "K80I-PR: PP, bore=14mm(H2), IP67, cable, ppr=5000"),
        ("K80I.OPRPP.02048.2H11838",          "K80I-PR partial: bore+output, no IP/conn"),
        ("K80I.OPRRS.01024",                  "K80I-PR partial: PPR+interface only"),
        ("K80I.ORS.01024.1H11828.65RC2",      "K80I: RS422/5V, bore=28mm, IP65, M12-8, ppr=1024"),
        ("K80I.OSC.01024.2H11838.65RC4",      "K80I: SinCos — analog class"),
        ("K80I.OPP.02048.2H11838",            "K80I partial: bore+output, no IP/conn"),
        # Path A — Sendix 5000 (shaft)
        ("8.5000.7344.1024",   "5000: flange=7(58mm/IP67), bore=10mm, RS422/5V, M12-8, ppr=1024"),
        ("8.5000.B144.1024",   "5000: flange=B(58mm/IP65), bore=6mm, RS422/5V, M12-8, ppr=1024"),
        ("8.5000.7524.2048",   "5000: flange=7(58mm/IP67), bore=12mm, PP/5-30V, M12-8, ppr=2048"),
        ("8.5000.A128.1024",   "5000: flange=A(58mm/IP67), bore=10mm, M23-12, ppr=1024"),
        # Path A — Sendix 5020 (hollow shaft)
        ("8.5020.3341.1024",   "5020: flange=3(IP67/no_housing), bore=10mm, RS422/5V, cable, ppr=1024"),
        ("8.5020.7824.2048",   "5020: flange=7(65mm/IP67), bore=15mm, PP/5-30V, M12-8, ppr=2048"),
        ("8.5020.D342.1024",   "5020: flange=D(63mm/IP65), bore=10mm, RS422/5V, M12-8, ppr=1024"),
        # Path A — Sendix 5814FS3 (solid, SinCos safety SIL3/PLe)
        ("8.5814FS3.122A.2048",  "5814FS3: flange=1(IP65), bore=10mm, SinCos/10-30V, cable, ppr=2048"),
        ("8.5814FS3.321A.1024",  "5814FS3: flange=3(IP67), bore=10mm, SinCos/5V, cable, ppr=1024"),
        ("8.5814FS3.1A26.2048",  "5814FS3: flange=1(IP65), bore=10mm feather key, SinCos/10-30V, M12-8, ppr=2048"),
        # Path A — Sendix 5834FS3 (hollow, SinCos safety SIL3/PLe, bore K=hollow_thru)
        ("8.5834FS3.B42B.2048",  "5834FS3: flange=B(63mm/IP65), bore=12mm hollow, SinCos/10-30V, cable, ppr=2048"),
        ("8.5834FS3.J31E.1024",  "5834FS3: flange=J(IP67), bore=10mm hollow, SinCos/5V, tang cable, ppr=1024"),
        ("8.5834FS3.LK26.2048",  "5834FS3: flange=L(63mm/IP67), bore=K(tapered/hollow_thru), M12-8, ppr=2048"),
        # Path A — Sendix 5814FS2 (solid, SinCos safety SIL2/PLd)
        ("8.5814FS2.122A.2048",  "5814FS2: flange=1(IP65), bore=10mm, SinCos/10-30V, cable, ppr=2048"),
        ("8.5814FS2.321A.1024",  "5814FS2: flange=3(IP67), bore=10mm flat, SinCos/5V, cable, ppr=1024"),
        ("8.5814FS2.1226.2048",  "5814FS2: flange=1(IP65), bore=10mm, SinCos/10-30V, M12-8, ppr=2048"),
        # Path A — Sendix 5834FS2 (hollow/tapered, SinCos safety SIL2/PLd)
        ("8.5834FS2.B42B.2048",  "5834FS2: flange=B(63mm/IP65), bore=12mm hollow, SinCos/10-30V, cable, ppr=2048"),
        ("8.5834FS2.J31E.1024",  "5834FS2: flange=J(58mm/IP67), bore=10mm hollow, SinCos/5V, tang cable, ppr=1024"),
        ("8.5834FS2.LK26.2048",  "5834FS2: flange=L(63mm/IP67), bore=K(tapered/solid), SinCos/10-30V, M12-8, ppr=2048"),
        # Path A — Sendix 5814 (solid, SinCos, Sendix series)
        ("8.5814.122A.2048",   "5814: flange=1(58mm/IP65), bore=10mm, SinCos/10-30V, cable, ppr=2048"),
        ("8.5814.121A.1024",   "5814: bore=10mm, SinCos/5V, cable, ppr=1024"),
        ("8.5814.1226.2048",   "5814: bore=10mm, SinCos/10-30V, radial M12-8, ppr=2048"),
        # Path A — Sendix 5834 (hollow/tapered, SinCos, Sendix series)
        ("8.5834.142B.2048",   "5834: flange=1(58mm), bore=12mm hollow_thru, SinCos/10-30V, cable, ppr=2048"),
        ("8.5834.132B.1024",   "5834: bore=10mm hollow_thru, SinCos/10-30V, cable, ppr=1024"),
        ("8.5834.552A.2048",   "5834: flange=5(63mm), bore=14mm hollow_thru, SinCos/10-30V, cable, ppr=2048"),
        ("8.5834.5K26.2048",   "5834: flange=5(63mm), bore=K(tapered/solid/10mm), SinCos/10-30V, M12-8, ppr=2048"),
        # Path A — Sendix 5804 (solid, SinCos, IP65)
        ("8.5804.111A.0512",   "5804: flange=1(58mm/IP65), bore=6mm, SinCos/5V, cable, ppr=512"),
        ("8.5804.2123.1024",   "5804: flange=2(58mm/IP65), bore=6mm, SinCos/10-30V, axial M23, ppr=1024"),
        ("8.5804.2225.2048",   "5804: bore=10mm, SinCos/10-30V, radial M23, ppr=2048"),
        # Path A — Sendix 5824 (hollow, SinCos, bore encodes IP)
        ("8.5824.111A.0512",   "5824: flange=1(hollow_thru), bore=6mm/IP40, SinCos/5V, cable, ppr=512"),
        ("8.5824.122A.1024",   "5824: bore=6mm/IP66, SinCos/10-30V, cable, ppr=1024"),
        ("8.5824.3622.2048",   "5824: flange=3(65mm), bore=10mm/IP66, SinCos/10-30V, M23-12, ppr=2048"),
        ("8.5824.481A.1024",   "5824: flange=4(65mm/hollow_thru), bore=12mm/IP66, SinCos/5V, cable, ppr=1024"),
        # Path A — Sendix 5805 (solid, high-res, IP65)
        ("8.5805.114A.6000",   "5805: flange=1(58mm/IP65), bore=6mm, RS422/5V, cable, ppr=6000"),
        ("8.5805.2261.8192",   "5805: bore=10mm, PP/10-30V, axial M23-12, ppr=8192"),
        ("8.5805.12GT.18000",  "5805: bore=6mm, RS422/5V, radial M12-8, ppr=18000"),
        # Path A — Sendix 5825 (hollow, high-res, bore encodes IP)
        ("8.5825.114A.6000",   "5825: flange=1(hollow_thru), bore=6mm/IP40, RS422/10-30V, cable, ppr=6000"),
        ("8.5825.162C.8192",   "5825: bore=10mm/IP66, PP/10-30V, radial M12-8, ppr=8192"),
        ("8.5825.3222.18000",  "5825: flange=3(65mm/hollow_thru), bore=6mm/IP66, PP/10-30V, M23-12, ppr=18000"),
        # Path A — Sendix 5803 (solid, high-temp, IP65)
        ("8.5803.114A.0100",   "5803: flange=1(58mm/IP65), bore=6mm, RS422/5V, cable, ppr=100"),
        ("8.5803.224A.1024",   "5803: flange=2(58mm/IP65), bore=10mm, RS422/5V, cable, ppr=1024"),
        ("8.5803.126A.2048",   "5803: bore=6mm, PP/10-30V, cable, ppr=2048"),
        ("8.5803.1145.1024",   "5803: bore=6mm, RS422/5V, radial M23-12, ppr=1024"),
        # Path A — Sendix 5823 (hollow, high-temp, bore encodes IP)
        ("8.5823.114A.0100",   "5823: flange=1(hollow_thru), bore=6mm/IP40, RS422/5V, cable, ppr=100"),
        ("8.5823.124A.1024",   "5823: flange=1(hollow_thru), bore=6mm/IP66, RS422/10-30V, cable, ppr=1024"),
        ("8.5823.232A.2048",   "5823: flange=2(hollow_thru per Silver), bore=8mm/IP40, PP/10-30V, cable, ppr=2048"),
        ("8.5823.362A.1024",   "5823: flange=3(hollow_thru/65mm), bore=10mm/IP66, PP/10-30V, M23-12, ppr=1024"),
        ("8.5823.471A.0500",   "5823: flange=4(hollow_thru per Silver), bore=12mm/IP40, RS422/5V, cable, ppr=500"),
        # Path A — Sendix 5006 (solid, IP67, M12-8 only)
        ("8.5006.7324.1024",   "5006: flange=7(58mm/IP67), bore=10mm, PP/5-30V, M12-8, ppr=1024"),
        ("8.5006.A144.2048",   "5006: flange=A(58mm/IP67), bore=6mm, RS422/5V, M12-8, ppr=2048"),
        ("8.5006.C324.0500",   "5006: flange=C(63.5mm/IP67), bore=10mm, PP/5-30V, M12-8, ppr=500"),
        # Path A — Sendix 5026 (hollow_thru, IP67, M12-8 only)
        ("8.5026.1822.1024",   "5026: flange=1(spring/IP67), bore=15mm, PP/5-30V, M12-8, ppr=1024"),
        ("8.5026.C342.2048",   "5026: flange=C(63mm/IP67), bore=10mm, RS422/5V, M12-8, ppr=2048"),
        ("8.5026.1422.0500",   "5026: bore=9.525mm (3/8 inch), PP/5-30V, M12-8, ppr=500"),
        # Path A — Sendix 7000 (solid shaft, ATEX, cable-only)
        ("8.7000.124A.1024",   "7000: flange=1(70mm/IP67), bore=10mm, RS422/5V, cable, ppr=1024"),
        ("8.7000.112.1024",    "7000: bore=10mm, RS422/5-30V, cable partial (3/4 slots)"),
        ("8.7000.1251.2048",   "7000: bore=12mm, PP/5-30V, axial cable 2m, ppr=2048"),
        # Path A — Sendix 7020 (hollow_blind, ATEX, cable-only)
        ("8.7020.124A.2048",   "7020: flange=1(70mm/IP67), bore=14mm, RS422/5V, cable, ppr=2048"),
        ("8.7020.512.1024",    "7020: flange=5(65mm/IP67), bore=12mm, RS422/5-30V, partial"),
        ("8.7020.1221.1024",   "7020: bore=14mm, PP/5-30V, axial cable 2m, ppr=1024"),
        # Path A — 5000/5020 partial opts
        ("8.5000.73.1024",     "5000 partial: flange+bore only (2/4 slots)"),
        ("8.5000.734.1024",    "5000 partial: flange+bore+output (3/4 slots)"),
        # Path A — 2400-series (miniature encoders)
        ("05.2400.122A.1024",  "2400: flange=1(24mm/IP65), bore=6mm, PP/5-24V, cable, ppr=1024"),
        ("05.2400.312A.0500",  "2400: flange=3(28mm/IP65), bore=4mm, PP/5-24V, cable, ppr=500"),
        ("05.2400.126A.1024",  "2400: bore=6mm, RS422/5V, cable, ppr=1024"),
        ("05.2420.122A.1024",  "2420: bore=6mm hollow_blind, PP/5-24V, cable, ppr=1024"),
        ("05.2420.112A.0360",  "2420: bore=4mm hollow_blind, PP/5-24V, cable, ppr=360"),
        ("8.2430.126A.0256",   "2430: bore=6mm, RS422/5V, cable, ppr=256"),
        ("8.2430.316A.0128",   "2430: flange=3(28mm), bore=4mm, RS422/5V, cable, ppr=128"),
        ("8.2440.126A.0256",   "2440: bore=6mm hollow_blind, RS422/5V, cable, ppr=256"),
        # Partial (no decoder yet)
        ("8.5814.122A.2048",                  "Sendix 5814 — partial, no decoder yet"),
        ("8.KIS40.1342.1024",                 "KIS40 — partial, no decoder yet"),
        # None
        ("UNKNOWN.CODE",                      "garbage -> None"),
    ]

    for code, label in test_codes:
        result = decode_kubler_order_code(code)
        if result is None:
            status = "-> None"
        elif not result.decode_success:
            status = (f"-> PARTIAL  family={result.silver_family!r}  ppr={result.ppr}"
                      f"  | {'; '.join(result.decode_notes)}")
        else:
            status = (
                f"-> OK  bore={result.shaft_bore_mm}mm({result.shaft_type_override})"
                f"  {result.output_circuit_canonical}"
                f"  V={result.supply_voltage_min_v}–{result.supply_voltage_max_v}"
                f"  {result.connection_type_canonical}(pins={result.connector_pins})"
                f"  IP{result.ip_rating}"
                f"  ppr={result.ppr}"
                f"  family={result.silver_family!r}"
            )
        print(f"  {code:<46s} {status}")
        print(f"    ({label})")