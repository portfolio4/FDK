"""Streaming admin echo and header-only TestRequest acknowledgments."""

import struct

import cocotb
from cocotb.triggers import Timer

from tests.apps.afk.fpga.message_helpers import (
    HEADER_BYTES, Message, parse_message, make_ack, make_echo_request, make_echo_response, make_message_header, make_test_request,
)
from tests.apps.afk.fpga.channel_helpers import make_channel_beats


def assert_response_is_correct(actual: Message, expected: Message) -> None:
    assert actual.msg_type == expected.msg_type
    assert actual.ack_seq == expected.ack_seq
    assert actual.size == expected.size
    assert actual.payload == expected.payload


class Driver:
    def __init__(self, dut):
        self.dut = dut
        self.width = int(dut.CHANNEL_PAYLOAD_BYTES.value)
        self.responses: list[Message] = []
        self.transfers = 0
        self.pending = None
        self.stalled = None

    async def tick(self, beat=None, *, ready=True, reset=False):
        dut = self.dut
        dut.clk.value = 0
        dut.rst.value = reset
        dut.in_data.value = beat.data if beat else 0
        dut.in_sop.value = beat.sop if beat else 0
        dut.in_eop.value = beat.eop if beat else 0
        dut.in_valid.value = beat is not None
        dut.out_ready.value = ready
        await Timer(5, unit="ns")
        accepted = beat is not None and bool(dut.in_ready.value) and not reset
        values = tuple(int(signal.value) for signal in (
            dut.out_valid, dut.out_sop, dut.out_eop, dut.out_data,
        ))
        valid, sop, eop, data = values
        if reset:
            self.stalled = self.pending = None
            assert not dut.in_ready.value and not valid
        else:
            if self.stalled is not None:
                assert values == self.stalled
            self.stalled = values if valid and not ready else None
            if valid and ready:
                self.transfers += 1
                if sop:
                    assert self.pending is None
                    self.pending = bytearray()
                assert self.pending is not None
                self.pending.extend(data.to_bytes(self.width, "big"))
                if eop:
                    size, = struct.unpack_from("<H", self.pending)
                    assert HEADER_BYTES <= size <= len(self.pending)
                    assert not any(self.pending[size:])
                    self.responses.append(parse_message(bytes(self.pending)))
                    self.pending = None
        dut.clk.value = 1
        await Timer(5, unit="ns")
        return accepted

    async def reset(self):
        await self.tick(reset=True)
        self.responses.clear()
        self.transfers = 0
        await self.tick()

    async def send_beats(self, beats, *, ready=True):
        for beat in beats:
            for _ in range(500):
                if await self.tick(beat, ready=ready):
                    break
            else:
                raise AssertionError("Input channel frame remained stalled")

    async def send(self, message, *, ready=True):
        await self.send_beats(make_channel_beats(message, self.width), ready=ready)
        # Allow the receiver to emit the final aligned payload beat.
        await self.drain(4, ready=ready)

    async def drain(self, count=None, *, ready=True):
        if count is None:
            count = 2 * (140 // self.width + 1) + 16
        for _ in range(count):
            await self.tick(ready=ready)


@cocotb.test()
async def test_echo_request_produces_echo_response(dut):
    driver = Driver(dut)
    await driver.reset()
    payload = bytes(range(128))
    request_seq = 0x12345678
    await driver.send(make_echo_request(request_seq, 0, payload))
    await driver.drain()
    assert len(driver.responses) == 1
    assert_response_is_correct(
        driver.responses[0], parse_message(make_echo_response(0, request_seq, payload)),
    )


@cocotb.test()
async def test_test_request_produces_empty_ack(dut):
    driver = Driver(dut)
    await driver.reset()
    await driver.send(make_test_request(0x98765432, 0))
    await driver.drain()
    assert len(driver.responses) == 1
    assert_response_is_correct(driver.responses[0], parse_message(make_ack(0, 0x98765432)))


@cocotb.test()
async def test_ack_backpressure_preserves_pending_response(dut):
    driver = Driver(dut)
    await driver.reset()
    await driver.send(make_test_request(7, 0), ready=False)
    await driver.drain(16, ready=False)
    assert driver.stalled is not None
    await driver.drain()
    assert len(driver.responses) == 1
    assert_response_is_correct(driver.responses[0], parse_message(make_ack(0, 7)))


@cocotb.test()
async def test_unknown_message_type_is_discarded(dut):
    driver = Driver(dut)
    await driver.reset()
    await driver.send(make_message_header(7, 0, 0xFFFF))
    await driver.drain()
    assert driver.responses == []


@cocotb.test()
async def test_incorrect_echo_size_is_discarded(dut):
    driver = Driver(dut)
    await driver.reset()
    await driver.send(make_message_header(7, 0, 1, body_size=127) + bytes(128))
    await driver.drain()
    assert driver.responses == []


@cocotb.test()
async def test_reset_discards_pending_ack(dut):
    driver = Driver(dut)
    await driver.reset()
    await driver.send(make_test_request(7, 0), ready=False)
    await driver.reset()
    await driver.drain()
    assert driver.responses == []


@cocotb.test()
async def test_echo_and_test_requests_share_response_stream(dut):
    driver = Driver(dut)
    await driver.reset()
    payload = bytes(range(128))
    await driver.send(make_echo_request(7, 0, payload))
    await driver.send(make_test_request(19, 0))
    await driver.send(make_echo_request(31, 0, payload[::-1]))
    await driver.drain()
    expected_responses = [
        parse_message(make_echo_response(0, 7, payload)),
        parse_message(make_ack(0, 19)),
        parse_message(make_echo_response(0, 31, payload[::-1])),
    ]
    assert len(driver.responses) == len(expected_responses)
    for actual, expected in zip(driver.responses, expected_responses):
        assert_response_is_correct(actual, expected)


@cocotb.test()
async def test_pending_ack_survives_next_request_type(dut):
    driver = Driver(dut)
    await driver.reset()
    # Fill TX, then leave another Ack pending while RX advances to an echo.
    await driver.send(make_test_request(7, 0), ready=False)
    await driver.send(make_test_request(19, 0), ready=False)
    payload = bytes(range(128))
    beats = make_channel_beats(make_echo_request(31, 0, payload), driver.width)
    prefix = min(len(beats), (HEADER_BYTES + driver.width - 1) // driver.width + 1)
    await driver.send_beats(beats[:prefix], ready=False)
    await driver.drain(4, ready=False)
    await driver.send_beats(beats[prefix:])
    await driver.drain()
    expected_responses = [
        parse_message(make_ack(0, 7)),
        parse_message(make_ack(0, 19)),
        parse_message(make_echo_response(0, 31, payload)),
    ]
    assert len(driver.responses) == len(expected_responses)
    for actual, expected in zip(driver.responses, expected_responses):
        assert_response_is_correct(actual, expected)
