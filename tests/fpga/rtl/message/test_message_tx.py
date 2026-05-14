"""Message header insertion and payload streaming into channel frames."""

import cocotb
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
        self.received: list[ChannelFrame] = []
        self.stalled: ChannelFrame | None = None

    def _collect_output(self) -> ChannelFrame:
        return ChannelFrame(
            channel_id=5, out_sop=bool(self.dut.out_sop.value),
            out_eop=bool(self.dut.out_eop.value), reserved=0,
            out_data=int(self.dut.out_data.value),
        )

    async def tick(
        self, beat: MessageBeat | None = None, *, ready: bool = True, reset: bool = False,
    ) -> bool:
        dut = self.dut
        dut.clk.value = 0
        dut.rst.value = reset
        dut.in_valid.value = beat is not None
        if reset:
            dut.in_msg_size.value = 0
            dut.in_seq.value = 0
            dut.in_ack_seq.value = 0
            dut.in_msg_type.value = 0
        elif beat is not None:
            dut.in_msg_size.value = beat.msg_size
            dut.in_seq.value = beat.seq
            dut.in_ack_seq.value = beat.ack_seq
            dut.in_msg_type.value = beat.msg_type
        dut.in_sop.value = False if beat is None else beat.sop
        dut.in_eop.value = False if beat is None else beat.eop
        dut.in_data.value = 0 if beat is None else beat.data
        if beat is not None:
            assert beat.data_len is not None
        dut.in_data_len.value = 0 if beat is None else beat.data_len
        dut.out_ready.value = ready
        await Timer(5, unit="ns")
        accepted = beat is not None and bool(dut.in_ready.value) and not reset
        if reset:
            assert not dut.in_ready.value
            self.stalled = None
        else:
            valid = bool(dut.out_valid.value)
            frame = self._collect_output()
            if self.stalled is not None:
                assert valid and frame == self.stalled
            self.stalled = frame if valid and not ready else None
            if valid and ready:
                self.received.append(frame)
        dut.clk.value = 1
        await Timer(5, unit="ns")
        return accepted

    async def reset(self) -> None:
        await self.tick(reset=True)
        assert not self.dut.out_valid.value
        self.received.clear()
        await self.tick()

    async def send(self, beats: list[MessageBeat], *, stall_between_frames: bool = False) -> None:
        for index, beat in enumerate(beats):
            if stall_between_frames and index:
                for _ in range(STALL_CYCLES):
                    await self.tick(ready=False)
            for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
                if await self.tick(beat):
                    break
            else:
                raise AssertionError("Input beat was not accepted")
        await self.drain()

    async def drain(self) -> None:
        for _ in range(HEADER_BYTES + 2 * self.channel_util.num_payload_bytes_per_channel_frame + 10):
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
@cocotb.parametrize(num_payload_bytes=[0, 1, 7, 8, 17, 128, 257])
async def test_header_payload_and_padding(dut, num_payload_bytes: int) -> None:
    driver = Driver(dut)
    await driver.reset()
    beats, expected = driver.message_util.encode_tx_message(bytes(i % 256 for i in range(num_payload_bytes)))
    await driver.send(beats, stall_between_frames=True)
    assert driver.received == expected


@cocotb.test()
async def test_streams_before_input_eop(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    width = driver.channel_util.num_payload_bytes_per_channel_frame
    beats, expected = driver.message_util.encode_tx_message(bytes(range(3 * width)))
    await driver.send(beats[:-1])
    assert driver.received
    await driver.send(beats[-1:])
    assert driver.received == expected


@cocotb.test()
async def test_backpressure(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    width = driver.channel_util.num_payload_bytes_per_channel_frame
    payload = bytes(i % 256 for i in range(19 * width))
    beats, expected = driver.message_util.encode_tx_message(payload)
    index = 0
    for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
        accepted = await driver.tick(beats[index], ready=False)
        if accepted:
            index += 1
        elif dut.out_valid.value:
            break
    else:
        raise AssertionError("Transmitter did not apply backpressure")
    for _ in range(20):
        assert not await driver.tick(beats[index], ready=False)
    await driver.send(beats[index:])
    assert driver.received == expected


@cocotb.test()
async def test_next_message_waits_for_final_output(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    first, first_expected = driver.message_util.encode_tx_message(b"first")
    second, second_expected = driver.message_util.encode_tx_message(b"second", seq=7, ack_seq=19, msg_type=2)
    for beat in first:
        for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
            if await driver.tick(beat):
                break
        else:
            raise AssertionError("Input beat was not accepted")
    for _ in range(20):
        assert not await driver.tick(second[0], ready=False)
    await driver.send(second)
    assert driver.received == first_expected + second_expected


@cocotb.test()
async def test_reset_discards_buffered_header_and_payload(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    old, _ = driver.message_util.encode_tx_message(b"old payload")
    assert await driver.tick(old[0], ready=False)
    assert dut.out_valid.value
    await driver.reset()
    await driver.drain()
    assert driver.received == []
    fresh, expected = driver.message_util.encode_tx_message(b"fresh", seq=9, ack_seq=3, msg_type=0xFFFF)
    await driver.send(fresh)
    assert driver.received == expected


@cocotb.test()
async def test_input_without_sop_is_discarded(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    beats, expected = driver.message_util.encode_tx_message(b"payload")
    first = beats[0]
    beats[0] = MessageBeat(
        msg_size=first.msg_size, seq=first.seq, ack_seq=first.ack_seq, msg_type=first.msg_type,
        sop=False, eop=first.eop, data=first.data, data_len=first.data_len,
    )
    await driver.send(beats)
    assert driver.received == []
    beats[0] = first
    await driver.send(beats)
    assert driver.received == expected


@cocotb.test()
async def test_partial_and_zero_byte_beats(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    width = driver.channel_util.num_payload_bytes_per_channel_frame
    payload = bytes(range(2 * width + 3))
    _, expected = driver.message_util.encode_tx_message(payload)
    # Fragment every byte separately and put garbage in unused lanes. A
    # zero-byte intermediate beat must contribute neither data nor padding.
    beats = []
    for i, byte in enumerate(payload):
        beats.append(MessageBeat(
            msg_size=HEADER_BYTES + len(payload), seq=0x12345678, ack_seq=0x90ABCDEF, msg_type=0xA5B6,
            sop=i == 0, eop=i == len(payload) - 1,
            data=int.from_bytes(bytes((byte,)) + b"\xa5" * (width - 1), "big"), data_len=1,
        ))
        if i == 0:
            beats.append(MessageBeat(
                msg_size=HEADER_BYTES + len(payload), seq=0x12345678, ack_seq=0x90ABCDEF, msg_type=0xA5B6, sop=False, eop=False,
                data=int.from_bytes(b"\xff" * width, "big"), data_len=0,
            ))
    await driver.send(beats, stall_between_frames=True)
    assert driver.received == expected


@cocotb.test()
async def test_zero_byte_eop_preserves_stalled_output(dut) -> None:
    driver = Driver(dut)
    await driver.reset()
    width = driver.channel_util.num_payload_bytes_per_channel_frame
    payload = bytes((-HEADER_BYTES) % width)
    beats, expected = driver.message_util.encode_tx_message(payload)
    # The header plus payload fill whole output beats. Delay EOP until the last
    # full beat is stalled, then verify it cannot change that visible beat.
    for beat in beats:
        delayed = MessageBeat(
            msg_size=beat.msg_size, seq=beat.seq, ack_seq=beat.ack_seq, msg_type=beat.msg_type,
            sop=beat.sop, eop=False, data=beat.data, data_len=beat.data_len,
        )
        for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
            if await driver.tick(delayed):
                break
        else:
            raise AssertionError("Input beat was not accepted")
    for _ in range(MAX_INPUT_ACCEPT_WAIT_CYCLES):
        if len(driver.received) == len(expected) - 1:
            break
        await driver.tick()
    else:
        raise AssertionError("Output did not reach the final full beat")
    end = MessageBeat(msg_size=HEADER_BYTES + len(payload), seq=0x12345678, ack_seq=0x90ABCDEF, msg_type=0xA5B6,
                      sop=False, eop=True, data=0, data_len=0)
    for _ in range(STALL_CYCLES):
        assert not await driver.tick(end, ready=False)
    await driver.send([end])
    expected[-1].out_eop = False
    expected.append(ChannelFrame(channel_id=5, out_sop=False, out_eop=True, reserved=0, out_data=0))
    assert driver.received == expected
