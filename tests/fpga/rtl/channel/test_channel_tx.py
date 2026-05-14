"""Fixed-frame TX tests using the shared channel wire-format helpers."""

import cocotb
import pytest
from cocotb.triggers import Timer

from tests.fpga.rtl.channel.util import ChannelFrame, ChannelUtil


STALL_CYCLES = 3
MAX_INPUT_ACCEPT_WAIT_CYCLES = 100


class Driver:
    def __init__(self, dut) -> None:
        self.dut = dut
        self.output_bytes = len(dut.out_data) // 8
        self.num_payload_bytes_per_channel_frame = len(dut.in_data) // 8
        self.channel_util = ChannelUtil(self.num_payload_bytes_per_channel_frame)
        self.received = bytearray()
        self.received_byte_counts: list[int] = []
        self.stalled: int | None = None
        self.stalled_byte_count: int | None = None

    async def tick(
        self, frame: ChannelFrame | None = None, *, ready: bool = True, reset: bool = False,
    ) -> bool:
        dut = self.dut
        dut.clk.value = 0
        dut.rst.value = reset
        dut.in_valid.value = frame is not None
        dut.in_channel_id.value = 0 if frame is None else frame.channel_id
        dut.in_sop.value = False if frame is None else frame.out_sop
        dut.in_eop.value = False if frame is None else frame.out_eop
        dut.in_data.value = 0 if frame is None else frame.out_data
        if frame is not None:
            assert frame.reserved == 0  # TX always transmits reserved bits as zero.
        dut.out_ready.value = ready
        await Timer(5, unit="ns")
        accepted = frame is not None and bool(dut.in_ready.value) and not reset
        if reset:
            assert not dut.in_ready.value
            self.stalled = None
            self.stalled_byte_count = None
        else:
            valid = bool(dut.out_valid.value)
            data = int(dut.out_data.value)
            byte_count = int(dut.output_byte_count.value)
            if self.stalled is not None:
                assert valid and data == self.stalled, "Output changed while stalled"
                assert byte_count == self.stalled_byte_count, "Byte count changed while stalled"
            self.stalled = data if valid and not ready else None
            self.stalled_byte_count = byte_count if valid and not ready else None
            if valid:
                assert 1 <= byte_count <= self.output_bytes
                assert data.to_bytes(self.output_bytes, "big")[byte_count:] == bytes(self.output_bytes - byte_count)
            if valid and ready:
                self.received.extend(data.to_bytes(self.output_bytes, "big")[:byte_count])
                self.received_byte_counts.append(byte_count)
        dut.clk.value = 1
        await Timer(5, unit="ns")
        return accepted

    async def reset(self) -> None:
        await self.tick(reset=True)
        await self.tick(reset=True)
        assert not self.dut.out_valid.value
        assert self.dut.output_byte_count.value == 0
        self.received.clear()
        self.received_byte_counts.clear()
        await self.tick()

    async def send(self, data: bytes, *, stall_between_frames: bool = False) -> None:
        frame_bytes = self.num_payload_bytes_per_channel_frame + 2
        assert len(data) % frame_bytes == 0
        frames = self.channel_util.decode_frames(data)
        for index, frame in enumerate(frames):
            if stall_between_frames and index > 0:
                for _ in range(STALL_CYCLES):
                    await self.tick(ready=False)
            for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
                if await self.tick(frame):
                    break
            else:
                raise AssertionError("Input handshake timed out")
        await self.drain()

    async def drain(self) -> None:
        for _ in range(self.output_bytes + self.num_payload_bytes_per_channel_frame + 10):
            await self.tick()
        assert not self.dut.out_valid.value

    def assert_output(self, expected_stream: bytes) -> None:
        # Valid bytes must match exactly; transport padding is not wire data.
        assert self.received == expected_stream


@cocotb.test()
async def test_reset_and_idle(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    for _ in range(20):
        await driver.tick()
        assert dut.in_ready.value
        assert not dut.out_valid.value
    assert driver.received == b""


@cocotb.test()
async def test_channel_ids_and_descriptor_flags(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    wire = b"".join(
        driver.channel_util.make_frame(
            channel_id=i,
            sop=bool(i & 1),
            eop=bool(i & 2),
            payload=(bytes(driver.num_payload_bytes_per_channel_frame) if i % 2 == 0 else
                     b"\xaa" * (driver.num_payload_bytes_per_channel_frame - 1) + b"\xab"),
        )
        for i in range(256)
    )
    await driver.send(wire)
    driver.assert_output(wire)
    # Every descriptor's reserved bits must be zero on the wire.
    assert all(frame.reserved == 0
               for frame in driver.channel_util.decode_frames(bytes(driver.received)))


@cocotb.test()
async def test_interleaved_channels_with_stalls(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
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
        for group in range(32)
        for index, (channel_id, sop, eop) in enumerate(sequence)
    )
    await driver.send(wire, stall_between_frames=True)
    driver.assert_output(wire)
    assert driver.received == wire


@cocotb.test()
async def test_eop_flush_and_continuation(dut) -> None:
    driver = Driver(dut)
    for count in (1, 3, 7, 19):
        await driver.reset()
        wire = driver.channel_util.make_random_frames(count)
        await driver.send(wire, stall_between_frames=True)
        driver.assert_output(wire)
        # EOP has flushed the entire stream, including its final partial word.
        # Further idle cycles must not duplicate it or emit padding as data.
        before_idle = bytes(driver.received)
        await driver.drain()
        assert driver.received == before_idle

        # The next frame starts immediately after the valid bytes of the last
        # word, regardless of how many unused output lanes that word had.
        following = driver.channel_util.make_random_frames(1)
        await driver.send(following)
        wire += following
        driver.assert_output(wire)


@cocotb.test()
async def test_single_frame_eop_flush_survives_stall(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    wire = driver.channel_util.make_frame(
        channel_id=7, sop=True, eop=True,
        payload=bytes(range(driver.num_payload_bytes_per_channel_frame)),
    )
    frame = driver.channel_util.decode_frames(wire)[0]
    assert await driver.tick(frame, ready=False)
    for _ in range(20):
        # No subsequent input: the accepted EOP must remain remembered.
        await driver.tick(ready=False)
    assert dut.out_valid.value
    await driver.drain()
    driver.assert_output(wire)
    assert driver.received_byte_counts == [
        min(driver.output_bytes, len(wire) - i)
        for i in range(0, len(wire), driver.output_bytes)
    ]


@cocotb.test()
async def test_partial_word_waits_until_accepted_eop(dut) -> None:
    driver = Driver(dut)
    frame_bytes = driver.num_payload_bytes_per_channel_frame + 2
    partial_bytes = frame_bytes % driver.output_bytes
    if partial_bytes == 0:
        pytest.skip("Whole channel frames cannot leave a partial output word at this width")
    await driver.reset()
    first = driver.channel_util.make_frame(
        channel_id=1, sop=True, eop=False,
        payload=bytes(driver.num_payload_bytes_per_channel_frame),
    )
    await driver.send(first)
    sent_bytes = len(first) // driver.output_bytes * driver.output_bytes
    assert len(first) - sent_bytes == partial_bytes
    await driver.drain()
    assert driver.received == first[:sent_bytes]
    last = driver.channel_util.make_frame(
        channel_id=1, sop=False, eop=True,
        payload=b"\xff" * driver.num_payload_bytes_per_channel_frame,
    )
    await driver.send(last, stall_between_frames=True)
    driver.assert_output(first + last)


@cocotb.test()
async def test_backpressure(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    wire = driver.channel_util.make_random_frames(64)
    frames = driver.channel_util.decode_frames(wire)
    index = 0
    for _ in range(200):
        if await driver.tick(frames[index], ready=False):
            index += 1
        if not dut.in_ready.value:
            break
    else:
        raise AssertionError("TX did not apply backpressure")
    assert dut.out_valid.value
    for _ in range(20):
        assert not await driver.tick(frames[index], ready=False)
    frame_bytes = driver.num_payload_bytes_per_channel_frame + 2
    await driver.send(wire[index * frame_bytes:])
    driver.assert_output(wire)


@cocotb.test()
async def test_reset_discards_pending_output_and_buffer(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    old_wire = driver.channel_util.make_random_frames(64)
    frames = driver.channel_util.decode_frames(old_wire)
    for frame in frames:
        await driver.tick(frame, ready=False)
        if not dut.in_ready.value:
            break
    assert dut.out_valid.value
    await driver.reset()
    await driver.drain()
    assert driver.received == b""

    # Also reset after consuming some output, leaving any remaining bytes in
    # the serializer. A new frame must start at byte zero after either reset.
    await driver.tick(frames[0])
    await driver.tick()
    await driver.reset()
    await driver.drain()
    assert driver.received == b""
    fresh = driver.channel_util.make_random_frames(16)
    await driver.send(fresh)
    driver.assert_output(fresh)
