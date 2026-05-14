"""File-descriptor endpoints and log expectations for integration tests."""

import os
import select
import time
from types import TracebackType


def _read_fd(fd: int, size: int, deadline: float) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
        raise TimeoutError("Timed out waiting for file descriptor input")
    data = os.read(fd, size)
    if not data:
        raise EOFError("File descriptor closed")
    return data


class MockFdEndpoint:
    def __init__(self) -> None:
        self._master_fd, self._slave_fd = os.openpty()
        os.set_blocking(self._master_fd, False)

    @property
    def slave_path(self) -> str:
        return os.ttyname(self._slave_fd)

    def read(self, size: int = 4096, timeout_seconds: float = 5.0) -> bytes:
        return _read_fd(self._master_fd, size, time.monotonic() + timeout_seconds)

    def read_exact(self, size: int, timeout_seconds: float = 5.0) -> bytes:
        data = bytearray()
        deadline = time.monotonic() + timeout_seconds
        while len(data) < size:
            data.extend(_read_fd(self._master_fd, size - len(data), deadline))
        return bytes(data)

    def send(self, data: bytes, timeout_seconds: float = 5.0) -> None:
        remaining = memoryview(data)
        deadline = time.monotonic() + timeout_seconds
        while remaining:
            timeout = deadline - time.monotonic()
            if timeout <= 0 or not select.select([], [self._master_fd], [], timeout)[1]:
                raise TimeoutError("Timed out sending file descriptor input")
            try:
                sent = os.write(self._master_fd, remaining)
            except BlockingIOError:
                continue
            if sent == 0:
                raise EOFError("File descriptor closed while sending")
            remaining = remaining[sent:]

    def close(self) -> None:
        for fd in (self._master_fd, self._slave_fd):
            if fd >= 0:
                os.close(fd)
        self._master_fd = -1
        self._slave_fd = -1

    def __enter__(self) -> "MockFdEndpoint":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class FdTailer:
    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._buffer = bytearray()

    def expect_str(self, expected: str, timeout_seconds: float = 5.0) -> None:
        expected_bytes = expected.encode("utf-8")
        deadline = time.monotonic() + timeout_seconds
        while expected_bytes not in self._buffer:
            try:
                self._buffer.extend(_read_fd(self._fd, 4096, deadline))
            except (TimeoutError, EOFError) as error:
                output = self._buffer.decode("utf-8", errors="replace")
                raise AssertionError(f"{error}. Expected {expected!r}, got {output!r}") from error
        end = self._buffer.index(expected_bytes) + len(expected_bytes)
        del self._buffer[:end]
