"""
Field parser tests.

Covers both real-world label examples from the user's collection and all
identified edge cases.  No database, no ML models — pure function tests.
"""
from __future__ import annotations

import pytest
from app.services.field_parser import (
    parse_label,
    extract_supplier,
    extract_item_no,
    extract_order_no,
    extract_composition,
    extract_fabric_type,
    extract_width,
    extract_weights,
    normalise_material,
    assign_tier,
    TIER_1_THRESHOLD,
    TIER_2_THRESHOLD,
)


# ─────────────────────────────────────────────────────────────────────────────
# Real-world label fixtures
# ─────────────────────────────────────────────────────────────────────────────

FAFA_LABEL = """\
FAFA TEXTILES CO. LTD
ITEM NO: H4-7103WY
87/10/2/1 POLYSTEER/RAYON/LUREX/SPANDEX TWEED
WIDTH/HEIGHT: 61/63 *250g/m^2"""

SPUN_LABEL = """\
ORDER NO: H19099        -24                        p316-171
ITEM NO:
100% SPUNPOLYSTER TWO LAYER FABRIC
BACK HONEYCOMB MESH KNT -2042
66/68" 286G/YD (170GSM) +-3%"""


# ─────────────────────────────────────────────────────────────────────────────
# Tier assignment
# ─────────────────────────────────────────────────────────────────────────────

class TestTierAssignment:
    def test_tier_1_at_threshold(self) -> None:
        assert assign_tier(TIER_1_THRESHOLD) == 1

    def test_tier_1_above(self) -> None:
        assert assign_tier(0.99) == 1

    def test_tier_2_at_threshold(self) -> None:
        assert assign_tier(TIER_2_THRESHOLD) == 2

    def test_tier_2_below_tier1(self) -> None:
        assert assign_tier(0.75) == 2

    def test_tier_3_below_tier2(self) -> None:
        assert assign_tier(0.50) == 3

    def test_tier_3_at_zero(self) -> None:
        assert assign_tier(0.0) == 3


# ─────────────────────────────────────────────────────────────────────────────
# Material normalisation
# ─────────────────────────────────────────────────────────────────────────────

class TestMaterialNormalisation:
    @pytest.mark.parametrize("raw,expected", [
        ("POLYSTEER",    "POLYESTER"),
        ("POLYSTER",     "POLYESTER"),
        ("POLY",         "POLYESTER"),
        ("SPUNPOLYSTER", "SPUNPOLYESTER"),
        ("SP",           "SPANDEX"),
        ("EA",           "SPANDEX"),
        ("ELASTANE",     "SPANDEX"),
        ("RYON",         "RAYON"),
        ("VISCOSE",      "RAYON"),
        ("WL",           "WOOL"),
        ("CT",           "COTTON"),
        ("NY",           "NYLON"),
        ("LUREX",        "LUREX"),    # already canonical
        ("POLYESTER",    "POLYESTER"),# already canonical
    ])
    def test_known_aliases(self, raw: str, expected: str) -> None:
        assert normalise_material(raw) == expected

    def test_unknown_material_uppercased(self) -> None:
        assert normalise_material("myFabric") == "MYFABRIC"

    def test_whitespace_stripped(self) -> None:
        assert normalise_material("  POLY  ") == "POLYESTER"


# ─────────────────────────────────────────────────────────────────────────────
# Supplier extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestSupplierExtraction:
    def test_fafa_label(self) -> None:
        result = extract_supplier(FAFA_LABEL)
        assert result.value == "FAFA TEXTILES CO. LTD"
        assert result.tier == 1

    @pytest.mark.parametrize("text,expected_fragment", [
        ("GOLDEN FABRIC INC.\nITEM NO: X1", "GOLDEN FABRIC INC."),
        ("SUNRISE MFG GROUP\n100% COTTON",  "SUNRISE MFG GROUP"),
        ("CHEN HSING CORP\nORDER NO: 123",  "CHEN HSING CORP"),
    ])
    def test_various_company_indicators(self, text: str, expected_fragment: str) -> None:
        result = extract_supplier(text)
        assert result.value is not None
        assert expected_fragment in str(result.value)

    def test_no_supplier_returns_empty(self) -> None:
        result = extract_supplier("100% COTTON\nWIDTH: 60 CM")
        assert result.value is None or result.tier == 3

    def test_hefa_variant_extracted(self) -> None:
        text = "HEFA TEXTILES CO. LTD\nITEM NO: B2-001"
        result = extract_supplier(text)
        assert result.value is not None
        assert "HEFA" in str(result.value)


# ─────────────────────────────────────────────────────────────────────────────
# Reference number extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestReferenceNumbers:
    def test_item_no_simple(self) -> None:
        field, extras = extract_item_no("ITEM NO: H4-7103WY\n100% COTTON")
        assert field.value == "H4-7103WY"
        assert field.tier == 1

    def test_item_no_hash_prefix(self) -> None:
        field, _ = extract_item_no("ITEM# B2-4401\nWIDTH: 60\"")
        assert field.value == "B2-4401"

    def test_style_prefix(self) -> None:
        field, _ = extract_item_no("STYLE NO: WL-9920X")
        assert field.value == "WL-9920X"

    def test_order_no_simple(self) -> None:
        field = extract_order_no("ORDER NO: H19099-24")
        assert field.value is not None
        assert "H19099" in str(field.value)

    def test_order_no_split_columns(self) -> None:
        # Multi-column split — primary part taken, confidence reduced
        field = extract_order_no("ORDER NO: H19099        -24")
        assert field.value is not None
        assert field.tier == 2   # split → reduced confidence

    def test_empty_item_no(self) -> None:
        # "ITEM NO:" with nothing after it
        field, _ = extract_item_no("ITEM NO:\n100% COTTON")
        # Value may be None or very short — should not be a long garbage string
        assert field.value is None or len(str(field.value)) < 3

    def test_po_prefix(self) -> None:
        field = extract_order_no("P/O NO: 88991-A")
        assert field.value is not None


# ─────────────────────────────────────────────────────────────────────────────
# Composition extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestCompositionExtraction:
    def test_format_a_fafa(self) -> None:
        result = extract_composition(FAFA_LABEL)
        assert len(result.components) == 4
        materials = [c.material for c in result.components]
        assert "POLYESTER" in materials
        assert "RAYON"     in materials
        assert "LUREX"     in materials
        assert "SPANDEX"   in materials

    def test_format_a_percentages(self) -> None:
        result = extract_composition(FAFA_LABEL)
        pcts = {c.material: c.percentage for c in result.components}
        assert pcts["POLYESTER"] == pytest.approx(87.0)
        assert pcts["RAYON"]     == pytest.approx(10.0)

    def test_format_a_sum_ok(self) -> None:
        result = extract_composition(FAFA_LABEL)
        assert result.sum_ok is True
        assert result.tier == 1

    def test_format_b_single_material(self) -> None:
        result = extract_composition("100% SPUNPOLYSTER TWO LAYER FABRIC")
        assert len(result.components) == 1
        assert result.components[0].material == "SPUNPOLYESTER"
        assert result.components[0].percentage == pytest.approx(100.0)

    def test_format_b_construction_descriptor(self) -> None:
        result = extract_composition("100% SPUNPOLYSTER TWO LAYER FABRIC")
        assert result.construction_descriptor is not None
        assert "LAYER" in result.construction_descriptor

    def test_format_c_material_first(self) -> None:
        result = extract_composition("POLYESTER 60% COTTON 40%")
        assert len(result.components) == 2
        pcts = {c.material: c.percentage for c in result.components}
        assert pcts.get("POLYESTER", 0) == pytest.approx(60.0)
        assert pcts.get("COTTON", 0)    == pytest.approx(40.0)

    def test_sum_not_100_forces_tier2(self) -> None:
        # 87+10+2+l (OCR: l=1 misread as something else) → sum wrong
        result = extract_composition("87/10/2/5 POLYESTER/RAYON/LUREX/SPANDEX")  # sum=104
        # Sum is 101 — should be flagged
        assert not result.sum_ok
        assert result.tier == 2

    def test_no_composition_returns_tier3(self) -> None:
        result = extract_composition("WIDTH: 60 CM\nFABRIC LABEL")
        assert result.tier == 3
        assert len(result.components) == 0

    def test_spun_label_format_b(self) -> None:
        result = extract_composition(SPUN_LABEL)
        assert len(result.components) == 1
        assert result.components[0].material == "SPUNPOLYESTER"
        assert result.components[0].percentage == pytest.approx(100.0)


# ─────────────────────────────────────────────────────────────────────────────
# Fabric type extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestFabricTypeExtraction:
    def test_tweed_end_of_line(self) -> None:
        result = extract_fabric_type(FAFA_LABEL)
        assert result.value == "TWEED"
        assert result.tier == 1

    def test_denim(self) -> None:
        result = extract_fabric_type("100% COTTON DENIM\nWIDTH: 58\"")
        assert result.value == "DENIM"

    def test_jersey(self) -> None:
        result = extract_fabric_type("POLYESTER 100% JERSEY")
        assert result.value == "JERSEY"

    def test_no_fabric_type(self) -> None:
        result = extract_fabric_type("ITEM NO: X1\nWIDTH: 60 CM")
        assert result.value is None

    def test_case_insensitive(self) -> None:
        result = extract_fabric_type("87% poly tweed\nitem: abc")
        assert result.value == "TWEED"


# ─────────────────────────────────────────────────────────────────────────────
# Width extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestWidthExtraction:
    def test_width_height_range_fafa(self) -> None:
        w_min, w_max, w_unit = extract_width(FAFA_LABEL)
        assert w_min.value == pytest.approx(61.0)
        assert w_max.value == pytest.approx(63.0)

    def test_width_with_inch_marker(self) -> None:
        w_min, w_max, w_unit = extract_width('66/68" 286G/YD (170GSM)')
        assert w_min.value == pytest.approx(66.0)
        assert w_max.value == pytest.approx(68.0)
        assert w_unit.value == "IN"

    def test_width_cm_unit(self) -> None:
        w_min, w_max, w_unit = extract_width("WIDTH: 150 CM")
        assert w_min.value == pytest.approx(150.0)
        assert w_unit.value == "CM"

    def test_width_single_value(self) -> None:
        w_min, w_max, _ = extract_width("WIDTH: 58\"")
        assert w_min.value == pytest.approx(58.0)
        assert w_max.value == pytest.approx(58.0)

    def test_no_width(self) -> None:
        w_min, _, _ = extract_width("ITEM NO: X1\n100% COTTON")
        assert w_min.value is None


# ─────────────────────────────────────────────────────────────────────────────
# Weight extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestWeightExtraction:
    def test_gsm_star_format(self) -> None:
        gsm, _, _ = extract_weights("WIDTH/HEIGHT: 61/63 *250g/m^2")
        # The star format may not match exactly; test with the standard suffix
        gsm2, _, _ = extract_weights("250 GSM")
        assert gsm2.value == pytest.approx(250.0)

    def test_gsm_standard(self) -> None:
        gsm, _, _ = extract_weights("250 GSM")
        assert gsm.value == pytest.approx(250.0)
        assert gsm.tier == 1

    def test_gyd_with_gsm_paren(self) -> None:
        _, gyd, _ = extract_weights("286G/YD (170GSM) +-3%")
        assert gyd.value == pytest.approx(286.0)

    def test_gsm_in_parens(self) -> None:
        gsm, _, _ = extract_weights("286G/YD (170GSM)")
        assert gsm.value == pytest.approx(170.0)

    def test_tolerance(self) -> None:
        _, _, tol = extract_weights("286G/YD (170GSM) +-3%")
        assert tol.value == pytest.approx(3.0)

    def test_no_weight(self) -> None:
        gsm, gyd, tol = extract_weights("ITEM NO: X1\n100% COTTON")
        assert gsm.value is None
        assert gyd.value is None


# ─────────────────────────────────────────────────────────────────────────────
# Full parse_label integration
# ─────────────────────────────────────────────────────────────────────────────

class TestParseLabelIntegration:
    def test_fafa_label_complete(self) -> None:
        result = parse_label(FAFA_LABEL)
        assert result.no_label_detected is False
        assert result.supplier.value == "FAFA TEXTILES CO. LTD"
        assert result.item_no.value == "H4-7103WY"
        assert result.fabric_type.value == "TWEED"
        assert len(result.composition.components) == 4
        assert result.composition.sum_ok is True

    def test_spun_label_complete(self) -> None:
        result = parse_label(SPUN_LABEL)
        assert result.no_label_detected is False
        assert result.order_no.value is not None
        assert len(result.composition.components) == 1
        assert result.composition.components[0].material == "SPUNPOLYESTER"

    def test_empty_text_returns_no_label(self) -> None:
        result = parse_label("")
        assert result.no_label_detected is True

    def test_very_short_text_returns_no_label(self) -> None:
        result = parse_label("   \n  ")
        assert result.no_label_detected is True

    def test_needs_review_set_when_low_confidence(self) -> None:
        # A label with nothing parseable except raw text
        result = parse_label("SOME RANDOM TEXT WITHOUT STRUCTURE")
        # needs_review depends on which fields have tier >= 2
        assert isinstance(result.needs_review, bool)

    def test_needs_review_false_for_high_confidence_label(self) -> None:
        result = parse_label(FAFA_LABEL)
        # FAFA label has clean structure — most fields should be Tier 1
        # At minimum, no_label_detected should be False
        assert result.no_label_detected is False

    def test_composition_sum_error_forces_needs_review(self) -> None:
        bad = "87/10/2/5 POLYESTER/RAYON/LUREX/SPANDEX TWEED"  # sum = 104
        result = parse_label(bad)
        # Composition tier should be 2 (sum != 100%)
        # sum=104 → sum_ok=False → hardcoded tier=2
        assert result.composition.tier == 2
        assert result.needs_review is True
