import io
import json
import urllib.error
import urllib.request

import pytest

from range_guard import (
    RangeGuard,
    RangeGuardError,
    TransferBudgetExceeded,
    TransferLedger,
    fetch_exact_range,
    open_upstream_range,
)


class FakeRaw:
    def __init__(self, body, forbid_read=False):
        self._body = io.BytesIO(body)
        self.forbid_read = forbid_read
        self.bytes_read = 0

    def read(self, size=-1):
        if self.forbid_read:
            raise AssertionError("upstream body must not be read")
        chunk = self._body.read(size)
        self.bytes_read += len(chunk)
        return chunk


class FakeResponse:
    def __init__(self, status, headers, body=b"", forbid_read=False):
        self.status_code = status
        self.headers = headers
        self.raw = FakeRaw(body, forbid_read=forbid_read)
        self.closed = False

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def partial_response(body, start=0, total=None):
    total = len(body) if total is None else total
    end = start + len(body) - 1
    return FakeResponse(
        206,
        {
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Content-Length": str(len(body)),
            "Content-Type": "video/mp4",
        },
        body,
    )


def test_fetch_exact_range_records_only_safe_transfer_fields():
    body = b"01234567"
    response = partial_response(body)
    session = FakeSession([response])
    ledger = TransferLedger(100)

    actual, total = fetch_exact_range(
        "https://origin.invalid/private?token=secret",
        "bytes=0-7",
        ledger,
        session=session,
    )

    assert actual == body
    assert total == len(body)
    assert ledger.total_upstream_bytes == len(body)
    assert ledger.events == [
        {
            "range": "bytes=0-7",
            "status": 206,
            "content_range": "bytes 0-7/8",
            "bytes_transferred": 8,
            "outcome": "PASS",
        }
    ]
    assert "secret" not in json.dumps(ledger.events)


def test_http_200_is_closed_before_body_read():
    response = FakeResponse(200, {"Content-Length": "999"}, forbid_read=True)
    ledger = TransferLedger(100)

    with pytest.raises(RangeGuardError, match="must be HTTP 206"):
        open_upstream_range(
            "https://origin.invalid/private",
            "bytes=0-7",
            ledger,
            session=FakeSession([response]),
        )

    assert response.closed
    assert response.raw.bytes_read == 0
    assert ledger.total_upstream_bytes == 0
    assert ledger.events[0]["outcome"] == "HTTP_200_ABORT"


def test_content_range_mismatch_is_rejected_before_body_read():
    response = FakeResponse(
        206,
        {"Content-Range": "bytes 1-8/20", "Content-Length": "8"},
        forbid_read=True,
    )
    ledger = TransferLedger(100)

    with pytest.raises(RangeGuardError, match="start does not match"):
        open_upstream_range(
            "https://origin.invalid/private",
            "bytes=0-7",
            ledger,
            session=FakeSession([response]),
        )

    assert response.raw.bytes_read == 0
    assert ledger.events[0]["outcome"] == "VALIDATION_REJECTED"


def test_finite_request_over_budget_is_rejected_before_body_read():
    response = partial_response(b"abcdefgh")
    ledger = TransferLedger(7)

    with pytest.raises(TransferBudgetExceeded):
        open_upstream_range(
            "https://origin.invalid/private",
            "bytes=0-7",
            ledger,
            session=FakeSession([response]),
        )

    assert response.raw.bytes_read == 0
    assert ledger.total_upstream_bytes == 0


def test_open_ended_response_does_not_reserve_full_budget_before_read():
    response = partial_response(b"0123456789", total=10_000_000_000)
    ledger = TransferLedger(8)

    upstream = open_upstream_range(
        "https://origin.invalid/private",
        "bytes=0-",
        ledger,
        session=FakeSession([response]),
    )

    reservation = ledger.reserve(8)
    assert reservation == 8
    assert response.raw.bytes_read == 0

    ledger.release(reservation)
    upstream.abort("CLIENT_CLOSED")


def test_concurrent_open_ended_responses_share_budget_as_they_read():
    ledger = TransferLedger(8)
    first = open_upstream_range(
        "https://origin.invalid/private",
        "bytes=0-",
        ledger,
        session=FakeSession(
            [partial_response(b"abcdefghijkl", total=10_000_000_000)]
        ),
    )
    second = open_upstream_range(
        "https://origin.invalid/private",
        "bytes=100-",
        ledger,
        session=FakeSession(
            [partial_response(b"mnopqrstuvwx", start=100, total=10_000_000_000)]
        ),
    )

    first_chunks = first.iter_content(chunk_size=4)
    second_chunks = second.iter_content(chunk_size=4)
    assert next(first_chunks) == b"abcd"
    assert next(second_chunks) == b"mnop"
    assert ledger.total_upstream_bytes == 8

    first.abort("CLIENT_CLOSED")
    second.abort("CLIENT_CLOSED")
    first_chunks.close()
    second_chunks.close()


def test_open_ended_client_close_counts_only_bytes_already_read():
    response = partial_response(b"01234", total=10_000_000_000)
    ledger = TransferLedger(10)
    upstream = open_upstream_range(
        "https://origin.invalid/private",
        "bytes=0-",
        ledger,
        session=FakeSession([response]),
    )

    chunks = upstream.iter_content(chunk_size=10)
    assert next(chunks) == b"01234"
    upstream.abort("CLIENT_CLOSED")
    chunks.close()

    assert ledger.total_upstream_bytes == 5
    assert response.raw.bytes_read == 5
    assert ledger.events[0]["bytes_transferred"] == 5
    assert ledger.events[0]["outcome"] == "CLIENT_CLOSED"
    assert ledger.reserve(5) == 5


def test_open_ended_request_stops_exactly_at_hard_budget():
    response = partial_response(b"0123456789")
    ledger = TransferLedger(6)
    upstream = open_upstream_range(
        "https://origin.invalid/private",
        "bytes=0-",
        ledger,
        session=FakeSession([response]),
    )

    with pytest.raises(TransferBudgetExceeded):
        upstream.read()

    assert response.raw.bytes_read == 6
    assert ledger.total_upstream_bytes == 6
    assert ledger.events[0]["bytes_transferred"] == 6


def test_local_guard_forwards_range_and_never_exposes_origin_url():
    body = b"guarded"
    session = FakeSession([partial_response(body)])
    ledger = TransferLedger(100)
    origin_url = "https://origin.invalid/private?token=secret"

    with RangeGuard(origin_url, ledger, session=session) as guard:
        request = urllib.request.Request(
            guard.url,
            headers={"Range": "bytes=0-6"},
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 206
            assert response.read() == body
        guard.raise_if_failed()

    assert session.calls[0][1]["headers"] == {"Range": "bytes=0-6"}
    assert ledger.events[0]["outcome"] == "PASS"
    assert origin_url not in json.dumps(ledger.events)


def test_local_guard_rejects_non_range_get_without_upstream_call():
    session = FakeSession([])
    ledger = TransferLedger(100)

    with RangeGuard("https://origin.invalid/private", ledger, session=session) as guard:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(guard.url)

    assert error.value.code == 400
    assert session.calls == []
    assert ledger.total_upstream_bytes == 0
