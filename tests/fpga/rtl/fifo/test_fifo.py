import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge


class FifoCollector:
    """Drive one cycle at a time and collect words actually accepted by the consumer."""

    def __init__(
        self,
        dut,
        enqueue_while_full: bool = False,
    ) -> None:
        self._dut = dut
        self._depth = int(dut.DEPTH.value)
        self._enqueue_while_full = enqueue_while_full
        self._max_wait_cycles = 4 * self._depth + 32
        self._outputs = []
        self._enqueued_count = 0

        self._stalled_output = None

    async def reset(self) -> None:
        self._dut.rst.value = 1
        self._dut.in_valid.value = 0
        self._dut.in_data.value = 0
        self._dut.out_ready.value = 0
        for _ in range(2):
            await FallingEdge(self._dut.clk)
            assert not self._dut.out_valid.value

        self._outputs.clear()
        self._enqueued_count = 0
        self._stalled_output = None

        self._dut.rst.value = 0
        await FallingEdge(self._dut.clk)

    async def _cycle(self, in_valid: bool, out_ready: bool, data: int = 0) -> None:
        # Note: if in_valid=True, this assumes you've already confirmed can_enqueue()

        # These outputs are settled at the previous falling-edge checkpoint.
        valid = bool(self._dut.out_valid.value)
        output = int(self._dut.out_data.value) if valid else None
        will_dequeue = valid and out_ready

        self._dut.in_valid.value = in_valid
        self._dut.in_data.value = data
        self._dut.out_ready.value = out_ready

        if self._stalled_output is not None:
            assert valid and output == self._stalled_output, "Output changed while stalled"
        self._stalled_output = output if valid and not out_ready else None

        await FallingEdge(self._dut.clk)

        if in_valid:
            self._enqueued_count += 1
        if will_dequeue:
            self._outputs.append(output)
        assert len(self._outputs) <= self._enqueued_count, "Output without an accepted input"

    def can_enqueue(self, next_out_ready: bool = False) -> bool:
        """Check whether input can be accepted with the proposed consumer readiness."""
        if self._dut.rst.value:
            return False
        in_ready = bool(self._dut.in_ready.value)
        if not self._enqueue_while_full:
            return in_ready

        # The full-FIFO bypass depends on the readiness used for the next cycle,
        # which may differ from the signal currently driven at this checkpoint.
        full = self._enqueued_count - len(self._outputs) == self._depth
        valid = bool(self._dut.out_valid.value)
        out_ready = bool(self._dut.out_ready.value)
        assert in_ready == (not full or (valid and out_ready))
        return not full or (valid and next_out_ready)

    async def cycle_enqueue_only(self, data: int) -> None:
        """Enqueue one word without consuming output; fail if input is blocked."""
        assert self.can_enqueue(), "Cannot enqueue while the FIFO is backpressured"
        await self._cycle(in_valid=True, out_ready=False, data=data)

    async def cycle_enqueue_and_dequeue(self, data: int) -> None:
        """Enqueue one word and accept available output; fail if input is blocked."""
        assert self.can_enqueue(next_out_ready=True), "Cannot enqueue while the FIFO is backpressured"
        await self._cycle(in_valid=True, out_ready=True, data=data)

    async def cycle_dequeue_only(self) -> None:
        await self._cycle(in_valid=False, out_ready=True)

    async def cycle_do_nothing(self) -> None:
        await self._cycle(in_valid=False, out_ready=False)

    def collected_outputs(self) -> list[int]:
        return self._outputs.copy()

    async def drain(self) -> None:
        """Wait for all accepted words, with a loose timeout to detect deadlock."""
        for _ in range(self._max_wait_cycles):
            await self.cycle_dequeue_only()
            if len(self._outputs) == self._enqueued_count:
                break
        else:
            raise AssertionError("FIFO did not produce all accepted words")

        # Continue reading to catch duplicate or unsolicited words after draining.
        for _ in range(8):
            await self.cycle_dequeue_only()


async def start(dut) -> FifoCollector:
    dut.rst.value = 1
    dut.in_valid.value = 0
    dut.in_data.value = 0
    dut.out_ready.value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    option = getattr(dut, "ALLOW_ENQUEUE_DEQUEUE_WHEN_FULL", None)
    collector = FifoCollector(
        dut,
        enqueue_while_full=bool(option.value) if option is not None else False,
    )
    await collector.reset()
    return collector


def make_words(dut, count: int) -> list[int]:
    mask = (1 << len(dut.in_data)) - 1
    return [(i + 1) & mask for i in range(count)]


async def enqueue_with_dequeue(collector: FifoCollector, word: int) -> None:
    for _ in range(collector._max_wait_cycles):
        if collector.can_enqueue(next_out_ready=True):
            await collector.cycle_enqueue_and_dequeue(word)
            return
        await collector.cycle_dequeue_only()
    raise AssertionError("FIFO did not accept input while draining")


@cocotb.test()
async def test_reset(dut) -> None:
    collector = await start(dut)
    for _ in range(4):
        await collector.cycle_dequeue_only()
    assert collector.collected_outputs() == []

    # Fill memory without consuming output, then discard all pending words.
    for word in make_words(dut, int(dut.DEPTH.value)):
        await collector.cycle_enqueue_only(word)
    await collector.reset()
    for _ in range(4):
        await collector.cycle_dequeue_only()
    assert collector.collected_outputs() == []

    # The FIFO can be reused immediately after reset.
    words = make_words(dut, 3)
    for word in words:
        await enqueue_with_dequeue(collector, word)
    await collector.drain()
    assert collector.collected_outputs() == words


@cocotb.test()
async def test_full_and_backpressure(dut) -> None:
    collector = await start(dut)
    expected = []

    # Discover capacity from accepted writes rather than assuming whether the
    # output register contributes an additional slot.
    for word in make_words(dut, collector._max_wait_cycles):
        if not collector.can_enqueue():
            pending = word
            break
        await collector.cycle_enqueue_only(word)
        expected.append(word)
    else:
        raise AssertionError("FIFO never applied input backpressure")
    assert len(expected) >= int(dut.DEPTH.value)

    # The full FIFO must keep applying backpressure and retain queued output.
    for _ in range(5):
        assert not collector.can_enqueue()
        await collector.cycle_do_nothing()

    # Read until space is available, then enqueue the next word.
    await enqueue_with_dequeue(collector, pending)
    expected.append(pending)
    if collector._enqueue_while_full:
        # Replacement left the FIFO full with out_ready high. Turning reads
        # off must block the next write, despite in_ready previously being high.
        next_word = (pending + 1) & ((1 << len(dut.in_data)) - 1)
        await collector.cycle_do_nothing()
        assert not collector.can_enqueue()
        await enqueue_with_dequeue(collector, next_word)
        expected.append(next_word)
    await collector.drain()
    assert collector.collected_outputs() == expected


@cocotb.test()
async def test_simultaneous_transfers_and_wraparound(dut) -> None:
    collector = await start(dut)
    depth = int(dut.DEPTH.value)
    words = make_words(dut, 4 * depth + 16)

    # Start with a backlog, then exercise both interfaces as pointers wrap.
    for word in words[:depth - 1]:
        await collector.cycle_enqueue_only(word)
    for i, word in enumerate(words[depth - 1:]):
        await enqueue_with_dequeue(collector, word)
        if i % 7 == 0:
            await collector.cycle_do_nothing()
    await collector.drain()
    assert collector.collected_outputs() == words


@cocotb.test()
async def test_intermittent_traffic(dut) -> None:
    collector = await start(dut)
    words = make_words(dut, 10)
    expected = []
    for word in words:
        await collector.cycle_enqueue_only(word)
        # Leave the consumer stalled without requiring any particular latency.
        for _ in range(3):
            await collector.cycle_do_nothing()
        await collector.drain()
        expected.append(word)
        assert collector.collected_outputs() == expected


@cocotb.test()
async def test_random_traffic(dut) -> None:
    collector = await start(dut)
    rng = random.Random(42)
    expected = []
    pending = None

    for _ in range(1000):
        if pending is None and rng.randrange(2):
            pending = rng.getrandbits(len(dut.in_data))
        ready = bool(rng.randrange(2))
        if pending is not None and collector.can_enqueue(next_out_ready=ready):
            if ready:
                await collector.cycle_enqueue_and_dequeue(pending)
            else:
                await collector.cycle_enqueue_only(pending)
            expected.append(pending)
            pending = None
        elif ready:
            await collector.cycle_dequeue_only()
        else:
            await collector.cycle_do_nothing()

    if pending is not None:
        await enqueue_with_dequeue(collector, pending)
        expected.append(pending)
    await collector.drain()
    assert collector.collected_outputs() == expected
