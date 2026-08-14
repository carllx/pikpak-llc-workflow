import io
import json
import socketserver
import time
import urllib.error
import urllib.request

import pytest

from pikpak_llc.range_guard import (
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


class AbortAfterFirstReadRaw(FakeRaw):
    def __init__(self, body):
        super().__init__(body)
        self._read_count = 0

    def read(self, size=-1):
        self._read_count += 1
        if self._read_count > 1:
            raise ConnectionAbortedError("upstream connection aborted")
        return super().read(size)


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


def test_non_206_is_closed_before_body_read():
    response = FakeResponse(416, {"Content-Range": "bytes */100"}, forbid_read=True)
    ledger = TransferLedger(100)

    with pytest.raises(RangeGuardError, match="got 416"):
        open_upstream_range(
            "https://origin.invalid/private",
            "bytes=80-99",
            ledger,
            session=FakeSession([response]),
        )

    assert response.closed
    assert response.raw.bytes_read == 0
    assert ledger.total_upstream_bytes == 0
    assert ledger.events[0]["outcome"] == "STATUS_REJECTED"


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


def test_transfer_ledger_can_raise_one_workflow_fuse_without_resetting_bytes():
    ledger = TransferLedger(8)
    ledger.reserve(5)
    ledger.consume(5)

    ledger.increase_max_bytes(20)

    assert ledger.max_bytes == 20
    assert ledger.total_upstream_bytes == 5
    with pytest.raises(ValueError):
        ledger.increase_max_bytes(19)


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


@pytest.mark.parametrize(
    "client_error",
    [BrokenPipeError, ConnectionResetError, ConnectionAbortedError],
)
def test_known_client_abort_after_partial_transfer_is_not_fatal(
    monkeypatch, client_error
):
    chunk_size = 65536
    body = b"a" * chunk_size + b"b" * chunk_size
    session = FakeSession([partial_response(body)])
    ledger = TransferLedger(len(body))
    original_write = socketserver._SocketWriter.write

    def abort_on_first_body_write(writer, data):
        if data == body[:chunk_size]:
            raise client_error("downstream client closed")
        return original_write(writer, data)

    monkeypatch.setattr(socketserver._SocketWriter, "write", abort_on_first_body_write)

    with RangeGuard("https://origin.invalid/private", ledger, session=session) as guard:
        request = urllib.request.Request(
            guard.url,
            headers={"Range": f"bytes=0-{len(body) - 1}"},
        )
        with urllib.request.urlopen(request) as response:
            with pytest.raises(Exception):
                response.read()
        deadline = time.monotonic() + 1
        while not ledger.events and time.monotonic() < deadline:
            time.sleep(0.01)
        guard.raise_if_failed()

    assert ledger.total_upstream_bytes == chunk_size
    assert ledger.events == [
        {
            "range": f"bytes=0-{len(body) - 1}",
            "status": 206,
            "content_range": f"bytes 0-{len(body) - 1}/{len(body)}",
            "bytes_transferred": chunk_size,
            "outcome": "CLIENT_CLOSED",
        }
    ]
    assert ledger.reserve(chunk_size) == chunk_size


def test_unknown_downstream_write_error_remains_fatal(monkeypatch):
    body = b"fatal"
    session = FakeSession([partial_response(body)])
    ledger = TransferLedger(len(body))
    original_write = socketserver._SocketWriter.write

    def fail_body_write(writer, data):
        if data == body:
            raise RuntimeError("unknown downstream failure")
        return original_write(writer, data)

    monkeypatch.setattr(socketserver._SocketWriter, "write", fail_body_write)

    with RangeGuard("https://origin.invalid/private", ledger, session=session) as guard:
        request = urllib.request.Request(guard.url, headers={"Range": "bytes=0-4"})
        with urllib.request.urlopen(request) as response:
            with pytest.raises(Exception):
                response.read()
        deadline = time.monotonic() + 1
        while not ledger.events and time.monotonic() < deadline:
            time.sleep(0.01)
        with pytest.raises(RangeGuardError, match="RuntimeError"):
            guard.raise_if_failed()

    assert ledger.events[0]["outcome"] == "FAIL"


def test_upstream_connection_abort_remains_fatal():
    chunk_size = 65536
    body = b"a" * chunk_size + b"b" * chunk_size
    response = partial_response(body)
    response.raw = AbortAfterFirstReadRaw(body)
    ledger = TransferLedger(len(body))

    with RangeGuard(
        "https://origin.invalid/private",
        ledger,
        session=FakeSession([response]),
    ) as guard:
        request = urllib.request.Request(
            guard.url,
            headers={"Range": f"bytes=0-{len(body) - 1}"},
        )
        with urllib.request.urlopen(request) as downstream:
            with pytest.raises(Exception):
                downstream.read()
        deadline = time.monotonic() + 1
        while not ledger.events and time.monotonic() < deadline:
            time.sleep(0.01)
        with pytest.raises(RangeGuardError, match="ConnectionAbortedError"):
            guard.raise_if_failed()

    assert ledger.total_upstream_bytes == chunk_size
    assert ledger.events[0]["outcome"] == "FAIL"
