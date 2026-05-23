"""
TextileSearch — Field Parser

Converts raw OCR text from a textile label into structured fields.
Every field is extracted independently — field order on the label is irrelevant.

Design principles (strict):
  - Every function is fully typed with explicit return types
  - No bare `except:` — all exceptions are caught by specific type
  - No implicit Optional — every nullable field is explicitly Optional[X]
  - All field results carry a confidence score (0.0–1.0) and a tier (1/2/3)
  - The composition sum check is hardcoded (non-configurable) — it always
    forces Tier 2 if percentages don't sum to 100% (±2% tolerance)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Final, Literal

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

TIER_1_THRESHOLD: Final[float] = 0.90
TIER_2_THRESHOLD: Final[float] = 0.65
COMPOSITION_SUM_TOLERANCE: Final[float] = 2.0   # ±2% before flagging

Tier = Literal[1, 2, 3]

# ─────────────────────────────────────────────────────────────────────────────
# Result types  (frozen dataclasses → immutable after construction)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FieldResult:
    """Result for a single scalar field."""
    value: str | float | None
    confidence: float
    tier: Tier
    raw_fragment: str           # the substring of OCR text that matched


@dataclass(frozen=True)
class CompositionComponent:
    material: str               # normalised name, e.g. "POLYESTER"
    material_raw: str           # as it appeared in OCR, e.g. "POLYSTEER"
    percentage: float           # e.g. 87.0
    tier: Tier


@dataclass(frozen=True)
class CompositionResult:
    components: list[CompositionComponent]
    confidence: float
    tier: Tier
    construction_descriptor: str | None   # e.g. "TWO LAYER FABRIC" extracted from Format B
    percentage_sum: float
    sum_ok: bool                          # True if sum is within ±2% of 100


@dataclass(frozen=True)
class ParsedLabel:
    """Complete parsed result for one label image."""
    supplier:           FieldResult
    item_no:            FieldResult
    order_no:           FieldResult
    fabric_type:        FieldResult
    construction:       FieldResult
    composition:        CompositionResult
    width_min:          FieldResult
    width_max:          FieldResult
    width_unit:         FieldResult
    weight_gsm:         FieldResult
    weight_gyd:         FieldResult
    tolerance_pct:      FieldResult
    needs_review:       bool
    no_label_detected:  bool

    @property
    def any_tier_2_or_3(self) -> bool:
        scalar_fields = [
            self.supplier, self.item_no, self.order_no, self.fabric_type,
            self.construction, self.width_min, self.width_max, self.width_unit,
            self.weight_gsm, self.weight_gyd, self.tolerance_pct,
        ]
        return (
            any(f.tier >= 2 for f in scalar_fields)
            or self.composition.tier >= 2
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tier assignment
# ─────────────────────────────────────────────────────────────────────────────

def assign_tier(confidence: float) -> Tier:
    if confidence >= TIER_1_THRESHOLD:
        return 1
    if confidence >= TIER_2_THRESHOLD:
        return 2
    return 3


def make_field(
    value: str | float | None,
    confidence: float,
    raw_fragment: str = "",
) -> FieldResult:
    return FieldResult(
        value=value,
        confidence=confidence,
        tier=assign_tier(confidence),
        raw_fragment=raw_fragment,
    )


def empty_field() -> FieldResult:
    """A field that was not found in the OCR text."""
    return FieldResult(value=None, confidence=0.0, tier=3, raw_fragment="")


# ─────────────────────────────────────────────────────────────────────────────
# Material normalisation
# ─────────────────────────────────────────────────────────────────────────────

# Built-in alias table. The DB table `material_aliases` extends this at runtime.
# Key: uppercase OCR text → Value: canonical material name
_BUILTIN_ALIASES: Final[dict[str, str]] = {
    "POLYSTEER":     "POLYESTER",
    "POLYSTER":      "POLYESTER",
    "POIYESTER":     "POLYESTER",
    "POLY":          "POLYESTER",
    "PES":           "POLYESTER",
    "PET":           "POLYESTER",
    "SPUNPOLYSTER":  "SPUNPOLYESTER",
    "SPUNPOLY":      "SPUNPOLYESTER",
    "RYON":          "RAYON",
    "RY":            "RAYON",
    "VISCOSE":       "RAYON",
    "SP":            "SPANDEX",
    "EA":            "SPANDEX",
    "ELASTANE":      "SPANDEX",
    "LYCRA":         "SPANDEX",
    "WL":            "WOOL",
    "WO":            "WOOL",
    "CT":            "COTTON",
    "CTN":           "COTTON",
    "CO":            "COTTON",
    "NY":            "NYLON",
    "PA":            "NYLON",
    "ACRY":          "ACRYLIC",
    "AC":            "ACRYLIC",
    "PAN":           "ACRYLIC",
    "LI":            "LINEN",
    "FLAX":          "LINEN",
    "LX":            "LUREX",
    "METALLIC":      "LUREX",
}

# Runtime-overridable alias table (merged from DB on startup)
_runtime_aliases: dict[str, str] = {}


def load_runtime_aliases(aliases: dict[str, str]) -> None:
    """
    Called once at startup from the DB material_aliases table.
    Merges with built-in aliases; DB values take precedence.
    """
    _runtime_aliases.clear()
    _runtime_aliases.update(_BUILTIN_ALIASES)
    _runtime_aliases.update({k.upper(): v.upper() for k, v in aliases.items()})


def normalise_material(raw: str) -> str:
    """
    Normalise an OCR material name to its canonical form.
    Falls back to the uppercased raw string if no alias found.
    """
    upper = raw.strip().upper()
    return _runtime_aliases.get(upper, _BUILTIN_ALIASES.get(upper, upper))


# ─────────────────────────────────────────────────────────────────────────────
# Known vocabulary lists
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_FABRIC_TYPES: Final[frozenset[str]] = frozenset({
    "TWEED", "JERSEY", "DENIM", "CHIFFON", "SATIN", "VELVET",
    "LACE", "KNIT", "WOVEN", "FLEECE", "BROCADE", "CREPE",
    "ORGANZA", "TAFFETA", "GEORGETTE", "POPLIN", "CANVAS",
    "CORDUROY", "MUSLIN", "VOILE", "LAWN", "FLANNEL", "MESH",
    "INTERLOCK", "PIQUE", "PONTE", "SCUBA", "TERRY", "VELOUR",
})

# Updated at runtime if the DB fabric_types table has additions
_runtime_fabric_types: set[str] = set(KNOWN_FABRIC_TYPES)


def load_runtime_fabric_types(types: set[str]) -> None:
    _runtime_fabric_types.clear()
    _runtime_fabric_types.update(KNOWN_FABRIC_TYPES)
    _runtime_fabric_types.update({t.upper() for t in types})


# ─────────────────────────────────────────────────────────────────────────────
# Individual field extractors
# ─────────────────────────────────────────────────────────────────────────────

# ── Supplier ──────────────────────────────────────────────────────────────────

_COMPANY_INDICATORS: Final[re.Pattern[str]] = re.compile(
    r"\b(CO\.?\s*LTD|INC\.?|CORP\.?|TEXTILES?|FABRICS?|GROUP|MFG|INDUSTRY|INDUSTRIES|TRADING)\b",
    re.IGNORECASE,
)

_ALL_CAPS_LINE: Final[re.Pattern[str]] = re.compile(
    r"^([A-Z][A-Z\s\.\,\&\-]{3,60})$",
    re.MULTILINE,
)


def extract_supplier(text: str) -> FieldResult:
    """
    Extract the supplier/manufacturer name.

    Strategy:
      1. Find ALL-CAPS lines containing company indicators → confidence 0.93
      2. Find any ALL-CAPS line (first one) as fallback → confidence 0.70
      3. Not found → empty field
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Strategy 1: line with known company indicator
    for line in lines:
        if _COMPANY_INDICATORS.search(line) and line.isupper():
            return make_field(line.strip(), confidence=0.93, raw_fragment=line)

    # Strategy 2: first ALL-CAPS line with > 3 words
    for match in _ALL_CAPS_LINE.finditer(text):
        candidate = match.group(1).strip()
        if len(candidate.split()) >= 2:
            return make_field(candidate, confidence=0.70, raw_fragment=candidate)

    return empty_field()


# ── Reference numbers (Item No / Order No) ───────────────────────────────────

_ITEM_NO_PREFIXES: Final[str] = (
    r"(?:ITEM\s*(?:NO\.?|NUMBER|#)|STYLE\s*(?:NO\.?)?|ART\.?\s*(?:NO\.?)?|"
    r"REF\.?\s*(?:NO\.?)?|CODE\s*(?:NO\.?)?|NO\.)"
)

_ORDER_NO_PREFIXES: Final[str] = (
    r"(?:ORDER\s*(?:NO\.?|NUMBER|#)?|ORD\.?\s*(?:NO\.?)?|P/?O\.?\s*(?:NO\.?)?|"
    r"PURCHASE\s*ORDER)"
)

_REF_VALUE: Final[str] = r"[ \t]*[:\-#]?[ \t]*([A-Z0-9][^\n]{0,49})"

_ITEM_NO_RE: Final[re.Pattern[str]] = re.compile(
    _ITEM_NO_PREFIXES + _REF_VALUE,
    re.IGNORECASE,
)
_ORDER_NO_RE: Final[re.Pattern[str]] = re.compile(
    _ORDER_NO_PREFIXES + _REF_VALUE,
    re.IGNORECASE,
)

# Splits multi-column whitespace runs (3+ spaces = column separator)
_COLUMN_SPLIT: Final[re.Pattern[str]] = re.compile(r"\s{3,}")


def _extract_reference(pattern: re.Pattern[str], text: str) -> FieldResult:
    match = pattern.search(text)
    if not match:
        return empty_field()

    raw_value = match.group(1).strip()

    # Multi-column artefact: "H19099        -24" split by whitespace
    # Collapse runs of 2+ spaces, but detect if there are multiple parts
    parts = _COLUMN_SPLIT.split(raw_value)

    if len(parts) == 1:
        # Single-part value: extract the ref number token (alphanumeric + dash)
        token_match = re.match(r"([A-Z0-9][\w\-]{0,24})", raw_value.strip(), re.IGNORECASE)
        clean = token_match.group(1).rstrip(".,") if token_match else raw_value.strip()
        return make_field(clean, confidence=0.92, raw_fragment=raw_value)

    # Multiple whitespace-separated parts: take first token
    token_match = re.match(r"([A-Z0-9][\w\-]{0,24})", parts[0].strip(), re.IGNORECASE)
    clean = token_match.group(1).rstrip(".,") if token_match else parts[0].strip()
    logger.debug(
        "Reference number split detected",
        extra={"taken": clean, "extra_parts": parts[1:]},
    )
    return make_field(clean, confidence=0.72, raw_fragment=raw_value)


def extract_item_no(text: str) -> tuple[FieldResult, list[str]]:
    """
    Returns (item_no_field, extra_ref_fragments).
    extra_ref_fragments contains any additional reference strings
    found after the primary value (e.g. page numbers, batch codes).
    """
    match = _ITEM_NO_RE.search(text)
    if not match:
        return empty_field(), []

    raw_value = match.group(1).strip()
    parts = _COLUMN_SPLIT.split(raw_value)
    token_match = re.match(r"([A-Z0-9][\w\-]{0,24})", parts[0].strip(), re.IGNORECASE)
    primary = token_match.group(1).rstrip(".,") if token_match else parts[0].strip()

    confidence = 0.92 if len(parts) == 1 else 0.72
    return make_field(primary, confidence, raw_fragment=raw_value), parts[1:]


def extract_order_no(text: str) -> FieldResult:
    return _extract_reference(_ORDER_NO_RE, text)


# ── Composition ───────────────────────────────────────────────────────────────

# Format A: "87/10/2/1 POLYSTEER/RAYON/LUREX/SPANDEX"
_COMP_FORMAT_A: Final[re.Pattern[str]] = re.compile(
    r"(\d+(?:/\d+)+)\s+([A-Z]+(?:/[A-Z]+)+)",
    re.IGNORECASE,
)

# Format B: "100% SPUNPOLYSTER TWO LAYER FABRIC" — single material, trailing descriptor
_COMP_FORMAT_B: Final[re.Pattern[str]] = re.compile(
    r"(\d{1,3})%\s+([A-Z]+(?:\s+[A-Z]+){0,4})",
    re.IGNORECASE,
)

# Format C: "POLYESTER 60% COTTON 40%" — material before percentage
_COMP_FORMAT_C: Final[re.Pattern[str]] = re.compile(
    r"([A-Z]{2,})\s+(\d{1,3})%",
    re.IGNORECASE,
)


def _components_from_format_a(
    pct_str: str, mat_str: str
) -> list[CompositionComponent] | None:
    """Parse "87/10/2/1" + "POLY/RAYON/LUREX/SP" into component list."""
    pcts = [float(p) for p in pct_str.split("/")]
    mats = [m.strip().upper() for m in mat_str.split("/")]
    if len(pcts) != len(mats):
        return None
    return [
        CompositionComponent(
            material=normalise_material(m),
            material_raw=m,
            percentage=p,
            tier=1,         # adjusted to 2 later if sum ≠ 100%
        )
        for p, m in zip(pcts, mats)
    ]


def _check_sum(components: list[CompositionComponent]) -> tuple[float, bool]:
    total = sum(c.percentage for c in components)
    ok = abs(total - 100.0) <= COMPOSITION_SUM_TOLERANCE
    return total, ok


def _apply_sum_tier(
    components: list[CompositionComponent], sum_ok: bool
) -> list[CompositionComponent]:
    """If sum is wrong, force all components to Tier 2."""
    if sum_ok:
        return components
    return [
        CompositionComponent(
            material=c.material,
            material_raw=c.material_raw,
            percentage=c.percentage,
            tier=2,
        )
        for c in components
    ]


def extract_composition(text: str) -> CompositionResult:
    """
    Tries all three formats. Returns the highest-confidence parse.
    If percentages do not sum to 100% (±2%), the result is always Tier 2.
    """
    candidates: list[CompositionResult] = []

    # ── Format A: "87/10/2/1 POLY/RAYON/LUREX/SP" ────────────────────────────
    for match in _COMP_FORMAT_A.finditer(text):
        components = _components_from_format_a(match.group(1), match.group(2))
        if components is None:
            continue
        total, sum_ok = _check_sum(components)
        components = _apply_sum_tier(components, sum_ok)
        confidence = 0.90 if sum_ok else 0.55
        # Hardcoded rule: sum != 100% ALWAYS forces Tier 2 (requires user confirmation)
        tier: Tier = 1 if sum_ok else 2
        candidates.append(CompositionResult(
            components=components,
            confidence=confidence,
            tier=tier,
            construction_descriptor=None,
            percentage_sum=total,
            sum_ok=sum_ok,
        ))

    # ── Format B: "100% SPUNPOLYSTER TWO LAYER FABRIC" ───────────────────────
    for match in _COMP_FORMAT_B.finditer(text):
        pct = float(match.group(1))
        mat_words = match.group(2).strip().upper().split()
        if not mat_words:
            continue

        material_raw = mat_words[0]
        material     = normalise_material(material_raw)
        descriptor   = " ".join(mat_words[1:]) if len(mat_words) > 1 else None

        # Only accept Format B if the percentage looks like 100% or makes sense
        sum_ok = abs(pct - 100.0) <= COMPOSITION_SUM_TOLERANCE
        confidence = 0.85 if sum_ok else 0.60
        # Hardcoded rule: sum != 100% ALWAYS forces Tier 2
        tier: Tier = 1 if sum_ok else 2

        component = CompositionComponent(
            material=material,
            material_raw=material_raw,
            percentage=pct,
            tier=tier,
        )
        candidates.append(CompositionResult(
            components=[component],
            confidence=confidence,
            tier=tier,
            construction_descriptor=descriptor,
            percentage_sum=pct,
            sum_ok=sum_ok,
        ))

    # ── Format C: "POLYESTER 60% COTTON 40%" ──────────────────────────────────
    matches_c = _COMP_FORMAT_C.findall(text)
    if len(matches_c) >= 2:
        components_c = [
            CompositionComponent(
                material=normalise_material(mat),
                material_raw=mat.upper(),
                percentage=float(pct),
                tier=1,
            )
            for mat, pct in matches_c
        ]
        total, sum_ok = _check_sum(components_c)
        components_c = _apply_sum_tier(components_c, sum_ok)
        confidence = 0.88 if sum_ok else 0.55
        # Hardcoded rule: sum != 100% ALWAYS forces Tier 2
        tier_c: Tier = 1 if sum_ok else 2
        candidates.append(CompositionResult(
            components=components_c,
            confidence=confidence,
            tier=tier_c,
            construction_descriptor=None,
            percentage_sum=total,
            sum_ok=sum_ok,
        ))

    if not candidates:
        return CompositionResult(
            components=[],
            confidence=0.0,
            tier=3,
            construction_descriptor=None,
            percentage_sum=0.0,
            sum_ok=False,
        )

    # Return highest-confidence candidate
    return max(candidates, key=lambda r: r.confidence)


# ── Fabric type ───────────────────────────────────────────────────────────────

def extract_fabric_type(text: str) -> FieldResult:
    """
    Find a known fabric type keyword anywhere in the text.
    Prioritises matches at end-of-line (common label format).
    """
    upper = text.upper()

    # Check end-of-line first (highest confidence)
    for line in upper.splitlines():
        stripped = line.strip()
        for fabric in _runtime_fabric_types:
            if stripped.endswith(fabric):
                return make_field(fabric, confidence=0.91, raw_fragment=stripped)

    # Check anywhere in text (lower confidence)
    for fabric in _runtime_fabric_types:
        if fabric in upper:
            return make_field(fabric, confidence=0.72, raw_fragment=fabric)

    return empty_field()


# ── Width / Height ────────────────────────────────────────────────────────────

_WIDTH_RE: Final[re.Pattern[str]] = re.compile(
    r"""
    (?:WIDTH(?:/HEIGHT)?|W/H|W\.?|WIDE)\s*[:\-]?\s*  # prefix
    (\d+(?:\.\d+)?)\s*                                # first number (width_min)
    (?:[/\-]\s*(\d+(?:\.\d+)?))?                     # optional second number (width_max)
    \s*
    (CM|IN(?:CH(?:ES)?)?|")?                          # optional unit
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Also match bare dimensions like: 66/68"
_BARE_WIDTH_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d{2,3})\s*/\s*(\d{2,3})\s*(\"|\bIN\b|\bCM\b)?",
    re.IGNORECASE,
)


def extract_width(
    text: str,
) -> tuple[FieldResult, FieldResult, FieldResult]:
    """
    Returns (width_min_field, width_max_field, width_unit_field).
    width_max == width_min when only one value is present.
    """
    # Strategy 1: explicit width prefix
    match = _WIDTH_RE.search(text)
    if match:
        min_val = float(match.group(1))
        max_val = float(match.group(2)) if match.group(2) else min_val
        unit_raw = match.group(3) or ""
        unit = _normalise_unit(unit_raw)
        confidence = 0.91 if match.group(2) else 0.88
        return (
            make_field(min_val, confidence, raw_fragment=match.group(0)),
            make_field(max_val, confidence, raw_fragment=match.group(0)),
            make_field(unit or None, 0.85 if unit else 0.40, raw_fragment=unit_raw),
        )

    # Strategy 2: bare "NN/NN" pattern (e.g. "66/68\"")
    match2 = _BARE_WIDTH_RE.search(text)
    if match2:
        min_val = float(match2.group(1))
        max_val = float(match2.group(2))
        unit_raw = match2.group(3) or ""
        unit = _normalise_unit(unit_raw)
        # Lower confidence — pattern is ambiguous without prefix
        return (
            make_field(min_val, 0.78, raw_fragment=match2.group(0)),
            make_field(max_val, 0.78, raw_fragment=match2.group(0)),
            make_field(unit or None, 0.80 if unit else 0.30, raw_fragment=unit_raw),
        )

    return empty_field(), empty_field(), empty_field()


def _normalise_unit(raw: str) -> str:
    u = raw.strip().upper().rstrip(".")
    if u in ('"', "INCH", "INCHES", "IN"):
        return "IN"
    if u == "CM":
        return "CM"
    return ""


# ── Weight ────────────────────────────────────────────────────────────────────

_GSM_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:G/M2|G/M²|GSM|GR/M2|G/SQM)",
    re.IGNORECASE,
)

# GSM in parentheses: "286G/YD (170GSM)"
_GSM_PAREN_RE: Final[re.Pattern[str]] = re.compile(
    r"\(\s*(\d+(?:\.\d+)?)\s*GSM\s*\)",
    re.IGNORECASE,
)

_GYD_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d+(?:\.\d+)?)\s*G/YD",
    re.IGNORECASE,
)

_TOLERANCE_RE: Final[re.Pattern[str]] = re.compile(
    r"[+\-±]{1,2}\s*(\d+(?:\.\d+)?)\s*%",
)


def extract_weights(
    text: str,
) -> tuple[FieldResult, FieldResult, FieldResult]:
    """
    Returns (weight_gsm_field, weight_gyd_field, tolerance_pct_field).
    Both weight types are extracted independently — a label may have both.
    """
    # GSM — explicit suffix first
    gsm_field = empty_field()
    match = _GSM_RE.search(text)
    if match:
        gsm_field = make_field(float(match.group(1)), confidence=0.95, raw_fragment=match.group(0))
    else:
        # GSM in parentheses
        match2 = _GSM_PAREN_RE.search(text)
        if match2:
            gsm_field = make_field(
                float(match2.group(1)), confidence=0.88, raw_fragment=match2.group(0)
            )

    # G/YD
    gyd_field = empty_field()
    match3 = _GYD_RE.search(text)
    if match3:
        gyd_field = make_field(
            float(match3.group(1)), confidence=0.90, raw_fragment=match3.group(0)
        )

    # Tolerance
    tol_field = empty_field()
    match4 = _TOLERANCE_RE.search(text)
    if match4:
        tol_field = make_field(
            float(match4.group(1)), confidence=0.92, raw_fragment=match4.group(0)
        )

    return gsm_field, gyd_field, tol_field


# ── Construction ─────────────────────────────────────────────────────────────

_KNOWN_CONSTRUCTIONS: Final[frozenset[str]] = frozenset({
    "TWO LAYER", "THREE LAYER", "DOUBLE LAYER", "SINGLE LAYER",
    "HONEYCOMB", "MESH", "KNIT", "WARP KNIT", "WEFT KNIT",
    "PLAIN WEAVE", "TWILL", "SATIN WEAVE",
})

_CONSTRUCTION_CODE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:MESH|KNIT|WEAVE|KNT)\s*-?\s*([A-Z0-9]{2,8})",
    re.IGNORECASE,
)


def extract_construction(text: str) -> tuple[FieldResult, FieldResult]:
    """
    Returns (construction_field, construction_code_field).
    Construction is the fabric structure descriptor ("TWO LAYER", "HONEYCOMB MESH").
    Construction code is a variant identifier ("2042" from "KNT -2042").
    """
    upper = text.upper()
    found_constructions: list[str] = []

    for kw in _KNOWN_CONSTRUCTIONS:
        if kw in upper:
            found_constructions.append(kw)

    if not found_constructions:
        return empty_field(), empty_field()

    construction_value = " / ".join(found_constructions)
    const_field = make_field(construction_value, confidence=0.82, raw_fragment=construction_value)

    # Construction code (e.g. "-2042")
    code_match = _CONSTRUCTION_CODE_RE.search(text)
    code_field = (
        make_field(code_match.group(1), confidence=0.78, raw_fragment=code_match.group(0))
        if code_match else empty_field()
    )

    return const_field, code_field


# ─────────────────────────────────────────────────────────────────────────────
# Top-level parser
# ─────────────────────────────────────────────────────────────────────────────

NO_TEXT_CONFIDENCE_THRESHOLD: Final[float] = 0.30
NO_TEXT_MIN_CHARS: Final[int] = 5


def parse_label(ocr_text: str) -> ParsedLabel:
    """
    Parse raw OCR text into structured fields.

    This is the main entry point. All fields are extracted independently.
    No exception is raised for missing or low-confidence fields — every field
    always returns a FieldResult (possibly with value=None and tier=3).

    Args:
        ocr_text: Full text output from PaddleOCR, newlines preserved.

    Returns:
        ParsedLabel with all fields populated and needs_review computed.
    """
    text = ocr_text.strip()

    # Detect completely empty / unreadable label
    no_label = len(text) < NO_TEXT_MIN_CHARS
    if no_label:
        return _empty_parsed_label(no_label_detected=True)

    supplier_field   = extract_supplier(text)
    item_field, _    = extract_item_no(text)
    order_field      = extract_order_no(text)
    fabric_field     = extract_fabric_type(text)
    const_field, const_code_field = extract_construction(text)
    composition      = extract_composition(text)
    w_min, w_max, w_unit = extract_width(text)
    gsm, gyd, tol   = extract_weights(text)

    parsed = ParsedLabel(
        supplier=supplier_field,
        item_no=item_field,
        order_no=order_field,
        fabric_type=fabric_field,
        construction=const_field,
        composition=composition,
        width_min=w_min,
        width_max=w_max,
        width_unit=w_unit,
        weight_gsm=gsm,
        weight_gyd=gyd,
        tolerance_pct=tol,
        needs_review=False,      # computed below
        no_label_detected=False,
    )

    return ParsedLabel(
        supplier=parsed.supplier,
        item_no=parsed.item_no,
        order_no=parsed.order_no,
        fabric_type=parsed.fabric_type,
        construction=parsed.construction,
        composition=parsed.composition,
        width_min=parsed.width_min,
        width_max=parsed.width_max,
        width_unit=parsed.width_unit,
        weight_gsm=parsed.weight_gsm,
        weight_gyd=parsed.weight_gyd,
        tolerance_pct=parsed.tolerance_pct,
        needs_review=parsed.any_tier_2_or_3,
        no_label_detected=False,
    )


def _empty_parsed_label(no_label_detected: bool = False) -> ParsedLabel:
    empty_comp = CompositionResult(
        components=[], confidence=0.0, tier=3,
        construction_descriptor=None, percentage_sum=0.0, sum_ok=False,
    )
    return ParsedLabel(
        supplier=empty_field(), item_no=empty_field(), order_no=empty_field(),
        fabric_type=empty_field(), construction=empty_field(), composition=empty_comp,
        width_min=empty_field(), width_max=empty_field(), width_unit=empty_field(),
        weight_gsm=empty_field(), weight_gyd=empty_field(), tolerance_pct=empty_field(),
        needs_review=not no_label_detected,
        no_label_detected=no_label_detected,
    )
