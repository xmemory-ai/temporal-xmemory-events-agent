"""Conventions both agents share; they describe how xmemory turns prose into records."""

MEMORY_CONVENTIONS = """\
How memory works
- The events memory and the coordination board are xmemory instances. You write plain prose; xmemory
  extracts structured records from it. It resolves records by the identifying name you write, so precision
  in names is everything.
- Name every event in its canonical form in every sentence about it: the short name plus the year, such as
  "NeurIPS 2026", "ICML 2027", "AI Engineer World's Fair 2026" or "Berlin AI Builders Meetup October 2026".
  Never vary the spelling of a name you have already used.
- Write dates as ISO 8601: 2026-12-07 for a day, 2026-12-07T18:30:00+01:00 for a time.
- Keep one write to one event or a small group of related facts. Statements are additive: say what is true,
  never that a list is complete, and never say something was removed unless it really was cancelled.
- Fields an event can carry: full name, website, kind (conference, workshop, meetup, hackathon, summit,
  webinar, course, other), format (in_person, online, hybrid), start and end dates, city, country, venue,
  registration URL, CFP deadline and URL, status (announced, cfp_open, registration_open, past, cancelled),
  organizer, price info, a short summary, the source URL, and topics as short lowercase tags.
- Every event carries a processing status: "unprocessed" right after discovery, "processed" once its pages
  have been studied, "failed" when that was impossible (say why in a processing note).
- The coordination board holds Sources (identified by a slug) with a quality rating and notes, and Runs
  (identified by a run id) with a status and a summary. Restate the slug or run id in every sentence.
- Attendance of team members is recorded by people, never by you.
"""
