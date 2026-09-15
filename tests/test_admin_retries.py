"""The admin helpers retry transient errors a bounded number of times and nothing else."""

import pytest
from xmemory import XmemoryAPIError

from temporal_xmemory_events_agent.memory import admin


def _error(status: int | None, code: str | None = None) -> XmemoryAPIError:
    return XmemoryAPIError("boom", status=status, code=code)


def test_transient_classification() -> None:
    assert admin.is_transient(_error(None))
    assert admin.is_transient(_error(503))
    assert admin.is_transient(_error(429))
    assert not admin.is_transient(_error(400))
    assert not admin.is_transient(_error(None, "WRITE_STILL_PROCESSING"))


async def test_with_retries_recovers_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin, "TRANSIENT_PAUSE_SECONDS", 0.0)
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _error(None)
        return "ok"

    assert await admin.with_retries("flaky", flaky) == "ok"
    assert calls["n"] == 3

    async def always() -> str:
        raise _error(502)

    with pytest.raises(XmemoryAPIError):
        await admin.with_retries("always", always)

    async def fatal() -> str:
        calls["n"] += 1
        raise _error(400)

    calls["n"] = 0
    with pytest.raises(XmemoryAPIError):
        await admin.with_retries("fatal", fatal)
    assert calls["n"] == 1
