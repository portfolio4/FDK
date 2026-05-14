"""Verify streaming echo through the example's UART pins and frame FIFOs."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer, with_timeout

from tests.fpga.rtl.channel.util import ChannelUtil

CLOCK_PERIOD_NS = 10
BIT_PERIOD_NS = 16 * CLOCK_PERIOD_NS
ECHO_PAYLOAD_BYTES = 128
HEADER_BYTES = 12
ECHO_CHANNEL_ID = 5


def make_message_frames(
    util: ChannelUtil, channel_id: int, message: bytes, *, padding: int = 0,
    empty_eop: bool = False,
) -> bytes:
    payload_bytes = util.num_payload_bytes_per_channel_frame
    frames = b"".join(
        util.make_frame(
            channel_id=channel_id, sop=i == 0, eop=not empty_eop and i + payload_bytes >= len(message),
            payload=message[i:i + payload_bytes].ljust(payload_bytes, bytes((padding,))),
        )
        for i in range(0, len(message), payload_bytes)
    )
    if empty_eop:
        frames += util.make_frame(channel_id, bytes(payload_bytes), sop=False, eop=True)
    return frames


def make_echo_message(seq: int, ack_seq: int, msg_type: int, payload: bytes) -> bytes:
    return ((HEADER_BYTES + len(payload)).to_bytes(2, "little") +
            seq.to_bytes(4, "little") + ack_seq.to_bytes(4, "little") +
            msg_type.to_bytes(2, "little") + payload)


def decode_message_payload(util: ChannelUtil, wire: bytes) -> bytes:
    width = util.num_payload_bytes_per_channel_frame
    message = b"".join(frame.out_data.to_bytes(width, "big") for frame in util.decode_frames(wire))
    return util.pad_to_beat_size(message[HEADER_BYTES:], width * 8)


async def send_serial(dut, wire: bytes) -> None:
    for byte in wire:
        for bit in [0, *((byte >> i) & 1 for i in range(8)), 1]:
            dut.rx.value = bit
            await Timer(BIT_PERIOD_NS, unit="ns")


async def receive_serial(dut, received: bytearray, count: int) -> None:
    for _ in range(count):
        await FallingEdge(dut.tx)
        await Timer(BIT_PERIOD_NS * 3 // 2, unit="ns")

        byte = 0
        for bit in range(8):
            byte |= int(dut.tx.value) << bit
            await Timer(BIT_PERIOD_NS, unit="ns")

        assert dut.tx.value == 1
        received.append(byte)


@cocotb.test()
async def test_uart_echo_starts_before_entire_request_arrives(dut) -> None:
    dut.rst.value = 1
    dut.rx.value = 1
    cocotb.start_soon(Clock(dut.clk, CLOCK_PERIOD_NS, unit="ns").start())

    for _ in range(3):
        await FallingEdge(dut.clk)

    dut.rst.value = 0
    await FallingEdge(dut.clk)

    util = ChannelUtil(int(dut.CHANNEL_PAYLOAD_BYTES.value))
    width = util.num_payload_bytes_per_channel_frame
    payload = bytes(range(ECHO_PAYLOAD_BYTES))

    # make the request echo message a little bit larger than normal by adding
    # a bunch of extra \xcc to the end. Test will confirm the FPGA ignores the extra bytes.
    request_message = make_echo_message(7, 0, 1, payload + b"\xcc" * (2 * width + 3))
    request = make_message_frames(util, ECHO_CHANNEL_ID, request_message, padding=0xA5)
    echoed_payload = decode_message_payload(util, request)[:ECHO_PAYLOAD_BYTES]
    # If all response bytes transfer before the delayed input EOP and fill
    # whole frames, TX emits an empty closing frame to carry EOP.
    expected = make_message_frames(
        util, ECHO_CHANNEL_ID, make_echo_message(0, 7, 2, echoed_payload),
        empty_eop=(HEADER_BYTES + len(echoed_payload)) % width == 0,
    )
    next_response_seq = HEADER_BYTES + len(echoed_payload)

    received = bytearray()
    serial_receiver = cocotb.start_soon(receive_serial(dut, received, len(expected)))

    # An otherwise valid echo on an unhandled channel must produce no response
    # and must not advance the echo response sequence.
    ignored_request = make_message_frames(util, 3, make_echo_message(99, 0, 1, payload))
    await send_serial(dut, ignored_request)

    ignored_request = make_message_frames(util, ECHO_CHANNEL_ID, make_echo_message(99, 0, 0xFFFF, payload))
    await send_serial(dut, ignored_request)

    await Timer(20 * BIT_PERIOD_NS, unit="ns")
    assert received == b""

    # Supply the header and one complete repacked payload beat to message_rx.
    first_beats = (HEADER_BYTES + width + width - 1) // width
    prefix_bytes = first_beats * (width + 2)
    await send_serial(dut, request[:prefix_bytes])

    # Allow the first response frame to cross UART while the rest of the
    # request has not been sent. This checks the complete transport pipeline.
    await Timer((width + 2) * 12 * BIT_PERIOD_NS, unit="ns")

    assert received[:width + 2] == expected[:width + 2]
    assert len(received) < len(expected)

    # Discard another complete request while channel 5 is mid-payload without
    # resetting its header, application state, or payload byte count.
    ignored_request = make_message_frames(util, 255, make_echo_message(100, 0, 1, payload))
    await send_serial(dut, ignored_request)

    await send_serial(dut, request[prefix_bytes:])
    await with_timeout(serial_receiver, len(expected) * 12 * BIT_PERIOD_NS, "ns")

    assert received == expected

    # A second request verifies the echo byte counter resets and response
    # sequences exclude ignored extra data and padding.
    payload = payload[::-1]
    request = make_message_frames(util, ECHO_CHANNEL_ID, make_echo_message(9, 0, 1, payload))
    echoed_payload = decode_message_payload(util, request)[:ECHO_PAYLOAD_BYTES]
    expected = make_message_frames(util, ECHO_CHANNEL_ID, make_echo_message(next_response_seq, 9, 2, echoed_payload))

    received = bytearray()
    serial_receiver = cocotb.start_soon(receive_serial(dut, received, len(expected)))

    await send_serial(dut, request)
    await with_timeout(serial_receiver, len(expected) * 12 * BIT_PERIOD_NS, "ns")

    assert received == expected
