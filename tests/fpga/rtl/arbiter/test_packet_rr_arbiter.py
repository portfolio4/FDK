from dataclasses import dataclass

import cocotb
from cocotb.triggers import Timer


@dataclass(frozen=True)
class Beat:
    data: int
    eop: bool


@dataclass(frozen=True)
class TickResult:
    accepted_mask: int
    output: int | None


class Driver:
    def __init__(self, dut):
        self.dut = dut
        self.num_inputs = len(dut.in_data)
        self.mask = (1 << len(dut.in_data[0])) - 1

    async def tick(
        self, beats: list[Beat | None], *, ready=True, reset=False
    ) -> TickResult:
        """Return input handshakes and the registered output after this edge."""
        d = self.dut
        d.clk.value = 0
        d.rst.value = reset
        d.out_ready.value = ready
        d.in_data.value = [beat.data & self.mask if beat else 0 for beat in beats]
        d.in_valid.value = sum(1 << i for i, beat in enumerate(beats) if beat)
        d.in_eop.value = sum(1 << i for i, beat in enumerate(beats) if beat and beat.eop)
        await Timer(5, unit="ns")
        accepted = int(d.in_ready.value) & int(d.in_valid.value)
        d.clk.value = 1
        await Timer(5, unit="ns")
        output = int(d.out_data.value) if d.out_valid.value else None
        return TickResult(accepted_mask=accepted, output=output)

    async def reset(self):
        result = await self.tick([None] * self.num_inputs, reset=True)
        assert result == TickResult(accepted_mask=0, output=None)
        assert not self.dut.in_ready.value


@cocotb.test()
async def every_lane_is_served_once_per_round(dut):
    t = Driver(dut)
    await t.reset()
    beats = [Beat(data=lane, eop=False) for lane in range(t.num_inputs)]
    for _ in range(4):
        lane_counts = [0] * t.num_inputs
        for _ in range(t.num_inputs):
            packet_lane = None
            for beat_index in range(3):
                result = await t.tick(beats)
                assert result.accepted_mask.bit_count() == 1
                lane = result.accepted_mask.bit_length() - 1
                assert result.output == lane & t.mask
                if packet_lane is None:
                    packet_lane = lane
                else:
                    assert lane == packet_lane
                # The next beat is EOP only after accepting the second beat.
                beats[lane] = Beat(data=lane, eop=beat_index == 1)
            lane_counts[packet_lane] += 1
        assert lane_counts == [1] * t.num_inputs
    result = await t.tick([None] * t.num_inputs)
    assert result == TickResult(accepted_mask=0, output=None)


@cocotb.test()
async def lock_survives_input_gaps_and_output_stalls(dut):
    t = Driver(dut)
    await t.reset()
    beats = [None] * t.num_inputs
    beats[1] = Beat(data=11, eop=False)

    # An empty output register can accept a beat even with downstream stalled.
    result = await t.tick(beats, ready=False)
    assert result == TickResult(accepted_mask=1 << 1, output=11 & t.mask)
    beats[1] = Beat(data=12, eop=False)
    beats[0] = Beat(data=20, eop=True)
    for _ in range(3):
        result = await t.tick(beats, ready=False)
        assert result == TickResult(accepted_mask=0, output=11 & t.mask)
    result = await t.tick(beats)
    assert result == TickResult(accepted_mask=1 << 1, output=12 & t.mask)

    # The selected producer may insert gaps without losing ownership.
    beats[1] = None
    for _ in range(3):
        result = await t.tick(beats)
        assert result == TickResult(accepted_mask=0, output=None)
    beats[1] = Beat(data=13, eop=True)
    result = await t.tick(beats)
    assert result == TickResult(accepted_mask=1 << 1, output=13 & t.mask)

    # EOP is buffered: another packet cannot overwrite it under backpressure.
    beats[1] = None
    for _ in range(3):
        result = await t.tick(beats, ready=False)
        assert result == TickResult(accepted_mask=0, output=13 & t.mask)
    result = await t.tick(beats)
    assert result == TickResult(accepted_mask=1 << 0, output=20 & t.mask)
    result = await t.tick([None] * t.num_inputs)
    assert result == TickResult(accepted_mask=0, output=None)


@cocotb.test()
async def reset_discards_buffered_data_and_packet_lock(dut):
    t = Driver(dut)
    await t.reset()
    beats = [None] * t.num_inputs
    beats[1] = Beat(data=1, eop=False)
    result = await t.tick(beats, ready=False)
    assert result == TickResult(accepted_mask=1 << 1, output=1 & t.mask)
    await t.reset()
    beats[1] = None
    beats[0] = Beat(data=2, eop=True)
    result = await t.tick(beats)
    assert result == TickResult(accepted_mask=1 << 0, output=2 & t.mask)
    result = await t.tick([None] * t.num_inputs)
    assert result == TickResult(accepted_mask=0, output=None)
