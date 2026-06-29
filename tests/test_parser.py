"""Parser tests using real row text captured from user.tender.gov.mn."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tenderbot.parser import (  # noqa: E402
    parse_budget, parse_deadline, parse_row, extract_id,
)

# A real row captured live (2026-06-24).
CELLS = [
    "09:00\n2026-07\n27",
    ("11В МАГИСТРАЛЬ. ДХ1136 ЦЭГЭЭС ДЗ1152 ЦЭГИЙН ХООРОНД БУЦАХ 1Ф1000ММ "
     "ГОЛЧТОЙ 1740 МЕТР ШУГАМЫГ ШИНЭЧЛЭН СОЛИХ ЗУРАГ ТӨСӨВ ХИЙЛГЭХ.\n"
     "Захиалагчийн нэр: Улаанбаатар дулааны сүлжээ\n"
     "ХАА-ны журам: Нээлттэй тендер шалгаруулалтын арга\n"
     "1 сар\n109,329,420 ₮"),
    "Урилгын дугаар\nУБДС/20260103026/03/01\nЗарласан огноо\n2026-06-24",
]
LINKS = [
    "https://user.tender.gov.mn/mn/invitation/detail/1782097935859",
    "https://user.tender.gov.mn/mn/client/detail/1453535505120",
]


def test_extract_id():
    assert extract_id(LINKS[0]) == "1782097935859"
    assert extract_id("nope") == ""


def test_parse_budget():
    amount, raw = parse_budget("1 сар\n109,329,420 ₮")
    assert amount == 109329420
    assert "₮" in raw
    assert parse_budget("no money here") == (None, "")


def test_parse_deadline():
    assert parse_deadline(CELLS[0]) == "2026-07-27 09:00"


def test_parse_row_full():
    t = parse_row(CELLS, LINKS)
    assert t is not None
    assert t.tender_id == "1782097935859"
    assert t.code == "УБДС/20260103026/03/01"
    assert t.name.startswith("11В МАГИСТРАЛЬ")
    assert t.buyer == "Улаанбаатар дулааны сүлжээ"
    assert t.procurement_method == "Нээлттэй тендер шалгаруулалтын арга"
    assert t.budget == 109329420
    assert t.publish_date == "2026-06-24"
    assert t.deadline == "2026-07-27 09:00"
    assert t.url == LINKS[0]


def test_parse_row_no_detail_link_returns_none():
    assert parse_row(["x"], ["https://user.tender.gov.mn/mn/client/detail/1"]) is None


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
