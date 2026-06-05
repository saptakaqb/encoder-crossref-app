"""
epc_decoder.py
==============
Decode real EPC (Encoder Products Company) order codes into Silver-queryable parameters.

Verified position layouts (from ordering guide images):

  15S / 15T / 15H / 25T / 25H / TR-series:
    MODEL-SHAFT-MOUNT-CPR-COMM-INVOLT-CHAN-OUTPUT-CONN[-TEMP][-FREQ][-SEAL][-CERT]
    pos:    1     2    3    4     5     6     7      8

  802S:
    MODEL-SHAFT-TEMP-CPR-CHAN-OUTPUT-FREQ-MOUNT-SEAL-CONNLOC-CONN[-CERT]
    pos:    1    2    3    4    5     6     7     8    9      10

  725:
    MODEL-STYLE-SHAFT-TEMP-CPR-CHAN-OUTPUT-FREQ-MOUNT-SEAL-CONNLOC-CONN-MATING[-CERT]
    pos:    1     2    3    4    5    6      7    8     9    10     11    12

  858S:
    MODEL-MNTTYPE-SHAFT-TEMP-CPR-CHAN-OUTPUT-FREQ-SEAL-CONNLOC-CONN[-CERT]
    pos:     1      2    3    4    5    6      7    8    9      10

  755A (shaft + hollow bore — single token, shaft_type from code at pos1):
    MODEL-BORE/SHAFT-TEMP-CPR-CHAN-OUTPUT-FREQ-MOUNT-CONN[-CERT]
    pos:      1       2    3    4    5      6    7     8

  260 (shaft_type from housing style at pos2):
    MODEL-COMM-HOUSINGTYPE-BORE-TEMP-CPR-CHAN-OUTPUT-FREQ-CONN-MOUNT-SEAL-CERT
    pos:   1       2        3    4    5    6    7      8    9   10    11   12

  58TF/58HF/58TP/58HP:
    MODEL-BORE-MOUNT-[RANGE]-CPR-WAVEFORM-OUTPUT-CONNLOC-CONN[-TEMP][-SEAL][-CERT]
    pos:    1    2      3      4     5       6      7       8

AQB Solutions | May 2026
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class EpcDecodedSpec:
    raw_code:  str
    family_token: str
    silver_family: str

    shaft_bore_mm:             Optional[float] = None
    shaft_type:                Optional[str]   = None
    output_circuit_canonical:  Optional[str]   = None
    output_voltage_class:      Optional[str]   = None
    supply_voltage_min_v:      Optional[float] = None
    supply_voltage_max_v:      Optional[float] = None
    connection_type_canonical: Optional[str]   = None
    connector_pins:            Optional[int]   = None
    ip_rating:                 Optional[int]   = None
    operating_temp_min_c:      Optional[float] = None
    operating_temp_max_c:      Optional[float] = None
    ppr:                       Optional[int]   = None

    decode_success: bool = False
    decode_notes:   list = field(default_factory=list)


# ── Family config ──────────────────────────────────────────────────────────────

@dataclass
class EpcFamilyConfig:
    # Core spec fields
    silver_family:         str
    shaft_type:            str       # default shaft_type (may be overridden per code)
    shaft_map:             dict      # code -> bore_mm (combined for multi-variant families)
    default_ip:            int
    default_temp_min_c:    float
    default_temp_max_c:    float
    sealing_map:           dict      # code -> ip_rating
    temp_token_map:        dict      # code -> (min_c, max_c)
    has_input_voltage_pos: bool

    # Position layout — defaults match the 15S / TR-series structure
    pos_shaft:         int           = 1
    pos_cpr:           int           = 3
    pos_output:        int           = 7
    pos_connector:     int           = 8
    pos_input_voltage: int           = 5   # only used when has_input_voltage_pos=True
    pos_temp:          Optional[int] = None  # None = trailing; int = fixed position
    pos_sealing:       Optional[int] = None  # None = trailing; int = fixed position

    # For families where shaft_type is encoded in the shaft/bore code itself (755A):
    # Maps shaft_code -> shaft_type override. Empty = always use cfg.shaft_type.
    shaft_type_by_code: dict = field(default_factory=dict)

    # For families where a separate position token determines shaft_type (260):
    # shaft_variant_pos: which position holds the housing/type code
    # shaft_variant_map: token -> shaft_type
    shaft_variant_pos: Optional[int] = None
    shaft_variant_map: dict          = field(default_factory=dict)


# ── Shared output type map ─────────────────────────────────────────────────────

_OUTPUT_CIRCUIT_MAP: dict[str, tuple[str, str]] = {
    "OC": ("Open Collector", "TTL"),
    "PU": ("Open Collector", "TTL"),
    "OD": ("Open Collector", "TTL"),
    "PP": ("Push-Pull",      "universal"),
    "HV": ("TTL RS422",      "TTL"),
    "LO": ("TTL RS422",      "TTL"),
    "H5": ("TTL RS422",      "TTL"),
    "P5": ("Push-Pull",      "universal"),
}

_SUPPLY_VOLTAGE_MAP: dict[str, tuple[float, float]] = {
    "OC": (4.75, 28.0),
    "PU": (4.75, 28.0),
    "OD": (4.75, 28.0),
    "PP": (4.75, 28.0),
    "HV": (4.75, 28.0),
    "LO": (4.75, 28.0),
    "H5": (8.0,  28.0),
    "P5": (8.0,  28.0),
}

# ── Connector map ──────────────────────────────────────────────────────────────

_CONNECTOR_MAP: dict[str, tuple[str, Optional[int]]] = {
    # Cable variants
    "F00": ("cable", None),
    "F01": ("cable", None),
    "F02": ("cable", None),
    "F03": ("cable", None),
    "M00": ("cable", None),
    "S":   ("cable", None),   # standard 18" flying leads
    "G":   ("cable", None),   # gland 24" cable (802S/725/858S)
    # M12 connectors
    "J":   ("M12",   5),
    "J00": ("M12",   5),
    "K":   ("M12",   8),
    "K00": ("M12",   8),
    "Z":   ("M12",   8),
    "MJ":  ("M12",   5),      # 5-pin body mount M12 (58/260/25T)
    "MK":  ("M12",   8),      # 8-pin body mount M12 standard
    "MZ":  ("M12",   8),      # 8-pin M12 optional wiring
    "SMJ": ("M12",   5),      # 5-pin body mount M12 (25T/H, 260)
    "SMK": ("M12",   8),      # 8-pin body mount M12 standard (25T/H, 260)
    "SMZ": ("M12",   8),      # 8-pin M12 optional wiring (25T/H, 260)
    # M23
    "MR":  ("M23",  12),      # 12-pin M23 (58-series)
    # MS connectors
    "W":   ("cable",  6),     # 6-pin MS (725)
    "Y":   ("cable",  7),     # 7-pin MS (725)
    "X":   ("cable", 10),     # 10-pin MS (725)
    "MY":  ("cable",  7),     # 7-pin MS (58-series)
    "MX":  ("cable", 10),     # 10-pin MS (58-series)
    "SMW": ("cable",  6),     # 6-pin MS (25T/H)
    "SMY": ("cable",  7),     # 7-pin MS (25T/H)
    "SMX": ("cable", 10),     # 10-pin MS (25T/H)
    "SMH": ("cable", 10),     # 10-pin body mount bayonet (25T/H, 260)
    "MW":  ("cable",  6),     # 6-pin MS (25SF/25SP connector type)
    # D-sub / special
    "9D":  ("cable",  9),
    "MY2": ("cable",  7),
    # 755A specific
    "C01": ("cable",  8),     # 8-pin Molex
    "C02": ("cable", None),   # terminal block
    # Other
    "A00": ("cable", 15),     # 15-pin header (15S)
    # 770/771 connectors
    "P":   ("cable", None),   # gland nut with 24" cable
    "B":   ("cable", None),   # terminal strip in conduit box
    "Y":   ("cable",  7),     # 7-pin MS on conduit box
    "L":   ("cable", 10),     # 10-pin industrial clamp
    # 30M connectors
    "C":   ("cable",  8),     # 8-pin Molex header
    "V":   ("cable", 16),     # 16-pin Molex header
    # 225A/Q connectors
    "T":   ("cable", None),   # terminal block
}

# ── Tokens always ignored in trailing positions ────────────────────────────────
_ALWAYS_IGNORE = {"F3", "CE", "N"}


# ── Family registry ────────────────────────────────────────────────────────────

EPC_FAMILY_CONFIGS: dict[str, EpcFamilyConfig] = {

    # ── 121 — verified from ordering guide ───────────────────────────────────
    # Format: MODEL-COMM-HOUSING-INVOLT-BORE-TEMP-CPR-CHAN-OUTPUT-FREQ-CONN-CERT
    # pos_shaft=4, pos_temp=5(fixed), pos_cpr=6, pos_output=8, pos_connector=10
    # has_input_voltage_pos=True at pos3 (5=5VDC only — no V1 option)
    # No sealing axis — fixed IP50
    "121": EpcFamilyConfig(
        silver_family="121", shaft_type="hollow_blind",
        shaft_map={
            "01": 6.35, "02": 9.525, "03": 7.9375, "04": 6.0,
            "05": 10.0, "06": 5.0,   "10": 12.7,   "11": 15.875,
            "12": 12.0, "13": 14.0,  "14": 8.0,    "15": 15.0, "99": 12.6238,
        },
        default_ip=50, default_temp_min_c=0.0, default_temp_max_c=70.0,
        sealing_map={},
        temp_token_map={"H": (0.0, 100.0)},
        has_input_voltage_pos=True,
        pos_shaft=4, pos_cpr=6, pos_output=8, pos_connector=10,
        pos_temp=5, pos_input_voltage=3,
    ),

    # ── 15S shaft — verified ───────────────────────────────────────────────────
    "15S": EpcFamilyConfig(
        silver_family="15S", shaft_type="solid",
        shaft_map={"19": 6.35, "20": 6.0, "21": 4.7625, "23": 4.0},
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S1": 64},
        temp_token_map={
            "T1": (-40.0, 85.0), "T2": (-20.0, 100.0),
            "T3": (-20.0, 120.0), "T7": (-40.0, 120.0),
        },
        has_input_voltage_pos=True,
    ),

    # ── 15T/H — verified ──────────────────────────────────────────────────────
    "15T": EpcFamilyConfig(
        silver_family="15T/H", shaft_type="hollow_thru",
        shaft_map={
            "01": 6.35, "02": 9.525, "03": 7.9375, "04": 6.0,
            "05": 10.0, "06": 5.0,   "08": 4.0, "14": 8.0, "15": 4.7625,
        },
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S1": 64},
        temp_token_map={
            "T1": (-40.0, 85.0), "T2": (-20.0, 100.0),
            "T3": (-20.0, 120.0), "T7": (-40.0, 120.0),
        },
        has_input_voltage_pos=True,
    ),

    "15H": EpcFamilyConfig(
        silver_family="15T/H", shaft_type="hollow_blind",
        shaft_map={
            "01": 6.35, "02": 9.525, "03": 7.9375, "04": 6.0,
            "05": 10.0, "06": 5.0,   "08": 4.0, "14": 8.0, "15": 4.7625,
        },
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S1": 64},
        temp_token_map={
            "T1": (-40.0, 85.0), "T2": (-20.0, 100.0),
            "T3": (-20.0, 120.0), "T7": (-40.0, 120.0),
        },
        has_input_voltage_pos=True,
    ),

    # ── 225A/Q — verified from ordering guide ────────────────────────────────
    # Format: MODEL-BORE-CPR-OUTPUT-MOUNT-SEAL-CONN (7 tokens total)
    # pos_shaft=1, pos_cpr=2, pos_output=3, pos_sealing=5(fixed), pos_connector=6
    # No temp axis — fixed default -25 to 85°C. Output: OC and PU only.
    "225A": EpcFamilyConfig(
        silver_family="225A/Q", shaft_type="hollow_blind",
        shaft_map={
            "01": 6.35,  "02": 9.525,  "03": 7.9375, "05": 10.0,
            "06": 11.0,  "07": 7.0,    "10": 12.7,   "11": 15.875,
            "12": 12.0,  "14": 14.0,   "15": 15.0,   "16": 16.0,
            "17": 17.0,  "18": 22.225, "19": 19.0,   "20": 20.0,
            "22": 22.0,  "34": 19.05,  "56": 14.2875,"68": 17.4625,
        },
        default_ip=50, default_temp_min_c=-25.0, default_temp_max_c=85.0,
        sealing_map={"N": 50, "Y": 50}, temp_token_map={}, has_input_voltage_pos=False,
        pos_shaft=1, pos_cpr=2, pos_output=3, pos_connector=6, pos_sealing=5,
    ),

    "225Q": EpcFamilyConfig(
        silver_family="225A/Q", shaft_type="hollow_blind",
        shaft_map={
            "01": 6.35,  "02": 9.525,  "03": 7.9375, "05": 10.0,
            "06": 11.0,  "07": 7.0,    "10": 12.7,   "11": 15.875,
            "12": 12.0,  "14": 14.0,   "15": 15.0,   "16": 16.0,
            "17": 17.0,  "18": 22.225, "19": 19.0,   "20": 20.0,
            "22": 22.0,  "34": 19.05,  "56": 14.2875,"68": 17.4625,
        },
        default_ip=50, default_temp_min_c=-25.0, default_temp_max_c=85.0,
        sealing_map={"N": 50, "Y": 50}, temp_token_map={}, has_input_voltage_pos=False,
        pos_shaft=1, pos_cpr=2, pos_output=3, pos_connector=6, pos_sealing=5,
    ),

    # ── 25T/H — verified from ordering guide ──────────────────────────────────
    # Same position structure as 15S. has_input_voltage_pos=True (V1 at pos5).
    # Default temp: -20 to 85°C. Sealing and temp are trailing optional.
    "25T": EpcFamilyConfig(
        silver_family="25T/H", shaft_type="hollow_thru",
        shaft_map={
            "01": 6.35,  "02": 9.525,  "03": 7.9375, "04": 6.0,
            "05": 12.7,  "09": 11.0,   "10": 10.0,   "11": 15.875,
            "12": 12.0,  "13": 14.0,   "14": 8.0,    "15": 15.0,
            "16": 16.0,  "17": 17.0,   "18": 18.0,   "19": 19.0,
            "20": 20.0,  "24": 24.0,   "25": 25.0,   "28": 28.0,
            "34": 19.05, "40": 25.4,   "42": 28.575, "78": 22.225,
        },
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S3": 66},
        temp_token_map={"T1": (-40.0, 85.0), "T4": (-20.0, 105.0)},
        has_input_voltage_pos=True,
    ),

    "25H": EpcFamilyConfig(
        silver_family="25T/H", shaft_type="hollow_blind",
        shaft_map={
            "01": 6.35,  "02": 9.525,  "03": 7.9375, "04": 6.0,
            "05": 12.7,  "09": 11.0,   "10": 10.0,   "11": 15.875,
            "12": 12.0,  "13": 14.0,   "14": 8.0,    "15": 15.0,
            "16": 16.0,  "17": 17.0,   "18": 18.0,   "19": 19.0,
            "20": 20.0,  "24": 24.0,   "25": 25.0,   "28": 28.0,
            "34": 19.05, "40": 25.4,   "42": 28.575, "78": 22.225,
        },
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S3": 66},
        temp_token_map={"T1": (-40.0, 85.0), "T4": (-20.0, 105.0)},
        has_input_voltage_pos=True,
    ),

    # ── 25SF / 25SP — verified (25SF ordering guide) ─────────────────────────
    # Format: MODEL-SHAFT-MOUNT-X-CPR-WAVEFORM-OUTPUT-CONNLOC-CONN[-TEMP][-SEAL][-CERT]
    # Same structure as 58TF: pos_cpr=4, pos_output=6, pos_connector=8
    # has_input_voltage_pos=False (5-30V in/out standard for all outputs)
    # 25SP assumed same structure as 25SF
    "25SF": EpcFamilyConfig(
        silver_family="25SF", shaft_type="solid",
        shaft_map={"03": 7.9375, "06": 6.0, "08": 8.0, "10": 10.0, "19": 6.35, "38": 9.525},
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S1": 64, "S3": 66, "S4": 67},
        temp_token_map={"T6": (-40.0, 100.0)},
        has_input_voltage_pos=False,
        pos_shaft=1, pos_cpr=4, pos_output=6, pos_connector=8,
    ),

    "25SP": EpcFamilyConfig(
        silver_family="25SP", shaft_type="solid",
        shaft_map={"03": 7.9375, "06": 6.0, "08": 8.0, "10": 10.0, "19": 6.35, "38": 9.525},
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S1": 64, "S3": 66, "S4": 67},
        temp_token_map={"T6": (-40.0, 100.0)},
        has_input_voltage_pos=False,
        pos_shaft=1, pos_cpr=4, pos_output=6, pos_connector=8,
    ),

    # ── 260 — verified from ordering guide ────────────────────────────────────
    # Single "260" token covers both hollow_blind and hollow_thru.
    # shaft_type determined by pos2 housing style: B=hollow_blind, T/R=hollow_thru.
    # Format: MODEL-COMM-HOUSINGTYPE-BORE-TEMP-CPR-CHAN-OUTPUT-FREQ-CONN-MOUNT-SEAL-CERT
    # pos_shaft=3, shaft_variant_pos=2, pos_temp=4(fixed), pos_cpr=5,
    # pos_output=7, pos_connector=9, pos_sealing=11(fixed)
    # Sealing map: 1=IP50(thru), 2=IP64(thru), 3=IP64(hollow), 4=IP50(hollow)
    "260": EpcFamilyConfig(
        silver_family="260", shaft_type="hollow_blind",  # default; overridden by pos2
        shaft_map={
            "01": 6.35,  "02": 9.525, "76": 11.1125, "10": 12.7,
            "11": 15.875,"06": 5.0,   "04": 6.0,     "14": 8.0,
            "05": 10.0,  "09": 11.0,  "12": 12.0,    "13": 14.0, "15": 15.0,
        },
        default_ip=50, default_temp_min_c=0.0, default_temp_max_c=70.0,
        sealing_map={"1": 50, "2": 64, "3": 64, "4": 50},
        temp_token_map={
            "L": (-40.0, 70.0), "H": (0.0, 100.0), "V": (0.0, 120.0),
        },
        has_input_voltage_pos=False,
        pos_shaft=3, pos_cpr=5, pos_output=7, pos_connector=9,
        pos_temp=4, pos_sealing=11,
        shaft_variant_pos=2,
        shaft_variant_map={"B": "hollow_blind", "T": "hollow_thru", "R": "hollow_thru"},
    ),

    # ── 30M / 30MT — verified from ordering guides ───────────────────────────
    # Format: MODEL-MAGNET/BORE-CPR-COMM-INVOLT-CHAN-OUTPUT-CONN[-SEAL]
    # pos_shaft=1, pos_cpr=2, has_input_voltage_pos=True at pos4, pos_output=6, pos_connector=7
    # Sealing is trailing: S6=IP69K, blank=IP50 default
    # 30MT has only K connector (8-pin M12); shaft_map empty (threaded module, no bore in Silver)
    "30M": EpcFamilyConfig(
        silver_family="30M", shaft_type="hollow_blind",
        shaft_map={
            "21": 4.7625, "01": 6.35,  "03": 7.9375, "02": 9.525,
            "05": 12.7,   "11": 15.875,"06": 5.0,    "04": 6.0,
            "14": 8.0,    "10": 10.0,  "13": 14.0,
        },
        default_ip=50, default_temp_min_c=-40.0, default_temp_max_c=120.0,
        sealing_map={"S6": 69}, temp_token_map={},
        has_input_voltage_pos=True,
        pos_shaft=1, pos_cpr=2, pos_output=6, pos_connector=7,
        pos_input_voltage=4,
    ),

    "30MT": EpcFamilyConfig(
        silver_family="30MT", shaft_type="solid",
        shaft_map={},   # threaded module — no bore in Silver
        default_ip=50, default_temp_min_c=-40.0, default_temp_max_c=120.0,
        sealing_map={"S6": 69}, temp_token_map={},
        has_input_voltage_pos=True,
        pos_shaft=1, pos_cpr=2, pos_output=6, pos_connector=7,
        pos_input_voltage=4,
    ),

    # ── 58TF / 58HF — verified from ordering guide ────────────────────────────
    # Format: MODEL-BORE-MOUNT-X-CPR-WAVEFORM-OUTPUT-CONNLOC-CONN[-T6][-S1/3/4][-CE]
    "58TF": EpcFamilyConfig(
        silver_family="58TF", shaft_type="hollow_thru",
        shaft_map={
            "01": 6.35,  "02": 9.525,  "03": 7.9375, "04": 6.0,
            "05": 12.7,  "09": 11.0,   "10": 10.0,   "11": 15.875,
            "12": 12.0,  "13": 14.0,   "14": 8.0,    "15": 15.0,
        },
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S1": 64, "S3": 66, "S4": 67},
        temp_token_map={"T6": (-40.0, 100.0)},
        has_input_voltage_pos=False,
        pos_shaft=1, pos_cpr=4, pos_output=6, pos_connector=8,
    ),

    "58HF": EpcFamilyConfig(
        silver_family="58HF", shaft_type="hollow_blind",
        shaft_map={
            "01": 6.35,  "02": 9.525,  "03": 7.9375, "04": 6.0,
            "05": 12.7,  "09": 11.0,   "10": 10.0,   "11": 15.875,
            "12": 12.0,  "13": 14.0,   "14": 8.0,    "15": 15.0,
        },
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S1": 64, "S3": 66, "S4": 67},
        temp_token_map={"T6": (-40.0, 100.0)},
        has_input_voltage_pos=False,
        pos_shaft=1, pos_cpr=4, pos_output=6, pos_connector=8,
    ),

    # ── 58TP / 58HP — verified from ordering guide ────────────────────────────
    # Programmable variant of 58TF/58HF. Same positions — pos3=CPR range (A/B,
    # ignored), pos4=factory-programmed CPR value.
    "58TP": EpcFamilyConfig(
        silver_family="58TP", shaft_type="hollow_thru",
        shaft_map={
            "01": 6.35,  "02": 9.525,  "03": 7.9375, "04": 6.0,
            "05": 12.7,  "09": 11.0,   "10": 10.0,   "11": 15.875,
            "12": 12.0,  "13": 14.0,   "14": 8.0,    "15": 15.0,
        },
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S1": 64, "S3": 66, "S4": 67},
        temp_token_map={"T6": (-40.0, 100.0)},
        has_input_voltage_pos=False,
        pos_shaft=1, pos_cpr=4, pos_output=6, pos_connector=8,
    ),

    "58HP": EpcFamilyConfig(
        silver_family="58HP", shaft_type="hollow_blind",
        shaft_map={
            "01": 6.35,  "02": 9.525,  "03": 7.9375, "04": 6.0,
            "05": 12.7,  "09": 11.0,   "10": 10.0,   "11": 15.875,
            "12": 12.0,  "13": 14.0,   "14": 8.0,    "15": 15.0,
        },
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S1": 64, "S3": 66, "S4": 67},
        temp_token_map={"T6": (-40.0, 100.0)},
        has_input_voltage_pos=False,
        pos_shaft=1, pos_cpr=4, pos_output=6, pos_connector=8,
    ),

    # ── 725 — verified ────────────────────────────────────────────────────────
    # Format: MODEL-STYLE-SHAFT-TEMP-CPR-CHAN-OUTPUT-FREQ-MOUNT-SEAL-CONNLOC-CONN-MATING
    "725": EpcFamilyConfig(
        silver_family="725", shaft_type="solid",
        shaft_map={
            "4":  6.35, "S": 9.525, "06": 6.0, "18": 8.0,
            "19": 7.9375, "21": 10.0, "25": 9.525,
        },
        default_ip=50, default_temp_min_c=0.0, default_temp_max_c=70.0,
        sealing_map={"1": 66, "2": 64, "5": 67},
        temp_token_map={"H": (0.0, 100.0), "L": (-40.0, 70.0)},
        has_input_voltage_pos=False,
        pos_shaft=2, pos_cpr=4, pos_output=6, pos_connector=11,
        pos_temp=3, pos_sealing=9,
    ),

    # ── 755A — verified from both ordering guides ─────────────────────────────
    # Single "755A" token covers shaft (solid) and hollow bore (hollow_blind).
    # shaft_type determined from the code at pos1:
    #   Shaft codes  (07,08,06,32,20,19) -> solid
    #   Bore codes   (all others)        -> hollow_blind (cfg default)
    # Format: MODEL-BORE/SHAFT-TEMP-CPR-CHAN-OUTPUT-FREQ-MOUNT-CONN[-CERT]
    # pos_temp=2(fixed), pos_cpr=3, pos_output=5, pos_connector=8, no sealing
    "755A": EpcFamilyConfig(
        silver_family="755A", shaft_type="hollow_blind",
        shaft_map={
            # Hollow bore codes
            "15": 4.7625, "16": 4.0,   "01": 6.35,  "18": 5.0,
            "03": 7.9375, "04": 6.0,   "02": 9.525, "14": 8.0,
            "10": 12.7,   "05": 10.0,  "11": 15.875,"12": 12.0,
            "17": 19.05,  "13": 14.0,
            # Shaft codes (will trigger shaft_type_by_code override to "solid")
            "07": 6.35,   "08": 5.0,   "06": 6.0,
            "32": 6.35,   "20": 6.0,   "19": 6.35,
        },
        default_ip=50, default_temp_min_c=0.0, default_temp_max_c=70.0,
        sealing_map={},
        temp_token_map={"L": (-40.0, 70.0), "H": (0.0, 100.0)},
        has_input_voltage_pos=False,
        pos_shaft=1, pos_cpr=3, pos_output=5, pos_connector=8,
        pos_temp=2,
        shaft_type_by_code={
            "07": "solid", "08": "solid", "06": "solid",
            "32": "solid", "20": "solid", "19": "solid",
        },
    ),

    # ── 770 / 771 — verified from ordering guides ────────────────────────────
    # Format: MODEL-HOUSINGSTYLE-TEMP-CPR-CHAN-OUTPUT-BORE-GASKET-CONN-MATING-CERT
    # pos_shaft=6, pos_temp=2(fixed), pos_cpr=3, pos_output=5, pos_connector=8
    # pos_sealing=1(fixed): housing style A=IP65, B=IP50 (both hollow_thru)
    # 770: smaller bores (5/8" to 24mm); 771: larger bores (1-1/8" to 43mm)
    "770": EpcFamilyConfig(
        silver_family="770", shaft_type="hollow_thru",
        shaft_map={
            "A": 15.875, "B": 19.05, "C": 22.225, "D": 25.4,
            "H": 14.0,   "I": 19.0,  "K": 24.0,
        },
        default_ip=50, default_temp_min_c=0.0, default_temp_max_c=70.0,
        sealing_map={"A": 65, "B": 50},
        temp_token_map={"H": (0.0, 100.0)},
        has_input_voltage_pos=False,
        pos_shaft=6, pos_cpr=3, pos_output=5, pos_connector=8,
        pos_temp=2, pos_sealing=1,
    ),

    "771": EpcFamilyConfig(
        silver_family="771", shaft_type="hollow_thru",
        shaft_map={
            "T": 15.875, "V": 22.225, "W": 25.4,   "A": 28.575,
            "K": 31.75,  "B": 34.925, "C": 38.1,   "D": 41.275,
            "F": 44.45,  "E": 47.625, "H": 28.0,   "Q": 30.0,
            "R": 32.0,   "L": 35.0,   "I": 38.0,   "J": 40.0,
            "M": 42.0,   "N": 43.0,
        },
        default_ip=50, default_temp_min_c=0.0, default_temp_max_c=70.0,
        sealing_map={"A": 65, "B": 50},
        temp_token_map={"H": (0.0, 100.0)},
        has_input_voltage_pos=False,
        pos_shaft=6, pos_cpr=3, pos_output=5, pos_connector=8,
        pos_temp=2, pos_sealing=1,
    ),

    # ── 802S — verified ───────────────────────────────────────────────────────
    # Format: MODEL-SHAFT-TEMP-CPR-CHAN-OUTPUT-FREQ-MOUNT-SEAL-CONNLOC-CONN[-CERT]
    "802S": EpcFamilyConfig(
        silver_family="802S", shaft_type="solid",
        shaft_map={"07": 6.35, "20": 9.525, "21": 10.0, "30": 9.525},
        default_ip=50, default_temp_min_c=0.0, default_temp_max_c=70.0,
        sealing_map={"1": 66, "2": 64, "5": 67},
        temp_token_map={"H": (0.0, 100.0), "L": (-40.0, 70.0)},
        has_input_voltage_pos=False,
        pos_shaft=1, pos_cpr=3, pos_output=5, pos_connector=10,
        pos_temp=2, pos_sealing=8,
    ),

    # ── 858S — verified ───────────────────────────────────────────────────────
    # Format: MODEL-MNTTYPE-SHAFT-TEMP-CPR-CHAN-OUTPUT-FREQ-SEAL-CONNLOC-CONN[-CERT]
    "858S": EpcFamilyConfig(
        silver_family="858S", shaft_type="solid",
        shaft_map={"06": 6.0, "07": 6.35, "20": 9.525, "21": 10.0},
        default_ip=50, default_temp_min_c=0.0, default_temp_max_c=70.0,
        sealing_map={"1": 66, "2": 64, "5": 67},
        temp_token_map={"H": (0.0, 100.0), "L": (-40.0, 70.0)},
        has_input_voltage_pos=False,
        pos_shaft=2, pos_cpr=4, pos_output=6, pos_connector=10,
        pos_temp=3, pos_sealing=8,
    ),

    # ── 865T — verified from ordering guide ──────────────────────────────────
    # Format: MODEL-BORE-HOUSINGSTYLE-CPR-COMM-INVOLT-CHAN-OUTPUT-CONN[-TEMP][-CERT]
    # pos_shaft=1, pos_sealing=2(fixed: H1->IP50, H2->IP66), pos_cpr=3
    # has_input_voltage_pos=True at pos5, pos_output=7, pos_connector=8
    # Temp is trailing: T4=0-100C
    "865T": EpcFamilyConfig(
        silver_family="865T", shaft_type="hollow_thru",
        shaft_map={
            "11": 15.875, "34": 19.05, "18": 22.225, "80": 25.4,
            "13": 14.0,   "19": 19.0,  "24": 24.0,
        },
        default_ip=50, default_temp_min_c=0.0, default_temp_max_c=70.0,
        sealing_map={"H1": 50, "H2": 66},
        temp_token_map={"T4": (0.0, 100.0)},
        has_input_voltage_pos=True,
        pos_shaft=1, pos_cpr=3, pos_output=7, pos_connector=8,
        pos_sealing=2, pos_input_voltage=5,
    ),

    # ── TR series — verified from TR1 ordering guide ──────────────────────────
    # Wheel codes (U1/U2/K1/K2/A1/A2) not in shaft_map -> partial decode on bore.
    # TR2/TR3/TRP assumed same structure.
    "TR1": EpcFamilyConfig(
        silver_family="TR1", shaft_type="solid",
        shaft_map={"19": 6.35, "20": 6.0},
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S2": 65, "S3": 66},
        temp_token_map={"T1": (-40.0, 85.0), "T2": (-20.0, 100.0)},
        has_input_voltage_pos=True,
    ),

    "TR2": EpcFamilyConfig(
        silver_family="TR2", shaft_type="solid",
        shaft_map={"19": 6.35, "20": 6.0},
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S2": 65, "S3": 66},
        temp_token_map={"T1": (-40.0, 85.0), "T2": (-20.0, 100.0)},
        has_input_voltage_pos=True,
    ),

    "TR3": EpcFamilyConfig(
        silver_family="TR3", shaft_type="solid",
        shaft_map={"25": 9.525},
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S3": 66, "S4": 67},
        temp_token_map={"T1": (-40.0, 85.0), "T2": (-20.0, 100.0)},
        has_input_voltage_pos=True,
    ),

    # ── TRP — verified from ordering guide ───────────────────────────────────
    # Format: MODEL-WHEEL-MOUNT-CPR-INVOLT-WAVEFORM-OUTPUT-CONN-TEMP-SEAL-CERT
    # NO commutation token (unlike TR1/TR2/TR3) -> positions shift left by one.
    # pos_input_voltage=4, pos_output=6, pos_connector=7
    # Temp at pos8 FIXED (T0=std, T6=extended), Sealing at pos9 FIXED
    # CPR is 6-digit zero-padded (000500=500) — factory-programmed, range 1-100,000
    # Wheel codes (U1/U2/K1/K2/A1/A2/D1/D2) -> no bore in Silver; 19/20 have bore.
    "TRP": EpcFamilyConfig(
        silver_family="TRP", shaft_type="solid",
        shaft_map={"19": 6.35, "20": 6.0},
        default_ip=50, default_temp_min_c=-20.0, default_temp_max_c=85.0,
        sealing_map={"S0": 50, "S2": 65, "S3": 66},
        temp_token_map={"T0": (-20.0, 85.0), "T6": (-40.0, 100.0)},
        has_input_voltage_pos=True,
        pos_shaft=1, pos_cpr=3, pos_output=6, pos_connector=7,
        pos_input_voltage=4, pos_temp=8, pos_sealing=9,
    ),
}


# ── Input voltage supply modifier ─────────────────────────────────────────────

def _apply_input_voltage(output_code: str, iv_token: str) -> tuple[float, float]:
    base_min, base_max = _SUPPLY_VOLTAGE_MAP.get(output_code, (4.75, 28.0))
    if iv_token == "5":
        return base_min, 5.25
    return base_min, base_max


# ── CPR field parser ───────────────────────────────────────────────────────────

def _parse_cpr(token: str) -> Optional[int]:
    if re.match(r"^\d{1,6}$", token):  # up to 6 digits for TRP (100,000 CPR max)
        val = int(token)
        return val if val > 0 else None
    return None


# ── Trailing token scanner ─────────────────────────────────────────────────────

def _scan_trailing_tokens(tokens: list[str], cfg: EpcFamilyConfig) -> dict:
    result = {
        "temp_min": cfg.default_temp_min_c,
        "temp_max": cfg.default_temp_max_c,
        "ip_rating": cfg.default_ip,
    }
    for tok in tokens:
        if not tok or tok in _ALWAYS_IGNORE:
            continue
        if tok in cfg.sealing_map:
            result["ip_rating"] = cfg.sealing_map[tok]
        elif tok in cfg.temp_token_map:
            result["temp_min"], result["temp_max"] = cfg.temp_token_map[tok]
    return result


# ── Main decode function ───────────────────────────────────────────────────────

def decode_epc_order_code(part_number: str) -> Optional[EpcDecodedSpec]:
    """
    Decode a real EPC order code into Silver-queryable parameters.
    Returns None if the model token is not recognised.
    """
    code   = part_number.strip()
    tokens = code.split("-")
    if not tokens:
        return None

    family_token = tokens[0].upper()
    cfg = EPC_FAMILY_CONFIGS.get(family_token)
    if cfg is None:
        return None

    spec = EpcDecodedSpec(
        raw_code=code, family_token=family_token, silver_family=cfg.silver_family,
    )
    spec.shaft_type           = cfg.shaft_type
    spec.ip_rating            = cfg.default_ip
    spec.operating_temp_min_c = cfg.default_temp_min_c
    spec.operating_temp_max_c = cfg.default_temp_max_c

    n = len(tokens)

    # ── shaft_type from variant position (260: B/T/R at pos2) ─────────────────
    if cfg.shaft_variant_pos is not None and n > cfg.shaft_variant_pos:
        spec.shaft_type = cfg.shaft_variant_map.get(
            tokens[cfg.shaft_variant_pos], cfg.shaft_type
        )

    # ── Shaft / bore ──────────────────────────────────────────────────────────
    if n > cfg.pos_shaft:
        shaft_code = tokens[cfg.pos_shaft]
        bore_mm = cfg.shaft_map.get(shaft_code)
        if bore_mm is not None:
            spec.shaft_bore_mm = bore_mm
            # shaft_type override from code (755A: shaft codes -> solid)
            if cfg.shaft_type_by_code:
                spec.shaft_type = cfg.shaft_type_by_code.get(shaft_code, spec.shaft_type)
        else:
            spec.decode_notes.append(f"Unknown shaft code: {shaft_code!r}")

    # ── CPR ───────────────────────────────────────────────────────────────────
    if n > cfg.pos_cpr:
        spec.ppr = _parse_cpr(tokens[cfg.pos_cpr])

    # ── Input voltage (families with has_input_voltage_pos) ───────────────────
    input_voltage_token = None
    if cfg.has_input_voltage_pos and n > cfg.pos_input_voltage:
        input_voltage_token = tokens[cfg.pos_input_voltage]

    # ── Temperature — fixed position ──────────────────────────────────────────
    if cfg.pos_temp is not None and n > cfg.pos_temp:
        tc = tokens[cfg.pos_temp]
        if tc in cfg.temp_token_map:
            spec.operating_temp_min_c, spec.operating_temp_max_c = cfg.temp_token_map[tc]

    # ── Output type ───────────────────────────────────────────────────────────
    if n > cfg.pos_output:
        out_code = tokens[cfg.pos_output].upper()
        if out_code in _OUTPUT_CIRCUIT_MAP:
            spec.output_circuit_canonical, spec.output_voltage_class = \
                _OUTPUT_CIRCUIT_MAP[out_code]
            if cfg.has_input_voltage_pos and input_voltage_token:
                spec.supply_voltage_min_v, spec.supply_voltage_max_v = \
                    _apply_input_voltage(out_code, input_voltage_token)
            else:
                spec.supply_voltage_min_v, spec.supply_voltage_max_v = \
                    _SUPPLY_VOLTAGE_MAP.get(out_code, (4.75, 28.0))
        else:
            spec.decode_notes.append(f"Unknown output type: {out_code!r}")

    # ── Sealing — fixed position ───────────────────────────────────────────────
    if cfg.pos_sealing is not None and n > cfg.pos_sealing:
        sc = tokens[cfg.pos_sealing]
        if sc in cfg.sealing_map:
            spec.ip_rating = cfg.sealing_map[sc]

    # ── Connector ─────────────────────────────────────────────────────────────
    if n > cfg.pos_connector:
        conn_code = tokens[cfg.pos_connector]
        if conn_code in _CONNECTOR_MAP:
            spec.connection_type_canonical, spec.connector_pins = \
                _CONNECTOR_MAP[conn_code]
        else:
            spec.decode_notes.append(f"Unknown connector code: {conn_code!r}")

    # ── Trailing tokens (temp/sealing not at fixed positions) ─────────────────
    trailing_start = cfg.pos_connector + 1
    if n > trailing_start:
        trailing = _scan_trailing_tokens(tokens[trailing_start:], cfg)
        if cfg.pos_temp is None:
            spec.operating_temp_min_c = trailing["temp_min"]
            spec.operating_temp_max_c = trailing["temp_max"]
        if cfg.pos_sealing is None:
            spec.ip_rating = trailing["ip_rating"]

    # ── Decode success ─────────────────────────────────────────────────────────
    if spec.shaft_bore_mm is not None and spec.output_circuit_canonical is not None:
        spec.decode_success = True
    elif spec.ppr is not None:
        spec.decode_notes.append("Partial: PPR known — Stage-3 family+PPR lookup")
    else:
        spec.decode_notes.append("Partial: family only — Stage-4 lookup")

    return spec


# ── Startup validation ─────────────────────────────────────────────────────────

def validate_decoders() -> bool:
    ok = True
    for token, cfg in EPC_FAMILY_CONFIGS.items():
        if not cfg.silver_family:
            print(f"[EPC DECODER] {token}: missing silver_family")
            ok = False
    if ok:
        print(f"[EPC DECODER] validate_decoders OK — {len(EPC_FAMILY_CONFIGS)} families registered")
    return ok


# ── Self-test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    validate_decoders()
    print()

    _TESTS = [
        # 121 — pos_shaft=4, pos_temp=5(fixed), pos_cpr=6, pos_output=8, pos_connector=10
        ("121-N-A-5-01-S-0360-Q-OC-1-S-N",
         "121: bore=01->6.35mm, S temp->0-70C, OC at pos8, S cable at pos10"),
        ("121-N-A-5-11-H-1024-Q-HV-1-S-N",
         "121: bore=11->15.875mm, H temp->0-100C, HV"),

        # 225Q — pos_shaft=1, pos_cpr=2, pos_output=3, pos_sealing=5(fixed), pos_connector=6
        ("225Q-10-100-OC-N-N-K",
         "225Q: bore=10->12.7mm, CPR=100, OC, seal=N->IP50, K M12-8"),
        ("225A-02-050-OC-N-Y-J",
         "225A: bore=02->9.525mm, CPR=50, OC, seal=Y->IP50, J M12-5"),

        # 25SF — pos_shaft=1, pos_cpr=4, pos_output=6, pos_connector=8 (like 58-series)
        ("25SF-38-MA-X-1000-B5-HV-S-MW-T6-S3",
         "25SF: shaft=38->9.525mm, CPR=1000 at pos4, HV at pos6, MW 6-pin MS, T6->-40/100C, S3->IP66"),
        ("25SF-06-MC-X-0512-B5-OC-E-MK",
         "25SF: shaft=06->6mm, OC, MK M12-8, default temp/IP"),

        # 30M — pos_shaft=1, pos_cpr=2, pos_input_voltage=4, pos_output=6, pos_connector=7
        ("30M-01-0256-N-V5-R3-HV-C",
         "30M: bore=01->6.35mm, CPR=0256, V5(5V), HV, C 8-pin Molex"),
        ("30M-02-1024-N-V1-R3-OC-K-S6",
         "30M: bore=02->9.525mm, V1(28V), OC, K M12-8, S6->IP69K trailing"),

        # 30MT — same positions as 30M
        ("30MT-00-0256-N-V1-R3-HV-K",
         "30MT: bore=00->None (partial, no-magnet code), V1, HV, K M12-8"),

        # 770 — pos_shaft=6, pos_temp=2(fixed), pos_cpr=3, pos_output=5, pos_sealing=1(fixed), pos_connector=8
        ("770-A-H-1024-Q-OC-A-Y-K-N-CE",
         "770: housing=A->IP65, H temp->0-100C, OC at pos5, bore=A->15.875mm, K M12-8"),
        ("770-B-S-0512-Q-PP-D-N-P-N",
         "770: housing=B->IP50, S temp->0-70C, PP, bore=D->25.4mm, P gland cable"),

        # 771 — identical layout to 770
        ("771-A-S-1024-Q-HV-A-N-K-N",
         "771: housing=A->IP65, S temp, HV, bore=A->28.575mm, K M12-8"),

        # 865T — pos_shaft=1, pos_sealing=2(fixed), pos_cpr=3, pos_input_voltage=5, pos_output=7, pos_connector=8
        ("865T-34-H1-0500-N-V1-R-OC-F02",
         "865T: bore=34->19.05mm, H1->IP50, CPR=500, V1, OC, F02 cable"),
        ("865T-80-H2-1024-N-V1-R-HV-SMK-T4",
         "865T: bore=80->25.4mm, H2->IP66, V1, HV, SMK M12-8, T4->0-100C trailing"),

        # 802S — verified previously
        ("802S-07-H-2048-R-PP-1-S-1-E-K",
         "802S: shaft=07->6.35mm, H temp, PP, sealing=1->IP66, K M12-8"),

        # Unknown
        ("UNKNOWN-01-1024", "Unknown -> None"),
    ]

    print("-" * 90)
    print(f"EPC DECODER TESTS — {len(EPC_FAMILY_CONFIGS)} families registered")
    print("-" * 90)

    for code, label in _TESTS:
        result = decode_epc_order_code(code)
        if result is None:
            status = "-> None"
        elif not result.decode_success:
            notes = "; ".join(result.decode_notes) or "--"
            status = (f"-> PARTIAL  family={result.silver_family!r}"
                      f"  ppr={result.ppr}  bore={result.shaft_bore_mm}"
                      f"  shaft_type={result.shaft_type}  | {notes}")
        else:
            status = (f"-> OK  bore={result.shaft_bore_mm}mm({result.shaft_type})"
                      f"  {result.output_circuit_canonical}"
                      f"  V={result.supply_voltage_min_v}-{result.supply_voltage_max_v}"
                      f"  {result.connection_type_canonical}(pins={result.connector_pins})"
                      f"  IP{result.ip_rating}"
                      f"  temp={result.operating_temp_min_c}/{result.operating_temp_max_c}C"
                      f"  ppr={result.ppr}")
        print(f"\n  {code}\n    ({label})\n    {status}")