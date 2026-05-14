"""ADMIN and PROGRAM_ACTIONS routing, live programming, and UART responses."""

from collections import deque
from itertools import zip_longest

import cocotb
from cocotb.clock import Clock
from cocotb.simtime import get_sim_time
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, Timer, with_timeout

from tests.fpga.rtl.channel.util import ChannelUtil
from tests.apps.afk.fpga.channel_helpers import ChannelId
from tests.apps.afk.fpga.message_helpers import (
    make_ack, make_echo_request, make_echo_response,
    make_program_condition, make_program_reaction, make_disable_condition, make_test_request, make_stimulus,
    make_reaction, MAX_REACTION_PAYLOAD_SIZE,
)

CLOCK_NS = 10
BIT_NS = 200  # Twenty ten-nanosecond clocks per UART bit.


async def start(dut) -> ChannelUtil:
    dut.rx.value = 1
    dut.rst.value = 1
    cocotb.start_soon(Clock(dut.clk, CLOCK_NS, unit="ns").start())
    for _ in range(3):
        await FallingEdge(dut.clk)
    dut.rst.value = 0
    return ChannelUtil(int(dut.CHANNEL_PAYLOAD_BYTES.value))


def frames(util: ChannelUtil, channel: int, message: bytes) -> list[bytes]:
    width = util.num_payload_bytes_per_channel_frame
    return [util.make_frame(
        channel, message[i:i + width].ljust(width, b"\xa5"),
        sop=i == 0, eop=i + width >= len(message),
    ) for i in range(0, len(message), width)]


async def send_wire(dut, wire: bytes) -> None:
    for byte in wire:
        for bit in [0, *((byte >> i) & 1 for i in range(8)), 1]:
            dut.rx.value = bit
            await Timer(BIT_NS, unit="ns")


async def read_byte(dut) -> int:
    await FallingEdge(dut.tx)
    await Timer(BIT_NS * 3 // 2, unit="ns")
    value = 0
    for bit in range(8):
        value |= int(dut.tx.value) << bit
        await Timer(BIT_NS, unit="ns")
    assert dut.tx.value == 1
    return value


async def check_responses(dut, util: ChannelUtil, expected: dict[int, deque[bytes]]) -> None:
    width = util.num_payload_bytes_per_channel_frame
    pending = {channel: bytearray() for channel in expected}
    count = sum(len(messages) for messages in expected.values())
    while count:
        wire = bytes([await read_byte(dut) for _ in range(width + 2)])
        frame = util.decode_frames(wire)[0]
        channel = frame.channel_id
        assert channel in expected and expected[channel], f"Unexpected response channel {channel}"
        assert frame.out_sop == (len(pending[channel]) == 0)
        pending[channel].extend(frame.out_data.to_bytes(width, "big"))
        if frame.out_eop:
            message = expected[channel].popleft()
            assert pending[channel][:len(message)] == message
            assert pending[channel][len(message):] == bytes(-len(message) % width)
            pending[channel].clear()
            count -= 1


@cocotb.test()
async def test_admin_echo(dut) -> None:
    util = await start(dut)
    payload = bytes(range(128))
    request = make_echo_request(0x12345678, 0, payload)
    reply = make_echo_response(0, 0x12345678, payload)
    receiver = cocotb.start_soon(check_responses(dut, util, {ChannelId.ADMIN: deque([reply])}))
    await send_wire(dut, b"".join(frames(util, ChannelId.ADMIN, request)))
    await with_timeout(receiver, 3, "ms")


@cocotb.test()
@cocotb.parametrize(payload_size=[0, 16])
async def test_programming_then_raw_stimulus_reaction(dut, payload_size) -> None:
    util = await start(dut)
    condition_id, reaction_id = 1, 1
    reaction_payload = bytes(range(payload_size))
    requests = [
        make_program_condition(7, 0, condition_id, reaction_id, b"match"),
        make_program_reaction(19, 0, reaction_id, reaction_payload),
    ]
    receiver = cocotb.start_soon(check_responses(
        dut, util, {ChannelId.PROGRAM_ACTIONS: deque([make_ack(0, 7), make_ack(12, 19)])}))
    for request in requests:
        await send_wire(dut, b"".join(frames(
            util, ChannelId.PROGRAM_ACTIONS, request)))
    await with_timeout(receiver, 3, "ms")

    for request_id in (0x0123456789ABCDEF, 0xFEDCBA9876543210):
        reaction = make_reaction(request_id, condition_id, reaction_payload)
        receiver = cocotb.start_soon(check_responses(
            dut, util, {ChannelId.TRIGGER: deque([reaction])}))
        await send_wire(dut, b"".join(frames(
            util, ChannelId.TRIGGER, make_stimulus(request_id, b"before match after"))))
        await with_timeout(receiver, 3, "ms")


@cocotb.test()
async def test_stimulus_to_first_response_latency(dut) -> None:
    """Measure the handshake-to-handshake interval defined by EXPECTED_LATENCY."""
    # Latency in clock cycles, measured between rising-edge handshakes:
    # START: the evaluator accepts the stimulus payload beat containing the final
    #        pattern byte (stimulus.valid && stimulus_ready). In this test,
    #        this is also the final payload beat (EOP).
    # STOP:  afk_main's first TRIGGER response beat transfers to the UART channel
    #        endpoint (response_valid && response_ready && response_sop).
    # The table is idle, other response sources are idle, and the endpoint is ready.
    # This excludes UART reception/serialization and stimulus header parsing.
    # Four stages: matcher-result register, fire_ff, table request acceptance
    # with synchronous RAM read, response arbiter register. The stop timestamp
    # is the edge consuming the arbiter's output, not when valid first rises.
    EXPECTED_LATENCY = 4

    util = await start(dut)
    width = util.num_payload_bytes_per_channel_frame
    condition_id, reaction_id, request_id = 1, 1, 0x0123456789ABCDEF
    pattern, reaction_payload = b"AB", b"latency response"
    receiver = cocotb.start_soon(check_responses(dut, util, {
        ChannelId.PROGRAM_ACTIONS: deque([make_ack(0, 7), make_ack(12, 19)]),
    }))
    for request in (
        make_program_condition(7, 0, condition_id, reaction_id, pattern),
        make_program_reaction(19, 0, reaction_id, reaction_payload),
    ):
        await send_wire(dut, b"".join(frames(util, ChannelId.PROGRAM_ACTIONS, request)))
    await with_timeout(receiver, 3, "ms")

    async def measure_latency():
        start_ns = None
        while True:
            # Snapshot settled signals before the transfer edge. Reading after
            # that edge could see the next beat or freshly updated registers.
            await FallingEdge(dut.clk)
            await ReadOnly()
            stimulus = int(dut.stimulus.value)
            stimulus_valid = bool(stimulus >> (len(dut.stimulus) - 1))
            # Packed stimulus ends with {sop, eop, request_id[63:0]}.
            stimulus_eop = bool((stimulus >> 64) & 1)
            start_transfer = (stimulus_valid and stimulus_eop
                              and bool(dut.stimulus_ready.value))
            response_transfer = (bool(dut.response_valid.value)
                                 and bool(dut.response_ready.value)
                                 and bool(dut.response_sop.value)
                                 and int(dut.response_channel_id.value) == ChannelId.TRIGGER)
            if start_transfer:
                assert start_ns is None, "Unexpected second stimulus EOP"
                assert dut.reaction_table_load_ready.value, "Reaction table must be idle"
            if start_transfer or start_ns is not None:
                assert dut.response_ready.value, "Latency measurement requires no backpressure"
                assert not dut.admin_valid.value and not dut.program_actions_valid.value, \
                    "Latency measurement requires no competing responses"

            await RisingEdge(dut.clk)
            if start_transfer:
                start_ns = get_sim_time(unit="ns")
            if response_transfer:
                assert start_ns is not None, "Reaction arrived before matching stimulus"
                elapsed_ns = get_sim_time(unit="ns") - start_ns
                cycles = elapsed_ns / CLOCK_NS
                dut._log.info("Stimulus acceptance to first response transfer: %g cycles (%g ns)",
                              cycles, elapsed_ns)
                assert cycles == EXPECTED_LATENCY, \
                    f"Expected {EXPECTED_LATENCY} cycles, measured {cycles:g} cycles"
                return

    monitor = cocotb.start_soon(measure_latency())
    receiver = cocotb.start_soon(check_responses(dut, util, {
        ChannelId.TRIGGER: deque([make_reaction(request_id, condition_id, reaction_payload)]),
    }))
    # The pattern crosses a payload beat boundary and completes only at EOP,
    # making the start event unambiguous for every tested channel width.
    payload = b"x" * (width - 1) + pattern
    await send_wire(dut, b"".join(frames(
        util, ChannelId.TRIGGER, make_stimulus(request_id, payload))))
    await with_timeout(monitor, 3, "ms")
    await with_timeout(receiver, 3, "ms")


@cocotb.test()
async def test_admin_echo_with_interleaved_programming_frames(dut) -> None:
    util = await start(dut)
    payload = bytes(range(128))
    admin_frames = frames(util, ChannelId.ADMIN, make_echo_request(7, 0, payload))
    program_frames = frames(util, ChannelId.PROGRAM_ACTIONS, make_program_reaction(19, 0, 0, b"reaction"))
    expected = {ChannelId.ADMIN: deque([make_echo_response(0, 7, payload)]),
                ChannelId.PROGRAM_ACTIONS: deque([make_ack(0, 19)])}
    receiver = cocotb.start_soon(check_responses(dut, util, expected))
    for pair in zip_longest(admin_frames, program_frames):
        for frame in pair:
            if frame is not None:
                await send_wire(dut, frame)
    await with_timeout(receiver, 3, "ms")


@cocotb.test()
@cocotb.parametrize(channel=[ChannelId.TRIGGER, ChannelId.PROGRAM_ACTIONS])
async def test_unsupported_request_is_discarded(dut, channel) -> None:
    util = await start(dut)
    reply = make_ack(0, 7)
    receiver = cocotb.start_soon(check_responses(dut, util, {ChannelId.ADMIN: deque([reply])}))
    request = make_test_request(99, 0)
    await send_wire(dut, b"".join(frames(util, channel, request)))
    await send_wire(dut, b"".join(frames(util, ChannelId.ADMIN, make_test_request(7, 0))))
    await with_timeout(receiver, 3, "ms")


@cocotb.test()
async def test_disable_condition_stops_only_selected_condition(dut) -> None:
    util = await start(dut)
    reaction_payload = b"response"
    requests = [
        make_program_condition(7, 0, 0, 0, b"first"),
        make_program_condition(19, 0, 1, 0, b"second"),
        make_program_reaction(31, 0, 0, reaction_payload),
    ]
    receiver = cocotb.start_soon(check_responses(dut, util, {
        ChannelId.PROGRAM_ACTIONS: deque([make_ack(0, 7), make_ack(12, 19), make_ack(24, 31)]),
    }))
    for request in requests:
        await send_wire(dut, b"".join(frames(util, ChannelId.PROGRAM_ACTIONS, request)))
    await with_timeout(receiver, 3, "ms")

    # Confirm the condition fires before disabling it.
    receiver = cocotb.start_soon(check_responses(dut, util, {
        ChannelId.TRIGGER: deque([make_reaction(1, 0, reaction_payload)]),
    }))
    await send_wire(dut, b"".join(frames(util, ChannelId.TRIGGER, make_stimulus(1, b"first"))))
    await with_timeout(receiver, 3, "ms")

    receiver = cocotb.start_soon(check_responses(dut, util, {
        ChannelId.PROGRAM_ACTIONS: deque([make_ack(36, 43)]),
    }))
    await send_wire(dut, b"".join(frames(util, ChannelId.PROGRAM_ACTIONS, make_disable_condition(43, 0, 0))))
    await with_timeout(receiver, 3, "ms")

    # A response to "first" would be unexpected; "second" must still trigger.
    receiver = cocotb.start_soon(check_responses(dut, util, {
        ChannelId.TRIGGER: deque([make_reaction(3, 1, reaction_payload)]),
        ChannelId.ADMIN: deque([make_ack(0, 55)]),
    }))
    for request_id, text in [(2, b"first"), (3, b"second")]:
        await send_wire(dut, b"".join(frames(util, ChannelId.TRIGGER, make_stimulus(request_id, text))))
    await send_wire(dut, b"".join(frames(util, ChannelId.ADMIN, make_test_request(55, 0))))
    await with_timeout(receiver, 3, "ms")
