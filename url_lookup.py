"""
url_lookup.py
=============
Resolves product URLs for result cards.

URL strategy per manufacturer:
  Kübler   → derived from family:  kuebler.com/…/product-details/{family}
  EPC      → derived from family:  encoder.com/model-{family_lower}
  Sick     → CSV dict lookup:      sick_urls.csv  (7K rows, keyed by part_number)
  Posital  → CSV dict lookup:      posital_urls.csv (17K rows, keyed by part_number)

AQB Solutions | May 2026
"""

import csv
import os

# ── Full manufacturer display names ──────────────────────────────────────────
MFR_FULL_NAMES = {
    "kubler":                    "Kübler",
    "encoder products company":  "Encoder Products Company",
    "epc":                       "Encoder Products Company",
    "sick":                      "SICK AG",
    "posital":                   "Posital (FRABA)",
}

# ── Runtime URL caches ────────────────────────────────────────────────────────
_SICK_URLS:    dict[str, str] = {}
_POSITAL_URLS: dict[str, str] = {}


def load_sick_urls(path: str = "sick_urls.csv") -> None:
    """Load sick_urls.csv into memory.  Called once at FastAPI startup."""
    global _SICK_URLS
    if not os.path.exists(path):
        print(f"  [url_lookup] WARNING: {path} not found — Sick URLs unavailable")
        return
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pn = row.get("part_number", "").strip()
            url = row.get("product_url", "").strip()
            if pn and url:
                _SICK_URLS[pn] = url
    print(f"  [url_lookup] Loaded {len(_SICK_URLS):,} Sick URLs from {path}")


def load_posital_urls(path: str = "posital_urls.csv") -> None:
    """Load posital_urls.csv into memory.  Called once at FastAPI startup."""
    global _POSITAL_URLS
    if not os.path.exists(path):
        print(f"  [url_lookup] WARNING: {path} not found — Posital URLs unavailable")
        return
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pn = row.get("part_number", "").strip()
            url = row.get("product_url", "").strip()
            if pn and url:
                _POSITAL_URLS[pn] = url
    print(f"  [url_lookup] Loaded {len(_POSITAL_URLS):,} Posital URLs from {path}")


def get_product_url(manufacturer: str, part_number: str, family: str) -> tuple[str, str]:
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
                f"incremental-encoders/product-details/{family}",
                "family",
            )
        return "", "none"

    # ── EPC ───────────────────────────────────────────────────────────────────
    if "encoder products" in mfr or mfr == "epc":
        if family:
            return (
                f"https://www.encoder.com/model-{family.lower()}",
                "family",
            )
        return "", "none"

    # ── Sick ──────────────────────────────────────────────────────────────────
    if "sick" in mfr:
        if part_number and part_number in _SICK_URLS:
            return _SICK_URLS[part_number], "exact"
        # Fallback to Sick product search
        return (
            f"https://www.sick.com/us/en/search?text={part_number}",
            "search",
        )

    # ── Posital ───────────────────────────────────────────────────────────────
    if "posital" in mfr:
        if part_number and part_number in _POSITAL_URLS:
            return _POSITAL_URLS[part_number], "exact"
        # Fallback to Posital search
        return (
            f"https://www.posital.com/en/search/?q={part_number}",
            "search",
        )

    return "", "none"
