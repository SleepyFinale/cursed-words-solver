"""Tests for result overlay hero HTML layout (no Qt)."""

from cursed_words_solver.ui.overlay import build_hero_result_html


def test_long_word_score_on_separate_line():
    word = "WONDERMONGERINGS"
    score = "15,985 pts"
    html = build_hero_result_html(word, score)
    word_line_end = html.index("</span>")
    br_pos = html.index("<br>", word_line_end)
    score_pos = html.index(score)
    assert br_pos < score_pos
    assert "&nbsp;&nbsp;" not in html
    assert score in html


def test_capybara_range_and_untrusted_on_score_line():
    score = (
        "<span style='color:#fa0;font-weight:bold'>UNTRUSTED</span> "
        "15,985 pts (14,200–17,500)"
    )
    html = build_hero_result_html("WORD", score)
    assert "UNTRUSTED" in html
    assert "15,985 pts (14,200–17,500)" in html
    assert html.index("<br>") < html.index("UNTRUSTED")


def test_setup_and_placement_lines_after_score():
    setup = "<br><span style='font-size:12px;color:#8cf'>+100 setup (rank 50)</span>"
    placement = "<br><span style='font-size:11px;color:#fa0'>Place A first</span>"
    html = build_hero_result_html(
        "HELLO",
        "1,234 pts",
        setup_line=setup,
        placement_line=placement,
    )
    score_pos = html.index("1,234 pts")
    assert html.index(setup, score_pos) > score_pos
    assert html.index(placement, score_pos) > score_pos
