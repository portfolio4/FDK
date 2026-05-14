"""Programming requests publish a condition or reaction and return an Ack."""

from dataclasses import dataclass

import cocotb
from cocotb.triggers import Timer

from tests.apps.afk.fpga.message_helpers import (
    HEADER_BYTES, MAX_CONDITION_MSG_SIZE, MAX_REACTION_PAYLOAD_SIZE,
    MAX_REACTION_MESSAGE_SIZE, REACTION_HEADER_BYTES,
    make_reaction, make_ack, make_message_header,
    make_program_condition, make_program_reaction, make_disable_condition,
)
from tests.apps.afk.fpga.channel_helpers import Beat, make_channel_beats


@dataclass(frozen=True)
class ConditionConfig:
    condition_id: int
    reaction_id: int
    enabled: bool
    pattern_len: int
    pattern: bytes

    @classmethod
    def decode(cls, value: int):
        return cls(
            condition_id=(value >> 273) & 255,
            reaction_id=(value >> 265) & 255,
            enabled=bool((value >> 264) & 1),
            pattern_len=(value >> 256) & 255,
            pattern=(value & ((1 << 256) - 1)).to_bytes(MAX_CONDITION_MSG_SIZE, "big"),
        )


@dataclass(frozen=True)
class ReactionStore:
    reaction_id: int
    reaction_len: int
    word_index: int
    data: bytes

    @classmethod
    def decode(cls, value: int, width: int):
        words = (MAX_REACTION_MESSAGE_SIZE + width - 1) // width
        index_bits = max(1, (words - 1).bit_length())
        metadata = value >> (width * 8)
        return cls(
            reaction_id=(metadata >> (index_bits + 8)) & 255,
            reaction_len=(metadata >> index_bits) & 255,
            word_index=metadata & ((1 << index_bits) - 1),
            data=(value & ((1 << (width * 8)) - 1)).to_bytes(width, "big"),
        )


class Driver:
    def __init__(self, dut):
        self.dut = dut
        self.width = int(dut.CHANNEL_PAYLOAD_BYTES.value)
        self.condition_config_ready = True
        self.reaction_store_ready = True
        self.configs: list[ConditionConfig] = []
        self.stores: list[ReactionStore] = []
        self.acks: list[bytes] = []
        self.ack_bytes = bytearray()

    async def tick(self, beat: Beat | None = None, *, ready=True, reset=False):
        d = self.dut
        d.clk.value = 0
        d.rst.value = reset
        d.in_data.value = beat.data if beat else 0
        d.in_sop.value = beat.sop if beat else False
        d.in_eop.value = beat.eop if beat else False
        d.in_valid.value = beat is not None
        d.condition_evaluator_config_ready.value = self.condition_config_ready
        d.reaction_table_store_ready.value = self.reaction_store_ready
        d.out_ready.value = ready
        await Timer(5, unit="ns")
        accepted = not reset and beat is not None and bool(d.in_ready.value)
        if not reset:
            config = d.out_condition_evaluator_config
            if int(config.value) >> (len(config) - 1) and self.condition_config_ready:
                self.configs.append(ConditionConfig.decode(int(config.value)))
            store = d.out_reaction_table_store
            if int(store.value) >> (len(store) - 1) and self.reaction_store_ready:
                self.stores.append(ReactionStore.decode(int(store.value), self.width))
            if d.out_valid.value and ready:
                if d.out_sop.value:
                    self.ack_bytes.clear()
                self.ack_bytes.extend(int(d.out_data.value).to_bytes(self.width, "big"))
                if d.out_eop.value:
                    size = int.from_bytes(self.ack_bytes[:2], "little")
                    self.acks.append(bytes(self.ack_bytes[:size]))
                    self.ack_bytes.clear()
        d.clk.value = 1
        await Timer(5, unit="ns")
        return accepted

    async def reset(self):
        await self.tick(reset=True)
        self.configs.clear()
        self.stores.clear()
        self.acks.clear()
        self.ack_bytes.clear()

    async def send_beats(self, beats):
        for beat in beats:
            for _ in range(1000):
                if await self.tick(beat):
                    break
            else:
                raise AssertionError("Programming input remained stalled")

    async def send(self, message: bytes):
        await self.send_beats(make_channel_beats(message, self.width))

    async def drain(self, *, ready=True):
        # Allow a full reaction store and an Ack to transfer at any beat width.
        for _ in range(2 * ((MAX_REACTION_MESSAGE_SIZE + HEADER_BYTES) // self.width + 1) + 32):
            await self.tick(ready=ready)


def expected_config(condition_id, reaction_id, pattern):
    return ConditionConfig(
        condition_id=condition_id, reaction_id=reaction_id, enabled=True,
        pattern_len=len(pattern), pattern=pattern.ljust(MAX_CONDITION_MSG_SIZE, b"\x00"),
    )


def expected_stores(width, reaction_id, payload, length=None):
    length = len(payload) if length is None else length
    header = make_reaction(0, 0, payload, reaction_len=length)[:REACTION_HEADER_BYTES]
    message = header + payload.ljust(MAX_REACTION_PAYLOAD_SIZE, b"\x00")
    return [ReactionStore(
        reaction_id=reaction_id, reaction_len=REACTION_HEADER_BYTES + length,
        word_index=offset // width, data=message[offset:offset + width].ljust(width, b"\x00"),
    ) for offset in range(0, REACTION_HEADER_BYTES + length, width)]


@cocotb.test()
async def test_program_condition_and_ack_wait_for_destination(dut):
    driver = Driver(dut)
    await driver.reset()
    pattern = bytes(range(1, MAX_CONDITION_MSG_SIZE + 1))
    driver.condition_config_ready = False
    await driver.send(make_program_condition(0x87654321, 0, 1, 1, pattern))
    await driver.drain()
    assert driver.configs == driver.stores == driver.acks == []

    driver.condition_config_ready = True
    await driver.drain(ready=False)
    assert driver.configs == [expected_config(1, 1, pattern)]
    assert driver.stores == driver.acks == []

    await driver.drain()
    assert driver.configs == [expected_config(1, 1, pattern)]
    assert driver.acks == [make_ack(0, 0x87654321)]


@cocotb.test()
async def test_program_reaction_and_ack_wait_for_destination(dut):
    driver = Driver(dut)
    await driver.reset()
    payload = bytes(range(MAX_REACTION_PAYLOAD_SIZE))
    driver.reaction_store_ready = False
    await driver.send(make_program_reaction(19, 0, 1, payload, reaction_len=5))
    await driver.drain()
    assert driver.configs == driver.stores == driver.acks == []

    driver.reaction_store_ready = True
    await driver.drain()
    assert driver.configs == []
    assert driver.stores == expected_stores(driver.width, 1, payload, length=5)
    assert driver.acks == [make_ack(0, 19)]


@cocotb.test()
async def test_invalid_commands_do_not_publish_or_ack(dut):
    driver = Driver(dut)
    await driver.reset()
    invalid = [
        make_message_header(1, 0, 0xFFFF, 300) + bytes(300),
        make_program_reaction(2, 0, 255, b"bad id"),
        make_program_reaction(3, 0, 0, b"bad length", reaction_len=MAX_REACTION_PAYLOAD_SIZE + 1),
        make_program_condition(4, 0, 255, 0, b"bad condition"),
        make_program_condition(5, 0, 0, 255, b"bad reaction"),
        make_program_condition(6, 0, 0, 0, b"bad length", pattern_len=33),
        make_disable_condition(7, 0, 255),
        make_message_header(8, 0, 2054),  # Missing condition ID.
        make_message_header(9, 0, 2054, 2) + b"\x00\x00",  # Wrong body size.
    ]
    wrong_size = bytearray(make_program_reaction(7, 0, 0, b"wrong size"))
    wrong_size[:2] = (len(wrong_size) - 1).to_bytes(2, "little")
    invalid.append(bytes(wrong_size))
    for message in invalid:
        await driver.send(message)
        await driver.drain()
        assert driver.configs == driver.stores == driver.acks == []

    truncated = make_channel_beats(make_program_reaction(8, 0, 0, b"incomplete"), driver.width)[:-2]
    truncated[-1] = Beat(data=truncated[-1].data, sop=truncated[-1].sop, eop=True)
    await driver.send_beats(truncated)
    await driver.drain()
    assert driver.configs == driver.stores == driver.acks == []

    # A valid request after rejected messages must still publish and Ack.
    await driver.send(make_program_condition(10, 0, 0, 0, b"ok"))
    await driver.drain()
    assert driver.configs == [expected_config(0, 0, b"ok")]
    assert driver.stores == []
    assert driver.acks == [make_ack(0, 10)]


@cocotb.test()
async def test_empty_updates_and_ack_sequence(dut):
    driver = Driver(dut)
    await driver.reset()
    await driver.send(make_program_condition(7, 0, 0, 0, b""))
    await driver.drain()
    await driver.send(make_program_reaction(19, 0, 0, b""))
    await driver.drain()
    assert driver.configs == [expected_config(0, 0, b"")]
    assert driver.stores == expected_stores(driver.width, 0, b"")
    assert driver.acks == [make_ack(0, 7), make_ack(HEADER_BYTES, 19)]


@cocotb.test()
async def test_restart_and_reset_discard_pending_commands(dut):
    driver = Driver(dut)
    await driver.reset()
    interrupted = make_channel_beats(make_program_reaction(1, 0, 0, b"old"), driver.width)
    await driver.send_beats(interrupted[:max(1, len(interrupted) // 2)])
    await driver.send(make_program_condition(2, 0, 0, 0, b"replacement"))
    await driver.drain()
    assert driver.configs == [expected_config(0, 0, b"replacement")]
    assert driver.stores == []
    assert driver.acks == [make_ack(0, 2)]

    driver.condition_config_ready = False
    await driver.send(make_program_condition(3, 0, 0, 0, b"discard"))
    await driver.drain()
    assert driver.configs == [expected_config(0, 0, b"replacement")]
    assert driver.acks == [make_ack(0, 2)]
    await driver.reset()
    driver.condition_config_ready = True
    await driver.drain()
    assert driver.configs == driver.stores == driver.acks == []
    await driver.send(make_program_condition(4, 0, 0, 0, b"fresh"))
    await driver.drain()
    assert driver.configs == [expected_config(0, 0, b"fresh")]
    assert driver.stores == []
    assert driver.acks == [make_ack(0, 4)]


@cocotb.test()
@cocotb.parametrize(payload_size=[0, 1, 14, 15, 16, 17, MAX_REACTION_PAYLOAD_SIZE])
async def test_program_reaction_stops_at_frame_length(dut, payload_size):
    driver = Driver(dut)
    await driver.reset()
    payload = bytes(i % 256 for i in range(payload_size))
    await driver.send(make_program_reaction(23, 0, 0, payload))
    await driver.drain()
    assert driver.stores == expected_stores(driver.width, 0, payload)
    assert driver.acks == [make_ack(0, 23)]


@cocotb.test()
async def test_disable_condition_and_ack_wait_for_destination(dut):
    driver = Driver(dut)
    await driver.reset()
    driver.condition_config_ready = False
    await driver.send(make_disable_condition(31, 0, 1))
    await driver.drain()
    assert driver.configs == driver.stores == driver.acks == []

    driver.condition_config_ready = True
    await driver.drain()
    assert driver.configs == [ConditionConfig(
        condition_id=1, reaction_id=0, enabled=False,
        pattern_len=0, pattern=bytes(MAX_CONDITION_MSG_SIZE),
    )]
    assert driver.stores == []
    assert driver.acks == [make_ack(0, 31)]
