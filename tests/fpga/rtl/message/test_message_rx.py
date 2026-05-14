"""Header decoding and payload repacking for a single routed channel."""

import cocotb
import pytest
from cocotb.triggers import Timer

from tests.fpga.rtl.channel.util import ChannelFrame, ChannelUtil
from tests.fpga.rtl.message.util import HEADER_BYTES, MessageBeat, MessageUtil

STALL_CYCLES = 3
MAX_INPUT_ACCEPT_WAIT_CYCLES = 100


class Driver:
    def __init__(self, dut) -> None:
        self.dut = dut
        self.channel_util = ChannelUtil(len(dut.in_data) // 8)
        self.message_util = MessageUtil(self.channel_util)
        self.received: list[MessageBeat] = []
        self.stalled: MessageBeat | None = None

    def _collect_output(self) -> MessageBeat:
        return MessageBeat(
            msg_size=int(self.dut.out_msg_size.value),
            seq=int(self.dut.out_seq.value), ack_seq=int(self.dut.out_ack_seq.value),
            msg_type=int(self.dut.out_msg_type.value), sop=bool(self.dut.out_sop.value),
            eop=bool(self.dut.out_eop.value), data=int(self.dut.out_data.value),
        )

    async def tick(
        self, frame: ChannelFrame | None = None, *, ready: bool = True, reset: bool = False,
    ) -> bool:
        dut = self.dut
        dut.clk.value = 0
        dut.rst.value = reset
        dut.in_valid.value = frame is not None
        dut.in_sop.value = False if frame is None else frame.out_sop
        dut.in_eop.value = False if frame is None else frame.out_eop
        dut.in_data.value = 0 if frame is None else frame.out_data
        dut.out_ready.value = ready
        await Timer(5, unit="ns")
        accepted = frame is not None and bool(dut.in_ready.value) and not reset
        if reset:
            assert not dut.in_ready.value
            self.stalled = None
        else:
            valid = bool(dut.out_valid.value)
            beat = self._collect_output()
            if self.stalled is not None:
                assert valid and beat == self.stalled
            self.stalled = beat if valid and not ready else None
            if valid and ready:
                self.received.append(beat)
        dut.clk.value = 1
        await Timer(5, unit="ns")
        return accepted

    async def reset(self) -> None:
        await self.tick(reset=True)
        assert not self.dut.out_valid.value
        self.received.clear()
        await self.tick()

    async def send(self, frames: list[ChannelFrame], *, stall_between_frames: bool = False) -> None:
        for index, frame in enumerate(frames):
            if stall_between_frames and index:
                for _ in range(STALL_CYCLES):
                    await self.tick(ready=False)
            for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
                if await self.tick(frame):
                    break
            else:
                raise AssertionError("Input frame was not accepted")
        await self.drain()

    async def drain(self) -> None:
        for _ in range(2 * self.channel_util.num_payload_bytes_per_channel_frame + 10):
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
@cocotb.parametrize(num_payload_bytes=[0, 1, 7, 8, 9, 16, 31, 128, 257])
async def test_header_payload_and_padding(dut, num_payload_bytes: int) -> None:
    driver = Driver(dut)
    await driver.reset()
    frames, expected = driver.message_util.encode_rx_message(bytes(i % 256 for i in range(num_payload_bytes)))
    await driver.send(frames, stall_between_frames=True)
    assert driver.received == expected


@cocotb.test()
async def test_payload_streams_before_input_eop(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    frames, expected = driver.message_util.encode_rx_message(bytes(range(128)))
    await driver.send(frames[:-1])
    assert driver.received
    await driver.send(frames[-1:])
    assert driver.received == expected


@cocotb.test()
async def test_backpressure_holds_metadata_and_data(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    frames, expected = driver.message_util.encode_rx_message(bytes(range(128)))
    index = 0
    for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
        if await driver.tick(frames[index], ready=False):
            index += 1
        if dut.out_valid.value and not dut.in_ready.value:
            break
    else:
        raise AssertionError("Receiver did not apply backpressure")
    assert dut.out_valid.value
    for _ in range(20):
        assert not await driver.tick(frames[index], ready=False)
    await driver.send(frames[index:])
    assert driver.received == expected


@cocotb.test()
async def test_next_message_waits_for_final_output_transfer(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    first, first_expected = driver.message_util.encode_rx_message(b"first payload" * 3)
    second, second_expected = driver.message_util.encode_rx_message(
        b"second payload", seq=7, ack_seq=19, msg_type=1)
    for frame in first:
        for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
            if await driver.tick(frame):
                break
        else:
            raise AssertionError("Input frame was not accepted")
    # Input EOP is now buffered or in the output register. The next header
    # must not overwrite its metadata while that output remains stalled.
    for _ in range(20):
        assert not await driver.tick(second[0], ready=False)
    await driver.send(second)
    assert driver.received == first_expected + second_expected


@cocotb.test()
async def test_reset_discards_partial_header_payload_and_pending_output(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    old, _ = driver.message_util.encode_rx_message(bytes(range(128)))
    fresh, expected = driver.message_util.encode_rx_message(b"fresh", seq=9, ack_seq=3, msg_type=2)
    await driver.send(old[:1])
    assert driver.received == []
    await driver.reset()
    index = 0
    for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
        if await driver.tick(old[index], ready=False):
            index += 1
        if dut.out_valid.value:
            break
    else:
        raise AssertionError("Receiver did not produce an output beat")
    await driver.reset()
    await driver.drain()
    assert driver.received == []
    await driver.send(fresh)
    assert driver.received == expected


@cocotb.test()
async def test_missing_sop_is_ignored_and_new_sop_restarts_message(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    frames, _ = driver.message_util.encode_rx_message(bytes(range(128)))
    frames[0].out_sop = False
    await driver.send(frames)
    assert driver.received == []
    frames[0].out_sop = True
    await driver.send(frames[:1])
    assert driver.received == []
    fresh, expected = driver.message_util.encode_rx_message(b"restart", seq=1, ack_seq=2, msg_type=3)
    await driver.send(fresh)
    assert driver.received == expected


@cocotb.test()
async def test_truncated_header_is_discarded(dut) -> None:
    driver = Driver(dut)
    width = driver.channel_util.num_payload_bytes_per_channel_frame
    num_frames = (HEADER_BYTES - 1) // width
    if num_frames == 0:
        pytest.skip("An input frame at this width already contains the entire header")
    await driver.reset()
    wire = b"".join(driver.channel_util.make_frame(
        channel_id=5, sop=i == 0, eop=i == num_frames - 1, payload=bytes(width),
    ) for i in range(num_frames))
    await driver.send(driver.channel_util.decode_frames(wire))
    assert driver.received == []
    fresh, expected = driver.message_util.encode_rx_message(b"valid", msg_type=0xFFFF)
    await driver.send(fresh)
    assert driver.received == expected
