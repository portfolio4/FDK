"""Registered echo payload forwarding, length limits, and handshake behavior."""

import random

import cocotb
from cocotb.triggers import Timer

from tests.fpga.rtl.message.util import HEADER_BYTES, MessageBeat

ECHO_PAYLOAD_BYTES = 128
ECHO_RESPONSE_MSG_TYPE = 2


class Driver:
    def __init__(self, dut) -> None:
        self.dut = dut
        self.width = int(dut.CHANNEL_PAYLOAD_BYTES.value)
        self.random = random.Random(0)
        # Packed structs expose a single vector through Verilator's VPI. Fields
        # follow handlers.sv declaration order, from most to least significant.
        self.input_layout = (
            ("data", self.width * 8), ("sop", 1), ("eop", 1), ("valid", 1),
            ("msg_size", 16), ("seq", 32), ("ack_seq", 32), ("msg_type", 16),
        )
        self.output_layout = (
            ("data", self.width * 8), ("data_len", self.width.bit_length()),
            ("sop", 1), ("eop", 1), ("valid", 1), ("msg_size", 16), ("ack_seq", 32), ("msg_type", 16),
        )
        assert len(dut.in_beat) == sum(bits for _, bits in self.input_layout)
        assert len(dut.out_beat) == sum(bits for _, bits in self.output_layout)
        self.received: list[MessageBeat] = []
        self.stalled: MessageBeat | None = None

    def output(self) -> tuple[bool, MessageBeat]:
        packed = int(self.dut.out_beat.value)
        fields = {}
        for name, bits in reversed(self.output_layout):
            fields[name] = packed & ((1 << bits) - 1)
            packed >>= bits
        valid = bool(fields.pop("valid"))
        return valid, MessageBeat(seq=0, **fields)

    async def tick(
        self, beat: MessageBeat | None = None, *, ready: bool = True, reset: bool = False,
    ) -> bool:
        dut = self.dut
        dut.clk.value = 0
        dut.rst.value = reset
        fields = {} if beat is None else vars(beat)
        fields = dict(fields, valid=int(beat is not None))
        packed = 0
        for name, bits in self.input_layout:
            packed = (packed << bits) | int(fields.get(name, 0))
        dut.in_beat.value = packed
        dut.out_ready.value = ready
        await Timer(5, unit="ns")
        accepted = beat is not None and bool(dut.in_ready.value) and not reset
        if reset:
            assert not dut.in_ready.value
            self.stalled = None
        else:
            valid, output = self.output()
            if self.stalled is not None:
                assert valid and output == self.stalled
            self.stalled = output if valid and not ready else None
            if valid and ready:
                self.received.append(output)
        dut.clk.value = 1
        await Timer(5, unit="ns")
        return accepted

    async def reset(self) -> None:
        await self.tick(reset=True)
        assert not self.output()[0]
        self.received.clear()
        await self.tick()

    def make_input_beat(
        self, seq: int, *, sop: bool, eop: bool, data: bytes | None = None,
    ) -> MessageBeat:
        if data is None:
            data = self.random.randbytes(self.width)
        if len(data) != self.width:
            raise ValueError(f"Input beat data must contain exactly {self.width} bytes")
        return MessageBeat(
            msg_size=HEADER_BYTES + ECHO_PAYLOAD_BYTES, seq=seq, ack_seq=0xDEADBEEF, msg_type=1,
            sop=sop, eop=eop,
            data=int.from_bytes(data, "big"),
        )


@cocotb.test()
async def test_echo_limits_payload_and_preserves_metadata_under_backpressure(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    expected = []
    # Extra beats after byte 128 must carry zero valid bytes while preserving
    # EOP. A second message checks the counter and acknowledgment restart.
    count = (ECHO_PAYLOAD_BYTES + driver.width - 1) // driver.width + 2
    for seq in (0x12345678, 0x90ABCDEF):
        for index in range(count):
            beat = driver.make_input_beat(
                seq,
                sop=index == 0, eop=index == count - 1,
            )
            if index == 1:
                for _ in range(3):
                    assert not await driver.tick(beat, ready=False)
            assert await driver.tick(beat)
            expected.append(MessageBeat(
                msg_size=HEADER_BYTES + ECHO_PAYLOAD_BYTES, seq=0, ack_seq=seq, msg_type=ECHO_RESPONSE_MSG_TYPE,
                data=beat.data, data_len=min(driver.width, max(0, ECHO_PAYLOAD_BYTES - index * driver.width)),
                sop=beat.sop, eop=beat.eop,
            ))
            if index % 3 == 2:
                await driver.tick()  # Input gaps must not generate extra beats.
        await driver.tick()
        assert not driver.output()[0]
    assert driver.received == expected


@cocotb.test()
async def test_reset_discards_pending_response_and_restarts_byte_count(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    assert await driver.tick(driver.make_input_beat(7, sop=True, eop=False), ready=False)
    await driver.tick(ready=False)
    assert driver.output()[0]
    await driver.reset()
    for _ in range(3):
        await driver.tick()
        assert dut.in_ready.value
        assert not driver.output()[0]
    fresh = driver.make_input_beat(19, sop=True, eop=True, data=b"\xa5" * driver.width)
    assert await driver.tick(fresh)
    await driver.tick()
    await driver.tick()
    assert driver.received == [MessageBeat(
        msg_size=HEADER_BYTES + ECHO_PAYLOAD_BYTES, seq=0, ack_seq=19, msg_type=ECHO_RESPONSE_MSG_TYPE,
        data=fresh.data, data_len=min(driver.width, ECHO_PAYLOAD_BYTES), sop=True, eop=True,
    )]
