"""The natural-language reads the workflow itself issues (agents phrase their own)."""

# One object type per read: asking for several at once makes the text-to-SQL reader collapse to one table.
# "Not processed" is an empty status (a newly found event) or the explicit value; both must land in the queue.
UNPROCESSED_EVENTS = (
    "Every Event record whose processing_status is empty, missing or unprocessed (that is, not processed and "
    "not failed). Return all rows with every field."
)
ALL_EVENTS = "Every Event record. Return all rows with every field."
ATTENDANCE_LINKS = (
    "Each attendance link: the CalendarDay date, the Event name and the TeamMember name it connects. "
    "Return one row per link."
)
