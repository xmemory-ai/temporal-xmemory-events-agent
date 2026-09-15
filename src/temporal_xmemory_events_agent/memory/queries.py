"""The natural-language reads the workflow itself issues (agents phrase their own)."""

# One object type per read: asking for several at once makes the text-to-SQL reader collapse to one table.
UNPROCESSED_EVENTS = "Every Event record whose processing_status is unprocessed. Return all rows with every field."
ALL_EVENTS = "Every Event record. Return all rows with every field."
ATTENDANCE_LINKS = (
    "Each attendance link: the CalendarDay date, the Event name and the TeamMember name it connects. "
    "Return one row per link."
)
