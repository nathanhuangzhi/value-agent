from app.tools.sec_6k import html_to_text, looks_like_results_release

HTML = """
<html><body>
<p>Vipshop Holdings Limited Reports Unaudited Second Quarter 2026 Financial Results</p>
<table>
<tr><td><p>Total net revenues</p></td><td>&nbsp;</td><td><div>21,000</div></td><td>20,300</td></tr>
<tr><td>Net income&#8203;</td><td></td><td>1,234</td><td>(56)</td></tr>
</table>
<p>CONDENSED CONSOLIDATED BALANCE SHEETS</p>
<script>ignored()</script>
</body></html>
"""


def test_table_rows_stay_on_one_line_with_pipes():
    text = html_to_text(HTML)
    lines = text.split("\n")
    assert "Total net revenues | 21,000 | 20,300" in lines        # block tags inside cells don't split the row
    assert "Net income | 1,234 | (56)" in lines                   # zero-width space dropped, empty cells collapsed
    assert "ignored()" not in text


def test_results_release_detection():
    assert looks_like_results_release(html_to_text(HTML))
    assert not looks_like_results_release("Vipshop announces a new CFO.\nAbout the company.")


def test_truncation_marker():
    long = "<p>" + "x" * 50 + "</p>" * 1
    assert html_to_text(long, max_chars=10).endswith("…(truncated)")
