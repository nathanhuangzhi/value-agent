from app.tools.sec_annual_reports import build_toc, find_section, section_text, search_text

DOC = "\n".join([
    "TABLE OF CONTENTS",
    "ITEM 4.", "INFORMATION ON THE COMPANY", "60",
    "ITEM 5.", "OPERATING AND FINANCIAL REVIEW AND PROSPECTS", "109",
    "ITEM   4.", "INFORMATION ON THE COMPANY",
    "We sell things.", "Lots of them.",
    "ITEM   5.", "OPERATING AND FINANCIAL REVIEW AND PROSPECTS",
    "A. Operating Results", "Revenue grew.",
    "NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS",
    "1. Organization and principal activities", "Cayman holdco.",
    "9. | Investments in equity method investees",
    "VipFubon | 270,683 | 572,427",
    "9. | Investments in equity method investees (Continued)",
    "Total | 2,002,043 | 3,136,784",
    "24.", "Segment information", "Five segments.",
])


def test_toc_prefers_real_sections_over_the_documents_own_toc():
    toc = build_toc(DOC)
    keys = {h["key"]: h for h in toc}
    assert keys["item 4"]["title"] == "Item 4. INFORMATION ON THE COMPANY"
    assert DOC.split("\n")[keys["item 4"]["line"]] == "ITEM   4."      # the body occurrence, not the TOC line
    assert keys["item 5"]["end"] > keys["item 5"]["line"] + 3


def test_notes_from_first_occurrence_and_both_heading_shapes():
    toc = build_toc(DOC)
    keys = {h["key"]: h for h in toc}
    assert keys["note 9"]["title"] == "Note 9. Investments in equity method investees"
    assert keys["note 24"]["title"] == "Note 24. Segment information"
    sec = find_section({"toc": toc}, "equity method")
    chunk, total, nxt = section_text(DOC, sec)
    assert "Total | 2,002,043" in chunk and "Segment information" not in chunk
    assert find_section({"toc": toc}, "note 24")["key"] == "note 24"
    assert find_section({"toc": toc}, "line:3")["line"] == 3


def test_search_hits_with_context():
    hits = search_text(DOC, "vipfubon")
    assert hits and "VipFubon" in hits[0]["snippet"]
