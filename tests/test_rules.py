"""Unit tests for the rules engine (design 2.3, 3.2, 3.6) using synthetic pages."""


from tests.conftest import make_page
from ttbverify.models import Commodity, LabelApplication, Outcome
from ttbverify.rules import evaluate


def _app(**overrides) -> LabelApplication:
    base = dict(
        serial_number="1", brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey", commodity=Commodity.SPIRITS,
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", origin=None,
        images=[{"path": "x.png", "role": "front"}],
    )
    base.update(overrides)
    return LabelApplication(**base)


def _by_id(checks):
    return {c.check_id: c for c in checks}


class TestProminenceFilter:
    """Design 3.2: a fine-print occurrence of the declared brand must not count."""

    def test_fineprint_brand_is_rejected(self):
        page = make_page(
            "RUSTY ANCHOR RUM\nSpiced Rum\n40% Alc./Vol. (80 Proof)\n750 mL",
            role="front", word_height=20,
        )
        # Append a tiny-height bottler line that literally contains the declared brand.
        from ttbverify.models import BoundingBox
        from ttbverify.ocr import OcrWord
        y = max(w.box.bottom for w in page.words) + 20
        x = 40
        for tok in "Distilled by Old Tom Distillery Bardstown KY".split():
            page.words.append(OcrWord(tok, 95.0, BoundingBox(x, y, 8 * len(tok), 8),
                                      line=9, block=2, par=1))
            x += 8 * len(tok) + 6

        app = _app(brand_name="OLD TOM DISTILLERY", class_type="Spiced Rum",
                   alcohol_content="40% Alc./Vol.")
        checks = _by_id(evaluate(app, [page]))
        assert checks["brand"].outcome is Outcome.FAIL
        # sanity: the class/type, which *is* prominent, still matches
        assert checks["class_type"].outcome is Outcome.PASS


class TestBrandClassSeparation:
    """Regression: the brand and class/type checks must not read each other's
    text — even when the display face makes the brand line measure *shorter*
    than the class line (Copperplate-style short caps)."""

    def _page(self, brand_h: int, class_h: int):
        from ttbverify.models import BoundingBox
        from ttbverify.ocr import OcrPage, OcrWord

        words: list = []
        y = 40
        for line_no, (text, h) in enumerate(
            [("IRONWOOD RESERVE", brand_h),
             ("Kentucky Straight Bourbon Whiskey", class_h),
             ("40% Alc./Vol. (80 Proof)", 18),
             ("Distilled by Old Tom Distillery, Bardstown KY", 9)],
            start=1,
        ):
            x = 40
            for tok in text.split():
                words.append(OcrWord(tok, 95.0,
                                     BoundingBox(x, y, 12 * len(tok), h),
                                     line=line_no, block=1, par=1))
                x += 12 * len(tok) + 8
            y += h + 20
        return OcrPage(words=words, width=x + 40, height=y, index=0,
                       role="front", engine="fake")

    def test_brand_check_does_not_return_the_class_line(self):
        # class line is the tallest thing on the label
        page = self._page(brand_h=22, class_h=34)
        app = _app(brand_name="OLD TOM DISTILLERY",
                   class_type="Kentucky Straight Bourbon Whiskey")
        checks = _by_id(evaluate(app, [page]))
        assert checks["brand"].outcome is Outcome.FAIL
        assert "Kentucky" not in (checks["brand"].observed or "")
        assert checks["class_type"].outcome is Outcome.PASS

    def test_class_check_does_not_return_the_brand_line(self):
        page = self._page(brand_h=48, class_h=30)
        app = _app(brand_name="IRONWOOD RESERVE",
                   class_type="Kentucky Straight Bourbon Whiskey")
        checks = _by_id(evaluate(app, [page]))
        assert checks["brand"].outcome is Outcome.PASS
        assert checks["class_type"].outcome is Outcome.PASS
        assert "IRONWOOD" not in (checks["class_type"].observed or "")


class TestNumericFields:
    def test_abv_exact(self):
        page = make_page("OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n"
                         "45% Alc./Vol. (90 Proof)\n750 mL\nOld Tom Distillery, LLC")
        checks = _by_id(evaluate(_app(), [page]))
        assert checks["abv"].outcome is Outcome.PASS
        assert checks["proof"].outcome is Outcome.PASS

    def test_abv_near_miss_reviews(self):
        page = make_page("OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n"
                         "45.3% Alc./Vol. (90 Proof)\n750 mL\nOld Tom Distillery, LLC")
        assert _by_id(evaluate(_app(), [page]))["abv"].outcome is Outcome.REVIEW

    def test_abv_mismatch_fails(self):
        page = make_page("OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n"
                         "38% Alc./Vol. (76 Proof)\n750 mL\nOld Tom Distillery, LLC")
        assert _by_id(evaluate(_app(), [page]))["abv"].outcome is Outcome.FAIL

    def test_proof_inconsistent_fails(self):
        page = make_page("OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n"
                         "45% Alc./Vol. (100 Proof)\n750 mL\nOld Tom Distillery, LLC")
        checks = _by_id(evaluate(_app(), [page]))
        assert checks["abv"].outcome is Outcome.PASS
        assert checks["proof"].outcome is Outcome.FAIL

    def test_net_contents_unit_variance_passes(self):
        page = make_page("OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n"
                         "45% Alc./Vol.\n0.75 L\nOld Tom Distillery, LLC")
        assert _by_id(evaluate(_app(), [page]))["net_contents"].outcome is Outcome.PASS

    def test_net_contents_value_mismatch_fails(self):
        page = make_page("OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n"
                         "45% Alc./Vol.\n500 mL\nOld Tom Distillery, LLC")
        assert _by_id(evaluate(_app(), [page]))["net_contents"].outcome is Outcome.FAIL


class TestNotDeclaredVsUnreadable:
    def test_missing_declared_value_is_not_declared(self):
        page = make_page("OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n"
                         "45% Alc./Vol.\n750 mL\nOld Tom Distillery, LLC")
        checks = _by_id(evaluate(_app(alcohol_content=None, net_contents=None), [page]))
        assert checks["abv"].outcome is Outcome.NOT_DECLARED
        assert checks["net_contents"].outcome is Outcome.NOT_DECLARED

    def test_declared_but_absent_from_label_is_unreadable(self):
        page = make_page("OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n"
                         "Old Tom Distillery, LLC")
        checks = _by_id(evaluate(_app(), [page]))
        assert checks["abv"].outcome is Outcome.UNREADABLE
        assert checks["net_contents"].outcome is Outcome.UNREADABLE

    def test_no_ocr_never_passes(self):
        checks = evaluate(_app(), [make_page("", role="front")], ocr_available=False)
        assert all(c.outcome is not Outcome.PASS for c in checks)
