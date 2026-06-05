"""
url_lookup.py
=============
Resolves product URLs for result cards.

URL strategy per manufacturer:
  Kübler   -> family-based: kuebler.com/product-finder/product-details/{family}
  EPC      -> family-based with override dict for non-standard slugs (TRU-TRAC series)
  Sick     -> CSV dict lookup:  sick_urls.csv  (keyed by part_number)
  Posital  -> CSV dict lookup:  posital_urls.csv (keyed by part_number)
  Lika     -> derived from source_datasheet PDF name

AQB Solutions | June 2026
"""

import csv
import os
import re

# ── Full manufacturer display names ──────────────────────────────────────────
MFR_FULL_NAMES = {
    "kubler":                    "Kübler",
    "encoder products company":  "Encoder Products Company",
    "epc":                       "Encoder Products Company",
    "sick":                      "SICK AG",
    "posital":                   "Posital (FRABA)",
    "lika":                      "Lika Electronic Srl",
}

# ── EPC family URL overrides ─────────────────────────────────────────────────
# Most EPC families follow the pattern encoder.com/model-{family.lower()}.
# The TRU-TRAC series has non-standard slugs that don't follow this pattern.
EPC_FAMILY_URL_OVERRIDES: dict[str, str] = {
    "TR1": "https://www.encoder.com/model-tr1-tru-trac",
    "TR2": "https://www.encoder.com/model-tr2-tru-trac",
    "TR3": "https://www.encoder.com/model-tr3-tru-trac",
    "TRP": "https://www.encoder.com/trp-tru-trac-pro",
}

# ── Runtime URL caches ────────────────────────────────────────────────────────
_SICK_URLS:    dict[str, str] = {}
_POSITAL_URLS: dict[str, str] = {}


def load_sick_urls(path: str = "sick_urls.csv") -> None:
    """Load sick_urls.csv into memory. Called once at FastAPI startup."""
    global _SICK_URLS
    if not os.path.exists(path):
        print(f"  [url_lookup] WARNING: {path} not found — Sick URLs unavailable")
        return
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pn  = row.get("part_number", "").strip()
            url = row.get("product_url", "").strip()
            if pn and url:
                _SICK_URLS[pn] = url
    print(f"  [url_lookup] Loaded {len(_SICK_URLS):,} Sick URLs from {path}")


def load_posital_urls(path: str = "posital_urls.csv") -> None:
    """Load posital_urls.csv into memory. Called once at FastAPI startup."""
    global _POSITAL_URLS
    if not os.path.exists(path):
        print(f"  [url_lookup] WARNING: {path} not found — Posital URLs unavailable")
        return
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pn  = row.get("part_number", "").strip()
            url = row.get("product_url", "").strip()
            if pn and url:
                _POSITAL_URLS[pn] = url
    print(f"  [url_lookup] Loaded {len(_POSITAL_URLS):,} Posital URLs from {path}")


def _lika_url(source_datasheet: str) -> str:
    """
    Derive Lika product URL from PDF filename stored in Silver source_datasheet.

    CAT-C100-E.pdf           -> https://www.lika.it/.../incremental/c100
    CAT-CK58_CK59_CK60-E.pdf -> https://www.lika.it/.../incremental/ck58-ck59-ck60
    CAT-I28-E.pdf            -> https://www.lika.it/.../incremental/i28
    """
    if not source_datasheet:
        return ""
    slug = source_datasheet
    slug = re.sub(r"^CAT-",   "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"-E\.pdf$", "", slug, flags=re.IGNORECASE)
    slug = slug.replace("_", "-").lower()
    return f"https://www.lika.it/eng/products/rotary-encoders/incremental/{slug}"


def get_product_url(
    manufacturer:     str,
    part_number:      str,
    family:           str,
    source_datasheet: str = "",
) -> tuple[str, str]:
    """
    Return (url, url_type) for a Silver result row.
    url_type: 'exact' | 'family' | 'search' | 'none'
    """
    mfr = manufacturer.lower().strip()

    # ── Kübler ───────────────────────────────────────────────────────────────
    if "kubler" in mfr or "kübler" in mfr:
        if family:
            return (
                f"https://www.kuebler.com/en/products/measurement/encoders/"
                f"product-finder/product-details/{family}",
                "family",
            )
        return "", "none"

    # ── EPC ───────────────────────────────────────────────────────────────────
    if "encoder products" in mfr or mfr == "epc":
        if family:
            # Check override dict first (TRU-TRAC series has non-standard slugs)
            if family in EPC_FAMILY_URL_OVERRIDES:
                return EPC_FAMILY_URL_OVERRIDES[family], "family"
            return (
                f"https://www.encoder.com/model-{family.lower()}",
                "family",
            )
        return "", "none"

    # ── Sick ──────────────────────────────────────────────────────────────────
    if "sick" in mfr:
        if part_number and part_number in _SICK_URLS:
            return _SICK_URLS[part_number], "exact"
        return (
            f"https://www.sick.com/us/en/search?text={part_number}",
            "search",
        )

    # ── Posital ───────────────────────────────────────────────────────────────
    if "posital" in mfr:
        if part_number and part_number in _POSITAL_URLS:
            return _POSITAL_URLS[part_number], "exact"
        return (
            f"https://www.posital.com/en/search/?q={part_number}",
            "search",
        )

    # ── Lika ─────────────────────────────────────────────────────────────────
    if "lika" in mfr:
        url = _lika_url(source_datasheet)
        return (url, "family") if url else ("", "none")

    return "", "none"