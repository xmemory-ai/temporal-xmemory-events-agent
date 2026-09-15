"""The web cleaner: structured event data, main text, feeds, windows."""

from pathlib import Path

from temporal_xmemory_events_agent.web.cleaner import clean, clean_html, window

FIXTURES = Path(__file__).parent / "fixtures"


def test_html_with_json_ld_puts_structured_event_lines_first() -> None:
    page = clean_html((FIXTURES / "meetup_event.html").read_text(), "https://www.meetup.com/x/events/1/")
    first_line = page.text.splitlines()[0]
    assert first_line.startswith("Structured event data: name: Berlin AI Builders: Agents in Production")
    assert "startDate: 2026-10-14T18:30:00+02:00" in first_line
    assert "location: name=Factory Berlin" in first_line
    assert "addressLocality=Berlin" in first_line
    assert "organizer: name=Berlin AI Builders" in first_line
    assert "three talks on running LLM agents" in page.text
    assert page.title.startswith("Berlin AI Builders")


def test_html_without_json_ld_keeps_the_article_and_drops_chrome() -> None:
    page = clean((FIXTURES / "plain_conference.html").read_bytes(), "text/html; charset=utf-8", "http://x.test/")
    assert page.title == "ExampleConf 2027 – Call for Papers"
    assert "3 to 5 March 2027" in page.text
    assert "due by 15 November 2026" in page.text
    assert "Structured event data" not in page.text
    assert "Privacy · Imprint" not in page.text


def test_feed_becomes_one_line_per_item() -> None:
    page = clean((FIXTURES / "cfp_feed.xml").read_bytes(), "application/rss+xml")
    lines = page.text.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(
        "- ExampleConf 2027 : Third Example Conference on Machine Learning Systems | http://example.test/cfp/1"
    )
    assert "<p>" not in lines[1]
    assert "Co-located with ExampleConf 2027" in lines[1]


def test_feed_is_sniffed_from_a_generic_xml_content_type() -> None:
    page = clean((FIXTURES / "cfp_feed.xml").read_bytes(), "text/xml")
    assert page.text.startswith("- ExampleConf 2027")


def test_yaml_and_text_pass_through() -> None:
    body = (FIXTURES / "deadlines.yml").read_bytes()
    page = clean(body, "text/plain; charset=utf-8")
    assert "full_name: Third Example Conference on Machine Learning Systems" in page.text


def test_window_cuts_at_a_line_break_and_reports_the_next_offset() -> None:
    text = "\n".join(f"line {i:03d} " + "x" * 40 for i in range(40))
    chunk, next_offset = window(text, 0, 500)
    assert chunk.endswith("x" * 40)
    assert next_offset is not None and next_offset < 500
    assert text[next_offset] == "\n"
    rest, end = window(text, next_offset, 100_000)
    assert end is None
    assert rest.startswith("line ")
    assert window(text, len(text) + 5, 100) == ("", None)
