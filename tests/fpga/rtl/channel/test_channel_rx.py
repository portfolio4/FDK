"""Fixed-frame RX tests; expected beats come directly from independent wire bytes."""

import cocotb
from cocotb.triggers import Timer

from tests.fpga.rtl.channel.util import ChannelFrame, ChannelUtil


STALL_CYCLES = 3
MAX_INPUT_ACCEPT_WAIT_CYCLES = 100


class Driver:
    def __init__(self, dut) -> None:
        self.dut = dut
        self.input_bytes = len(dut.in_data) // 8
        self.num_payload_bytes_per_channel_frame = len(dut.out_data) // 8
        self.channel_util = ChannelUtil(self.num_payload_bytes_per_channel_frame)
        self.received: list[ChannelFrame] = []
        self.stalled: ChannelFrame | None = None
        self.pending_input = b""
        self.transmitted = b""

    def _collect_output(self) -> ChannelFrame:
        return ChannelFrame(
            channel_id=int(self.dut.out_channel_id.value),
            out_sop=bool(self.dut.out_sop.value),
            out_eop=bool(self.dut.out_eop.value),
            reserved=int(self.dut.out_reserved.value),
            out_data=int(self.dut.out_data.value),
        )

    async def tick(
        self, word: int | None = None, *, ready: bool = True, reset: bool = False,
    ) -> bool:
        dut = self.dut
        dut.clk.value = 0
        dut.rst.value = reset
        dut.in_valid.value = word is not None
        dut.in_data.value = 0 if word is None else word
        dut.out_ready.value = ready
        await Timer(5, unit="ns")
        accepted = word is not None and bool(dut.in_ready.value) and not reset
        if reset:
            assert not dut.in_ready.value
            self.stalled = None
        else:
            valid = bool(dut.out_valid.value)
            beat = self._collect_output()
            if self.stalled is not None:
                assert valid and beat == self.stalled, "Output changed while stalled"
            self.stalled = beat if valid and not ready else None
            if valid and ready:
                self.received.append(beat)
        dut.clk.value = 1
        await Timer(5, unit="ns")
        return accepted

    async def reset(self) -> None:
        await self.tick(reset=True)
        await self.tick(reset=True)
        assert not self.dut.out_valid.value
        self.received.clear()
        self.pending_input = b""
        self.transmitted = b""
        await self.tick()

    async def send(self, data: bytes, *, stall_between_frames: bool = False) -> None:
        # Send only full input beats. Keep remaining source bytes for the next
        # call rather than inventing transport padding (all input lanes are valid).
        data = self.pending_input + data
        send_bytes = len(data) // self.input_bytes * self.input_bytes
        self.pending_input = data[send_bytes:]
        data = data[:send_bytes]
        words = [int.from_bytes(data[i:i + self.input_bytes], "big")
                 for i in range(0, len(data), self.input_bytes)]
        for index, word in enumerate(words):
            if stall_between_frames and index > 0:
                for _ in range(STALL_CYCLES):
                    await self.tick(ready=False)
            for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
                if await self.tick(word):
                    break
            else:
                raise AssertionError("Input handshake timed out")
        self.transmitted += data
        await self.drain()

    async def drain(self) -> None:
        # Drain all buffered frames, then check for duplicate/unsolicited output.
        for _ in range(self.input_bytes + self.num_payload_bytes_per_channel_frame + 10):
            await self.tick()
        assert not self.dut.out_valid.value


@cocotb.test()
async def test_reset_and_idle(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    for _ in range(20):
        await driver.tick()
        assert dut.in_ready.value
        assert not dut.out_valid.value
    assert driver.received == []


@cocotb.test()
async def test_descriptor_bits_and_channel_ids(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    wire = b"".join(
        driver.channel_util.make_frame(
            channel_id=i,
            sop=bool(i & 1),
            eop=bool(i & 2),
            reserved=i >> 2,
            payload=(bytes(driver.num_payload_bytes_per_channel_frame) if i % 2 == 0 else
                     b"\xaa" * (driver.num_payload_bytes_per_channel_frame - 1) + b"\xab"),
        )
        for i in range(256)
    )
    await driver.send(wire)
    assert driver.received == driver.channel_util.decode_frames(driver.transmitted)


@cocotb.test()
async def test_interleaved_channels_with_stalls(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    # Channel 1's three-beat message overlaps channel 2's two-beat message
    # and channel 3's single-beat message. Repeat with distinct payloads.
    sequence = [
        (1, True, False),
        (2, True, False),
        (1, False, False),
        (3, True, True),
        (1, False, True),
        (2, False, True),
    ]
    wire = b"".join(
        driver.channel_util.make_frame(
            channel_id=channel_id,
            sop=sop,
            eop=eop,
            payload=bytes((group * len(sequence) + index,)) * driver.num_payload_bytes_per_channel_frame,
        )
        for group in range(30)
        for index, (channel_id, sop, eop) in enumerate(sequence)
    )
    await driver.send(wire, stall_between_frames=True)
    assert driver.received == driver.channel_util.decode_frames(driver.transmitted)


@cocotb.test()
async def test_exact_frame_count_and_trailing_fragment(dut) -> None:
    driver = Driver(dut)
    for count in (1, 3, 7, 19):
        await driver.reset()
        wire = driver.channel_util.make_random_frames(count)
        assert len(wire) == count * (driver.num_payload_bytes_per_channel_frame + 2)
        await driver.send(wire)

        # A partial input beat stays in the driver. A partial channel frame
        # already sent to RX stays in RX, without producing premature output.
        sent_bytes = len(wire) // driver.input_bytes * driver.input_bytes
        assert driver.transmitted == wire[:sent_bytes]
        assert driver.pending_input == wire[sent_bytes:]
        assert driver.received == driver.channel_util.decode_frames(wire[:sent_bytes])

        # Finish the pending input beat after an idle gap. The original final
        # frame must complete exactly once. Padding is also valid stream data,
        # so any complete frames it forms must be emitted too.
        stream = driver.channel_util.pad_to_beat_size(wire, len(dut.in_data))
        await driver.send(stream[len(wire):])
        assert driver.transmitted == stream
        assert driver.pending_input == b""
        assert driver.received == driver.channel_util.decode_frames(stream)
        assert driver.received[:count] == driver.channel_util.decode_frames(wire)


@cocotb.test()
async def test_incomplete_frame_and_reset(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    wire = driver.channel_util.make_random_frames(32)
    # Where input words are smaller than a frame, stop one or more bytes short
    # of completion. Neither an idle period nor reset may emit that fragment.
    prefix_bytes = ((driver.num_payload_bytes_per_channel_frame + 1) // driver.input_bytes) * driver.input_bytes
    if prefix_bytes:
        await driver.send(wire[:prefix_bytes])
        assert driver.received == []
        # Complete the original stream across an idle gap without losing bytes.
        await driver.send(wire[prefix_bytes:])
        assert driver.received == driver.channel_util.decode_frames(driver.transmitted)
        await driver.reset()
        await driver.send(wire[:prefix_bytes])
    await driver.reset()
    fresh = driver.channel_util.make_random_frames(48)
    await driver.send(fresh)
    assert driver.received == driver.channel_util.decode_frames(driver.transmitted)


@cocotb.test()
async def test_backpressure_and_reset_pending_output(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    wire = driver.channel_util.make_random_frames(64)
    words = [int.from_bytes(wire[i:i + driver.input_bytes], "big")
             for i in range(0, len(wire), driver.input_bytes)]
    index = 0
    # A long stall must eventually backpressure the producer without dropping
    # already accepted frames. Keep the next word stable throughout the stall.
    for _ in range(200):
        if await driver.tick(words[index], ready=False):
            index += 1
        if not dut.in_ready.value:
            break
    else:
        raise AssertionError("RX did not apply backpressure")
    assert dut.out_valid.value
    for _ in range(20):
        assert not await driver.tick(words[index], ready=False)
    driver.transmitted = wire[:index * driver.input_bytes]
    await driver.send(wire[index * driver.input_bytes:])
    assert driver.received == driver.channel_util.decode_frames(driver.transmitted)

    # Reset while a complete output and queued input are pending.
    for word in words:
        await driver.tick(word, ready=False)
        if dut.out_valid.value:
            break
    assert dut.out_valid.value
    await driver.reset()
    await driver.drain()
    assert driver.received == []
    fresh = driver.channel_util.make_random_frames(16)
    await driver.send(fresh)
    assert driver.received == driver.channel_util.decode_frames(driver.transmitted)
