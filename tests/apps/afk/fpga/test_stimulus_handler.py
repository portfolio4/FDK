"""Raw stimulus synchronization, header decoding, and retained payload beats."""

from dataclasses import dataclass
import random

import cocotb
from cocotb.triggers import Timer

from tests.apps.afk.fpga.message_helpers import make_stimulus


@dataclass
class StimulusBeat:
    valid: bool
    data: bytes
    byte_count: int
    sop: bool
    eop: bool
    request_id: int


def decode_stimulus(value: int, width: int) -> StimulusBeat:
    count_bits = width.bit_length()
    return StimulusBeat(
        valid=bool(value >> (width*8 + count_bits + 66)),
        data=((value >> (count_bits + 66)) & ((1 << (width*8)) - 1)).to_bytes(width, "big"),
        byte_count=(value >> 66) & ((1 << count_bits) - 1),
        sop=bool((value >> 65) & 1),
        eop=bool((value >> 64) & 1),
        request_id=value & ((1 << 64) - 1),
    )


class Driver:
    def __init__(self, dut):
        self.dut = dut
        self.width = int(dut.CHANNEL_PAYLOAD_BYTES.value)
        self.responses = []
        self.stalled = None
        self.rng = random.Random(42)

    async def tick(self, word=None, *, ready=True, reset=False):
        d = self.dut
        d.clk.value = 0
        d.rst.value = reset
        d.in_data.value = int.from_bytes(word, "big") if word is not None else 0
        d.in_valid.value = word is not None
        d.stimulus_ready.value = ready
        await Timer(5, unit="ns")
        accepted = word is not None and bool(d.in_ready.value)
        response = decode_stimulus(int(d.out_stimulus.value), self.width)
        if reset:
            assert not response.valid and not d.in_ready.value
            self.stalled = None
        else:
            if self.stalled is not None:
                assert response == self.stalled
            self.stalled = response if response.valid and not ready else None
            if response.valid and ready:
                self.responses.append(response)
        d.clk.value = 1
        await Timer(5, unit="ns")
        return accepted

    async def reset(self):
        await self.tick(reset=True)
        await self.tick()
        self.responses.clear()

    def words(self, wire):
        return [wire[i:i+self.width].ljust(self.width, b"\0")
                for i in range(0, len(wire), self.width)]

    async def send_words(self, words, *, ready=True, random_stalls=False):
        for word in words:
            for _ in range(1000):
                if await self.tick(word, ready=self.rng.randrange(4) != 0 if random_stalls else ready):
                    break
            else:
                raise AssertionError("Stimulus input remained stalled")
            if random_stalls:
                for _ in range(self.rng.randrange(3)):
                    await self.tick(ready=self.rng.randrange(4) != 0)

    async def drain(self, *, ready=True):
        for _ in range(3*self.width + 10):
            await self.tick(ready=ready)

    def expected(self, request_id, payload, padding=b""):
        chunks = [payload[i:i+self.width] for i in range(0, len(payload), self.width)] or [b""]
        return [StimulusBeat(True, (chunk + padding)[:self.width].ljust(self.width, b"\0"), len(chunk),
                             i == 0, i == len(chunks)-1, request_id)
                for i, chunk in enumerate(chunks)]


@cocotb.test()
async def length_delimits_consecutive_packets_and_partial_beats(dut):
    t = Driver(dut)
    await t.reset()
    payloads = [b"", b"x", bytes(range(t.width)), bytes(range(t.width + 1)),
                make_stimulus(99, b"embedded header"),
                bytes(i % 256 for i in range(1027)), b"last"]
    carry_bytes = -len(make_stimulus(0, b"")) % t.width
    # Ending before, at, or just after the retained carry must never require
    # another input beat to flush the packet or expose padding as payload.
    payloads.extend(bytes(range(length))
                    for length in sorted({max(0, carry_bytes-1), carry_bytes, carry_bytes+1}))
    expected = []
    for i, payload in enumerate(payloads):
        wire = make_stimulus(i, payload)
        padding_bytes = -len(wire) % t.width
        # Even a preamble/SFD in the final beat's padding must be discarded.
        padding = (b"\xaa"*7 + b"\xab") * ((padding_bytes + 7)//8)
        await t.send_words(t.words(wire + padding[:padding_bytes]), random_stalls=True)
        expected.extend(t.expected(i, payload, padding[:padding_bytes]))
    await t.drain()
    assert t.responses == expected


@cocotb.test()
async def payload_streams_before_packet_completion_and_holds_while_stalled(dut):
    t = Driver(dut)
    await t.reset()
    payload = bytes(i % 256 for i in range(4*t.width + 3))
    words = t.words(make_stimulus(0xFEDCBA9876543210, payload))
    prefix_words = (18 + t.width + t.width-1)//t.width
    await t.send_words(words[:prefix_words], ready=False)
    await t.drain(ready=False)
    assert t.stalled == t.expected(0xFEDCBA9876543210, payload)[0]
    assert t.responses == []
    await t.drain()
    assert t.responses  # No need to wait for the remainder of the packet.
    await t.send_words(words[prefix_words:])
    await t.drain()
    assert t.responses == t.expected(0xFEDCBA9876543210, payload)


@cocotb.test()
async def reset_discards_partial_headers_payloads_and_pending_output(dut):
    t = Driver(dut)
    await t.reset()
    for prefix_length in (5, 12, 18 + t.width):
        wire = make_stimulus(123, b"x"*(4*t.width + 20))
        await t.send_words(t.words(wire[:prefix_length]), ready=False)
        await t.drain(ready=False)
        await t.reset()
        await t.send_words(t.words(make_stimulus(456, b"fresh")))
        await t.drain()
        assert t.responses == t.expected(456, b"fresh")
        await t.reset()


@cocotb.test()
async def full_beats_are_accepted_every_cycle_and_outputs_follow_next_cycle(dut):
    t = Driver(dut)
    await t.reset()
    payload = bytes(i % 256 for i in range(32*t.width + 3))
    words = t.words(make_stimulus(789, payload))
    expected = t.expected(789, payload)
    for i, word in enumerate(words):
        assert await t.tick(word), "Full input beats must be accepted on consecutive clocks"
        # The output registered by the preceding input edge transfers now.
        previous_payload_bytes = max(0, i*t.width - 18)
        assert t.responses == expected[:previous_payload_bytes//t.width]
        current_payload_bytes = min(len(payload), max(0, (i+1)*t.width - 18))
        output = decode_stimulus(int(dut.out_stimulus.value), t.width)
        if (current_payload_bytes//t.width > previous_payload_bytes//t.width or
                i == len(words)-1):
            assert output == expected[len(t.responses)], "Payload output must be registered immediately"
        else:
            assert not output.valid
    await t.drain()
    assert t.responses == expected


@cocotb.test()
async def final_fragment_survives_stalls_after_an_unaligned_full_word(dut):
    t = Driver(dut)
    await t.reset()
    if 18 % t.width == 0:
        return  # Aligned headers cannot produce two output words from one input beat.
    payload = bytes(i % 256 for i in range(2*t.width + 1))
    expected = t.expected(123, payload)
    for word in t.words(make_stimulus(123, payload)):
        assert await t.tick(word)
    assert decode_stimulus(int(dut.out_stimulus.value), t.width) == expected[-2]
    assert t.responses == expected[:-2]
    await t.drain(ready=False)
    await t.tick()
    assert decode_stimulus(int(dut.out_stimulus.value), t.width) == expected[-1]
    await t.drain(ready=False)
    await t.drain()
    assert t.responses == expected
