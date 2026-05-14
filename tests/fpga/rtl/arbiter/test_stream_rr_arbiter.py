import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer


async def start(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    harness = ArbiterHarness(dut)
    await harness.reset()
    return harness


class ArbiterHarness:

    def __init__(self, dut):
        self._dut = dut
        self._curr_cycle_in_valid_mask = 0

    @property
    def num_inputs(self) -> int:
        return len(self._dut.in_data)

    @property
    def data_width(self) -> int:
        return len(self._dut.in_data[0])

    def fit_input_width(self, value: int) -> int:
        return value & ((1 << self.data_width) - 1)

    async def reset(self) -> None:
        self._curr_cycle_in_valid_mask = 0
        self._dut.rst.value = 1
        self._dut.in_data.value = [0] * len(self._dut.in_data)
        self._dut.in_valid.value = 0
        self._dut.out_ready.value = 0

        for _ in range(3):
            await FallingEdge(self._dut.clk)
            self.assert_no_output()

        self._dut.rst.value = 0

    def _set_input_lane(self, lane: int , in_data: int, in_valid: bool) -> None:
        self._dut.in_data[lane].value = in_data
        mask = 1 << lane
        current = self._curr_cycle_in_valid_mask
        self._curr_cycle_in_valid_mask = (
            (current | mask) if in_valid else (current & ~mask)
        )

    def set_input_lane(self, lane: int, in_data: int) -> None:
        self._set_input_lane(lane, in_data, True)

    def clear_input_lane(self, lane: int) -> None:
        self._set_input_lane(lane, self.fit_input_width(0xAB), False)

    def clear_all_input_lanes(self) -> None:
        for lane in range(self.num_inputs):
            self.clear_input_lane(lane)

    async def cycle(self, expect_lane_ready: int | None = None):
        self._dut.in_valid.value = self._curr_cycle_in_valid_mask

        # in_ready[lane] gets set in combinational logic between
        # cycles so we give the combination values some time to settle
        # by waiting 1ns in a 10ns cycle
        await Timer(1, unit="ns")
        if expect_lane_ready is not None:
            assert(self._dut.in_ready.value == (1 << expect_lane_ready))

        await FallingEdge(self._dut.clk)

    def _assert_output(self, out_data: int, out_valid: bool) -> None:
        assert(self._dut.out_valid.value == out_valid)

        if out_valid:
            assert(self._dut.out_data.value == out_data)

    def assert_output(self, out_data: int) -> None:
        self._assert_output(out_data=out_data, out_valid=True)

    def assert_no_output(self) -> None:
        self._assert_output(out_data=0, out_valid=False)

    def get_output(self) -> int | None:
        if self._dut.out_valid.value:
            return int(self._dut.out_data.value)
        else:
            return None

    def set_out_ready(self, b: bool) -> None:
        self._dut.out_ready.value = b

@cocotb.test()
async def test_rst(dut) -> None:
    harness = await start(dut)

    harness.set_input_lane(lane=1, in_data=1)
    harness.set_out_ready(False)
    await harness.cycle()
    harness.assert_output(out_data=1)

    await harness.reset()
    for _ in range(4):
        await harness.cycle()
        harness.assert_no_output()

@cocotb.test()
async def test_round_robin(dut) -> None:
    harness = await start(dut)

    harness.set_input_lane(lane=1, in_data=1)

    # we are going to accept every output immediately
    harness.set_out_ready(True)

    await harness.cycle(expect_lane_ready=1)
    harness.assert_output(out_data=1)

    # at this point, the last sent item was lane 1

    in_data = [harness.fit_input_width(lane) for lane in range(harness.num_inputs)]
    # populate every lane
    for lane in range(harness.num_inputs):
        harness.set_input_lane(lane, in_data=in_data[lane])

    # validate that outputs are 2, 3, 4, ..., 0, 1
    for _ in range(10):
        for lane in list(range(2, harness.num_inputs)) + list(range(0, min(2, harness.num_inputs))):
            await harness.cycle(expect_lane_ready=lane)
            harness.assert_output(out_data=in_data[lane])

@cocotb.test()
async def test_backpressure(dut) -> None:
    harness = await start(dut)

    harness.set_out_ready(False)
    harness.set_input_lane(lane=0, in_data=0)
    await harness.cycle(expect_lane_ready=0)
    harness.assert_output(out_data=0)

    # at this point, last sent item was lane 0, but it's not drained by downstream

    in_data = [harness.fit_input_width(lane) for lane in range(harness.num_inputs)]
    # populate every lane
    for lane in range(harness.num_inputs):
        harness.set_input_lane(lane, in_data=in_data[lane])

    # validate that outputs are 1, 2, 3, 4, ..., 0
    ordering = list(range(1, harness.num_inputs))
    for lane, prev_lane in zip(ordering, [None] + ordering[:-1]):
        harness.set_out_ready(False)
        for _ in range(5):
            await harness.cycle()
        if prev_lane is None:
            harness.assert_output(out_data=0)
        else:
            harness.assert_output(out_data=in_data[prev_lane])
        harness.set_out_ready(True)
        await harness.cycle(expect_lane_ready=lane)
        harness.assert_output(out_data=in_data[lane])

@cocotb.test()
async def test_single_active_lane(dut) -> None:
    harness = await start(dut)
    harness.set_out_ready(True)
    in_data = [harness.fit_input_width(lane) for lane in range(harness.num_inputs)]

    for _ in range(5):
        for lane in range(harness.num_inputs):
            harness.clear_all_input_lanes()
            harness.set_input_lane(lane, in_data[lane])
            await harness.cycle(expect_lane_ready=lane)
            harness.assert_output(out_data=in_data[lane])

        # clear all the lanes, no traffic for a while, before resuming
        harness.clear_all_input_lanes()
        for _ in range(10):
            await harness.cycle()
            harness.assert_no_output()

@cocotb.test()
async def test_skips_empty_lanes(dut) -> None:
    if len(dut.in_data) < 4:
        pytest.skip("Requires at least 4 input lanes")

    harness = await start(dut)

    harness.set_out_ready(True)
    harness.set_input_lane(lane=0, in_data=0)
    await harness.cycle(expect_lane_ready=0)
    harness.assert_output(out_data=0)

    # at this point, last sent item was lane 0

    # lanes 1 and 3 will get set, and we expect 0 and 2 to get skipped
    harness.clear_all_input_lanes()
    in_data = [harness.fit_input_width(lane) for lane in range(harness.num_inputs)]
    for lane in [1, 3]:
        harness.set_input_lane(lane, in_data[lane])

    for _ in range(10):
        for lane in [1, 3]:
            await harness.cycle(expect_lane_ready=lane)
            harness.assert_output(out_data=in_data[lane])

@cocotb.test()
async def test_simultaneous_enqueue_dequeue(dut) -> None:
    harness = await start(dut)

    harness.set_out_ready(True)
    for i in range(100):
        in_data = harness.fit_input_width(i)
        harness.set_input_lane(lane=0, in_data=in_data)
        await harness.cycle(expect_lane_ready=0)
        harness.assert_output(out_data=in_data)

@cocotb.test()
async def test_new_input_during_stall(dut) -> None:
    if len(dut.in_data) < 4:
        pytest.skip("Requires at least 4 input lanes")

    harness = await start(dut)

    in_data = [harness.fit_input_width(lane) for lane in range(harness.num_inputs)]

    harness.set_input_lane(lane=1, in_data=in_data[1])
    harness.set_out_ready(False)
    await harness.cycle(expect_lane_ready=1)
    harness.assert_output(out_data=in_data[1])

    # at this point, last sent item was lane 1, but it is not drained

    # data for lane 3 is next in line
    harness.set_input_lane(lane=3, in_data=in_data[3])
    await harness.cycle()
    harness.assert_output(out_data=in_data[1])

    # if we then add data for lane 2, it should get in front of lane 3 in priority
    harness.set_input_lane(lane=2, in_data=in_data[2])
    await harness.cycle()
    harness.assert_output(out_data=in_data[1])

    harness.set_out_ready(True)
    await harness.cycle(expect_lane_ready=2)
    harness.assert_output(out_data=in_data[2])
    await harness.cycle(expect_lane_ready=3)
    harness.assert_output(out_data=in_data[3])

@cocotb.test()
async def test_rst_in_middle_of_operation(dut) -> None:
    if len(dut.in_data) < 4:
        pytest.skip("Requires at least 4 input lanes")

    harness = await start(dut)
    harness.set_out_ready(True)

    in_data = [harness.fit_input_width(lane) for lane in range(harness.num_inputs)]

    for _ in range(5):
        for lane in range(harness.num_inputs):
            harness.set_input_lane(lane, in_data=in_data[lane])
        counts = { x : 0 for x in in_data }
        for i in range(2):
            await harness.cycle()
            output = harness.get_output()
            assert(output is not None)
            counts[output] += 1
        assert(all(counts[x] == 0 or counts[x] == 1 for x in counts))
        assert(sum(counts[x] for x in counts) == 2)

        await harness.reset()
        harness.set_out_ready(True)
        for lane in range(harness.num_inputs):
            harness.set_input_lane(lane, in_data=in_data[lane])

        counts = { x : 0 for x in in_data }
        for i in range(harness.num_inputs):
            await harness.cycle()
            output = harness.get_output()
            assert(output is not None)
            counts[output] += 1
        assert(all(counts[x] == 1 for x in counts))

