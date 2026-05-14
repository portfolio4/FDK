"""Condition programming, frame boundaries, priority, and dropped fire attempts."""

from dataclasses import dataclass

import cocotb
from cocotb.triggers import Timer


def pack_fields(*fields):
    value = 0
    for field, width in fields:
        assert 0 <= field < (1 << width)
        value = (value << width) | int(field)
    return value


@dataclass
class StimulusData:
    data: bytes = b""
    sop: bool = False
    eop: bool = False
    request_id: int = 0


@dataclass
class ConfigData:
    condition_id: int
    reaction_id: int
    pattern: bytes
    enabled: bool = True


@dataclass
class FireData:
    valid: bool
    reaction_id: int
    condition_id: int
    request_id: int


def unpack_fire(value: int) -> FireData:
    # Matches afk_condition_evaluator_fire_t's packed field order.
    return FireData(
        valid=bool((value >> 80) & 1),
        reaction_id=(value >> 72) & 0xFF,
        condition_id=(value >> 64) & 0xFF,
        request_id=value & ((1 << 64) - 1),
    )


class Driver:
    def __init__(self, dut):
        self.dut = dut
        self.width = int(dut.CHANNEL_PAYLOAD_BYTES.value)
        self.conditions = int(dut.MAX_CONDITIONS.value)
        self.reactions = int(dut.MAX_REACTIONS.value)
        self.fires: list[FireData] = []
        self.enabled = (1 << self.reactions) - 1

    async def tick(self, *, stimulus: StimulusData | None = None, ready=True,
                   config: ConfigData | None = None, reset=False):
        d = self.dut
        d.clk.value = 0
        d.rst.value = reset
        d.reaction_enabled.value = self.enabled
        # Cocotb exposes packed struct ports as vectors. Pack in declaration
        # order, keeping the ready signals separate from the payload structs.
        stimulus_fields = stimulus if stimulus is not None else StimulusData()
        d.stimulus.value = pack_fields(
            (stimulus is not None, 1),
            (int.from_bytes(stimulus_fields.data.ljust(self.width, b"\0"), "big"), self.width * 8),
            (len(stimulus_fields.data), self.width.bit_length()),
            (stimulus_fields.sop, 1), (stimulus_fields.eop, 1), (stimulus_fields.request_id, 64),
        )
        d.fire_ready.value = ready
        config_fields = config if config is not None else ConfigData(0, 0, b"", False)
        d.in_config.value = pack_fields(
            (config is not None, 1), (config_fields.condition_id, 8),
            (config_fields.reaction_id, 8), (config_fields.enabled, 1),
            (len(config_fields.pattern), 8),
            (int.from_bytes(config_fields.pattern.ljust(32, b"\0"), "big"), 256),
        )
        await Timer(5, unit="ns")
        accepted = stimulus is not None and bool(d.stimulus_ready.value)
        loaded = config is not None and bool(d.config_ready.value)
        fire = unpack_fire(int(d.fire.value))
        if fire.valid:
            assert not reset
            self.fires.append(fire)
        if reset:
            assert not fire.valid
            assert not d.stimulus_ready.value
            assert not d.config_ready.value
        d.clk.value = 1
        await Timer(5, unit="ns")
        return accepted, loaded

    async def reset(self):
        await self.tick(reset=True)
        await self.tick()
        self.fires.clear()

    async def program_condition(self, index, reaction, pattern, enabled=True):
        _, loaded = await self.tick(config=ConfigData(index, reaction, pattern, enabled))
        assert loaded

    async def send_stimulus(self, data, request=1, *, ready=True, gaps=False):
        chunks = [data[i:i+self.width] for i in range(0, len(data), self.width)] or [b""]
        for i, chunk in enumerate(chunks):
            for _ in range(3):
                accepted, _ = await self.tick(
                    stimulus=StimulusData(chunk, sop=(i == 0), eop=(i == len(chunks)-1), request_id=request),
                    ready=ready,
                )
                if accepted:
                    break
            assert accepted
            if gaps and i != len(chunks)-1:
                await self.tick(ready=ready)
        # Dedicated history reset cycle, also protecting the last beat's match.
        await self.tick()


@cocotb.test()
async def matching_and_frame_boundaries(dut):
    t = Driver(dut)
    await t.reset()
    await t.send_stimulus(b"abc", 1)
    assert t.fires == []  # Reset invalidates every condition.
    await t.program_condition(0, 0, b"abc")
    # Pattern crosses a beat boundary and ends in a partial final beat.
    await t.send_stimulus(b"x" * (t.width - 1) + b"abc", 0xFEDCBA9876543210, gaps=True)
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=0xFEDCBA9876543210)]
    t.fires.clear()
    await t.send_stimulus(b"ab", 2)
    await t.send_stimulus(b"c", 3)
    assert t.fires == []  # No matcher history leaks across frames.
    await t.send_stimulus(b"", 4)
    assert t.fires == []

    await t.send_stimulus(b"abcabcabc", 5)
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=5)]
    await t.reset()
    await t.send_stimulus(b"abc", 6)
    assert t.fires == []


@cocotb.test()
async def disabling_condition_blocks_matches(dut):
    t = Driver(dut)
    await t.reset()
    await t.program_condition(0, 0, b"abc")
    await t.send_stimulus(b"abc", 1)
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=1)]
    t.fires.clear()

    await t.program_condition(0, 0, b"", enabled=False)
    await t.send_stimulus(b"abc", 2)
    assert t.fires == []


@cocotb.test()
async def priority_and_reaction_eligibility(dut):
    t = Driver(dut)
    await t.reset()
    for i in range(t.conditions):
        await t.program_condition(i, i % t.reactions, b"abc")
    await t.send_stimulus(b"abc", 10)
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=10)]
    t.fires.clear()
    t.enabled &= ~1
    await t.send_stimulus(b"abc", 11)
    expected = [FireData(valid=True, reaction_id=1, condition_id=1, request_id=11)] if t.conditions > 1 and t.reactions > 1 else []
    assert t.fires == expected
    t.fires.clear()
    t.enabled = (1 << t.reactions) - 1
    await t.program_condition(0, 0, b"abc", enabled=False)
    await t.send_stimulus(b"abc", 12)
    assert t.fires == ([FireData(valid=True, reaction_id=1 % t.reactions, condition_id=1, request_id=12)] if t.conditions > 1 else [])
    if t.conditions > 1:
        for i in range(1, t.conditions):
            await t.program_condition(i, i % t.reactions, b"")
    await t.program_condition(0, 0, b"")
    t.fires.clear()
    await t.send_stimulus(b"abc", 13)
    assert t.fires == []


@cocotb.test()
async def fires_dropped_during_downstream_backpressure(dut):
    t = Driver(dut)
    await t.reset()
    await t.program_condition(0, 0, b"a")

    # Send two beats that both match, but the downstream consumer is stalled
    accepted, _ = await t.tick(stimulus=StimulusData(b"a" * t.width, sop=True, request_id=20), ready=False)
    assert accepted
    assert t.fires == []  # Matcher results are registered before selection.
    await t.tick(ready=False)
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=20)]
    # We fired, but the consumer dropped it. A gap must not repeat the attempt.
    await t.tick(ready=False)
    # and even if another beat matches when the downstream consumer is not stalled,
    # it shouldn't cause another fire
    accepted, _ = await t.tick(stimulus=StimulusData(b"a", eop=True, request_id=20), ready=True)
    assert accepted
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=20)]

    # another new stimulus packet should be accepted and result in a second fire
    await t.tick()
    accepted, _ = await t.tick(stimulus=StimulusData(b"a", sop=True, eop=True, request_id=21))
    assert accepted
    await t.tick()
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=20), FireData(valid=True, reaction_id=0, condition_id=0, request_id=21)]


@cocotb.test()
async def programming_waits_for_idle_and_preserves_other_conditions(dut):
    t = Driver(dut)
    await t.reset()
    await t.program_condition(0, 0, b"ab")
    update = ConfigData(0, 0, b"zz")
    # Both inputs may be offered together, but only stimulus is accepted.
    accepted, loaded = await t.tick(stimulus=StimulusData(b"x" * t.width, sop=True, request_id=30), config=update)
    assert accepted and not loaded
    _, loaded = await t.tick(config=update)
    assert not loaded  # Includes gaps inside a frame.
    accepted, loaded = await t.tick(
        stimulus=StimulusData(b"ab"[:t.width], eop=t.width >= 2, request_id=30), config=update,
    )
    assert accepted and not loaded
    if t.width == 1:
        await t.tick(stimulus=StimulusData(b"b", eop=True, request_id=30), config=update)
    _, loaded = await t.tick(config=update)
    assert not loaded  # History-clear cycle.
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=30)]
    _, loaded = await t.tick(config=update)
    assert loaded
    if t.conditions > 1:
        await t.program_condition(1, 0, b"other")
    t.fires.clear()
    await t.send_stimulus(b"ab", 31)
    assert t.fires == []
    await t.send_stimulus(b"zz", 32)
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=32)]
    if t.conditions > 1:
        await t.send_stimulus(b"other", 33)
        assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=32), FireData(valid=True, reaction_id=0, condition_id=1, request_id=33)]


@cocotb.test()
async def wildcard_padding_and_maximum_pattern(dut):
    t = Driver(dut)
    await t.reset()
    await t.program_condition(0, 0, b"a\0c")
    await t.send_stimulus(b"abc", 40)
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=40)]
    pattern = b"0123456789abcdefghijklmnopqrstuv"  # 32 bytes
    await t.program_condition(0, 0, pattern)
    t.fires.clear()
    await t.send_stimulus(b"x" * (t.width - 1) + pattern, 41)
    assert t.fires == [FireData(valid=True, reaction_id=0, condition_id=0, request_id=41)]
    # Existing matcher semantics include zero padding as wildcard candidates.
    await t.program_condition(0, 0, b"a\0")
    t.fires.clear()
    await t.send_stimulus(b"a", 42)
    assert t.fires == ([FireData(valid=True, reaction_id=0, condition_id=0, request_id=42)] if t.width > 1 else [])
