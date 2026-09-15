"""Payloads of the web fetch activity and the text the fetch tool hands back to the model."""

from enum import StrEnum

from pydantic import Field

from temporal_xmemory_events_agent.base_models import FrozenTightBaseModel


class FetchStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    BLOCKED = "blocked"


class FetchRequest(FrozenTightBaseModel):
    url: str
    offset: int = Field(default=0, ge=0, description="Character offset into the cleaned text, for long pages")


class FetchResult(FrozenTightBaseModel):
    url: str
    status: FetchStatus
    title: str = ""
    text: str = Field(default="", description="The cleaned text window starting at `offset`")
    offset: int = 0
    total_chars: int = 0
    next_offset: int | None = Field(default=None, description="Offset of the next window, None when this is the end")
    error: str = ""

    def render(self) -> str:
        """The string the model sees: an error line, or the text plus a trailer telling it how to continue."""
        if self.status is FetchStatus.BLOCKED:
            return f"BLOCKED: {self.url} may not be fetched (robots.txt). {self.error}".rstrip()
        if self.status is FetchStatus.ERROR:
            return f"ERROR: could not fetch {self.url}: {self.error}"
        head = f"# {self.title}\n" if self.title else ""
        if self.next_offset is None:
            trailer = f"\n[end of page, {self.total_chars} characters in total]"
        else:
            trailer = (
                f"\n[truncated: showing characters {self.offset}-{self.next_offset} of {self.total_chars}; "
                f"call fetch_url again with offset={self.next_offset} for more]"
            )
        return f"{head}{self.text}{trailer}"
