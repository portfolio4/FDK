from dataclasses import dataclass

import cocotb
from cocotb.triggers import Timer


@dataclass(frozen=True)
class Beat:
    data: int
    data_len: int
    sop: bool
    eop: bool


class Driver:
    def __init__(self, dut) -> None:
        self.dut = dut
        self.depth = int(dut.DEPTH.value)
        self.capacity = int(dut.DATA_WIDTH.value) // 8
        self.beat_bytes = len(dut.in_data) // 8
        self.max_wait = self.capacity + 16
        self.received: list[Beat] = []
        self.stalled: Beat | None = None

    def beats(self, payload: bytes, padding: int = 0) -> list[Beat]:
        chunks = [payload[i:i + self.beat_bytes] for i in range(0, len(payload), self.beat_bytes)]
        chunks = chunks or [b""]
        return [
            Beat(
                data=int.from_bytes(chunk.ljust(self.beat_bytes, bytes([padding])), "big"),
                data_len=len(chunk), sop=i == 0, eop=i == len(chunks) - 1,
            )
            for i, chunk in enumerate(chunks)
        ]

    async def tick(
        self, *, request: tuple[int, bool] | None = None,
        beat: Beat | None = None, ready: bool = False, reset: bool = False,
    ) -> tuple[bool, bool]:
        """Drive inputs, sample handshakes, then advance one rising clock edge."""
        dut = self.dut
        dut.clk.value = 0
        dut.rst.value = reset
        dut.req_valid.value = request is not None
        dut.req_addr.value = 0 if request is None else request[0]
        dut.req_write.value = False if request is None else request[1]
        dut.in_valid.value = beat is not None
        dut.in_data.value = 0 if beat is None else beat.data
        dut.in_data_len.value = 0 if beat is None else beat.data_len
        dut.in_sop.value = False if beat is None else beat.sop
        dut.in_eop.value = False if beat is None else beat.eop
        dut.out_ready.value = ready
        await Timer(5, unit="ns")

        request_accepted = request is not None and bool(dut.req_ready.value)
        beat_accepted = beat is not None and bool(dut.in_ready.value)
        if reset:
            assert not dut.req_ready.value
            assert not dut.in_ready.value
            assert not dut.out_valid.value
            self.stalled = None
        else:
            valid = bool(dut.out_valid.value)
            output = Beat(
                int(dut.out_data.value), int(dut.out_data_len.value),
                bool(dut.out_sop.value), bool(dut.out_eop.value),
            )
            if self.stalled is not None:
                assert valid and output == self.stalled, "Output changed while stalled"
            self.stalled = output if valid and not ready else None
            if valid and ready:
                self.received.append(output)

        dut.clk.value = 1
        await Timer(5, unit="ns")
        return request_accepted, beat_accepted

    async def reset(self) -> None:
        await self.tick(reset=True)
        self.received.clear()
        await self.tick()

    async def request(self, addr: int, *, write: bool) -> None:
        for _ in range(self.max_wait):
            accepted, _ = await self.tick(request=(addr, write))
            if accepted:
                return
        raise AssertionError("Table did not accept request")

    async def send(self, beat: Beat) -> None:
        for _ in range(self.max_wait):
            _, accepted = await self.tick(beat=beat)
            if accepted:
                return
        raise AssertionError("Table did not accept write beat")

    async def write(self, addr: int, payload: bytes) -> None:
        assert len(payload) <= self.capacity
        await self.request(addr, write=True)
        # Invalid input lanes deliberately contain nonzero data.
        for beat in self.beats(payload, padding=0xA5):
            await self.send(beat)

    async def read(self, addr: int, *, stall_cycles: int = 0) -> list[Beat]:
        self.received.clear()
        await self.request(addr, write=False)
        max_beats = (self.capacity + self.beat_bytes - 1) // self.beat_bytes
        for _ in range(max_beats):
            for _ in range(self.max_wait):
                if self.dut.out_valid.value:
                    break
                await self.tick()
            else:
                raise AssertionError("Table did not produce read beat")
            for _ in range(stall_cycles):
                await self.tick(ready=False)
            await self.tick(ready=True)
            if self.received[-1].eop:
                break
        else:
            raise AssertionError("Read exceeded entry capacity without EOP")
        num_beats = len(self.received)
        for _ in range(3):
            await self.tick(ready=True)
            assert not self.dut.out_valid.value, "Output repeated after EOP"
        assert len(self.received) == num_beats, "Output repeated after EOP"
        assert self.dut.req_ready.value, "Table remained locked after read"
        return self.received.copy()


async def start(dut) -> Driver:
    driver = Driver(dut)
    await driver.reset()
    return driver


def make_payload(length: int) -> bytes:
    base = make_payload.base
    make_payload.base += 1
    return bytes((base + 37 * i + 11) % 256 for i in range(length))


make_payload.base = 0


@cocotb.test()
async def test_reset_and_idle(dut) -> None:
    driver = await start(dut)
    for _ in range(4):
        await driver.tick(ready=True)
        assert dut.req_ready.value
        assert not dut.in_ready.value
        assert not dut.out_valid.value


@cocotb.test()
async def test_unwritten_entries_are_empty(dut) -> None:
    driver = await start(dut)
    for addr in range(driver.depth):
        assert await driver.read(addr) == driver.beats(b"")


@cocotb.test()
async def test_single_beat(dut) -> None:
    driver = await start(dut)
    expected = make_payload(driver.beat_bytes)
    await driver.write(0, expected)
    assert await driver.read(0) == driver.beats(expected)


@cocotb.test()
async def test_read_starts_on_request_acceptance(dut) -> None:
    driver = await start(dut)
    for length in sorted({0, 1, driver.capacity}):
        payload = make_payload(length)
        addr = driver.depth - 1
        await driver.write(addr, payload)
        expected = driver.beats(payload)
        driver.received.clear()

        # The first beat must be valid immediately after the request edge,
        # even when the receiver is ready throughout (no setup/bubble cycle).
        accepted, _ = await driver.tick(request=(addr, False), ready=True)
        assert accepted
        assert not driver.received, "Output transferred before request acceptance"
        for beat in expected:
            assert dut.out_valid.value, "Read inserted a bubble"
            assert Beat(int(dut.out_data.value), int(dut.out_data_len.value),
                        bool(dut.out_sop.value), bool(dut.out_eop.value)) == beat
            await driver.tick(ready=True)
        assert driver.received == expected
        assert not dut.out_valid.value
        assert dut.req_ready.value


@cocotb.test()
async def test_full_entry(dut) -> None:
    driver = await start(dut)
    expected = make_payload(driver.capacity)
    await driver.write(0, expected)
    assert await driver.read(0) == driver.beats(expected)


@cocotb.test()
async def test_zero_length_eop_after_full_beats(dut) -> None:
    driver = await start(dut)
    neighbor = make_payload(driver.capacity)
    await driver.write(1, neighbor)
    expected = make_payload(driver.capacity - driver.capacity % driver.beat_bytes)
    await driver.request(0, write=True)
    for beat in driver.beats(expected):
        await driver.send(Beat(beat.data, beat.data_len, beat.sop, eop=False))
    await driver.send(Beat((1 << len(dut.in_data)) - 1, data_len=0, sop=False, eop=True))
    assert await driver.read(0) == driver.beats(expected)
    assert await driver.read(1) == driver.beats(neighbor)


@cocotb.test()
async def test_partial_final_beat(dut) -> None:
    driver = await start(dut)
    expected = make_payload(min(driver.capacity, 2 * driver.beat_bytes) - 1)
    await driver.write(0, expected)
    assert await driver.read(0) == driver.beats(expected)


@cocotb.test()
async def test_shorter_write_replaces_entry(dut) -> None:
    driver = await start(dut)
    await driver.write(0, make_payload(driver.capacity))
    expected = make_payload(1)
    await driver.write(0, expected)
    assert await driver.read(0) == driver.beats(expected)


@cocotb.test()
async def test_empty_write_clears_entry(dut) -> None:
    driver = await start(dut)
    await driver.write(0, make_payload(driver.capacity))
    await driver.write(0, b"")
    assert await driver.read(0) == driver.beats(b"")


@cocotb.test()
async def test_entries_are_independent(dut) -> None:
    driver = await start(dut)
    entries = [make_payload(driver.capacity - addr % driver.beat_bytes)
               for addr in range(driver.depth)]
    for addr, expected in enumerate(entries):
        await driver.write(addr, expected)
    for addr in reversed(range(driver.depth)):
        assert await driver.read(addr) == driver.beats(entries[addr])


@cocotb.test()
async def test_read_preserves_entry(dut) -> None:
    driver = await start(dut)
    expected = make_payload(driver.capacity)
    await driver.write(0, expected)
    assert await driver.read(0) == driver.beats(expected)
    assert await driver.read(0) == driver.beats(expected)


@cocotb.test()
async def test_write_input_gaps(dut) -> None:
    driver = await start(dut)
    expected = make_payload(driver.capacity)
    await driver.request(0, write=True)
    for beat in driver.beats(expected, padding=0xFF):
        for _ in range(3):
            await driver.tick()
            assert dut.in_ready.value
            assert not dut.req_ready.value
        await driver.send(beat)
    assert await driver.read(0) == driver.beats(expected)


@cocotb.test()
async def test_write_locks_requests_until_eop(dut) -> None:
    driver = await start(dut)
    await driver.request(0, write=True)
    # A competing request must not switch the active write's address or mode.
    for _ in range(3):
        accepted, _ = await driver.tick(request=(driver.depth - 1, False))
        assert not accepted
        assert dut.in_ready.value
    expected = make_payload(driver.beat_bytes)
    await driver.send(driver.beats(expected)[0])
    assert dut.req_ready.value
    assert await driver.read(0) == driver.beats(expected)


@cocotb.test()
async def test_read_backpressure(dut) -> None:
    driver = await start(dut)
    expected = make_payload(driver.capacity)
    await driver.write(0, expected)
    assert await driver.read(0, stall_cycles=3) == driver.beats(expected)


@cocotb.test()
async def test_read_locks_requests_until_final_handshake(dut) -> None:
    driver = await start(dut)
    expected = make_payload(1)
    await driver.write(0, expected)
    await driver.request(0, write=False)
    for _ in range(driver.max_wait):
        if dut.out_valid.value:
            break
        await driver.tick()
    else:
        raise AssertionError("Table did not produce final beat")
    assert dut.out_eop.value
    for _ in range(3):
        accepted, _ = await driver.tick(request=(driver.depth - 1, True))
        assert not accepted
        assert not dut.in_ready.value
    await driver.tick(ready=True)
    assert driver.received == driver.beats(expected)
    assert dut.req_ready.value
    assert not dut.out_valid.value


@cocotb.test()
async def test_input_outside_write_is_ignored(dut) -> None:
    driver = await start(dut)
    expected = make_payload(driver.capacity)
    await driver.write(0, expected)
    for _ in range(3):
        _, accepted = await driver.tick(beat=driver.beats(b"\xff")[0])
        assert not accepted
    assert await driver.read(0) == driver.beats(expected)


@cocotb.test()
async def test_reset_clears_stored_lengths(dut) -> None:
    driver = await start(dut)
    for addr in range(driver.depth):
        await driver.write(addr, make_payload(driver.capacity))
    await driver.reset()
    for addr in range(driver.depth):
        assert await driver.read(addr) == driver.beats(b"")


@cocotb.test()
async def test_reset_aborts_write(dut) -> None:
    driver = await start(dut)
    await driver.request(0, write=True)
    beat = driver.beats(make_payload(driver.beat_bytes))[0]
    await driver.send(Beat(beat.data, beat.data_len, sop=True, eop=False))
    await driver.reset()
    assert await driver.read(0) == driver.beats(b"")
    expected = make_payload(1)
    await driver.write(0, expected)
    assert await driver.read(0) == driver.beats(expected)


@cocotb.test()
async def test_reset_aborts_stalled_read(dut) -> None:
    driver = await start(dut)
    await driver.write(0, make_payload(driver.capacity))
    await driver.request(0, write=False)
    for _ in range(driver.max_wait):
        if dut.out_valid.value:
            break
        await driver.tick()
    else:
        raise AssertionError("Table did not produce read beat")
    await driver.tick(ready=False)
    await driver.reset()
    assert await driver.read(0) == driver.beats(b"")
