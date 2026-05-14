import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer

import random
import pytest


async def reset(dut) -> None:
    dut.rst.value = 1
    dut.aligned_pattern.value = 0
    dut.pattern_mask.value = 0
    dut.load_new_pattern.value = 0
    dut.in_data.value = 0
    dut.in_byte_count.value = 0
    dut.in_valid.value = 0
    dut.out_ready.value = 0

    await FallingEdge(dut.clk)
    for _ in range(3):
        await FallingEdge(dut.clk)
        assert not dut.in_ready.value
        assert not dut.out_valid.value
        assert not dut.out_is_match.value

    dut.rst.value = 0

async def set_pattern(dut, pattern: str) -> None:
    dut.in_valid.value = 0
    capacity = len(dut.aligned_pattern) // 8
    encoded = pattern.encode("ascii").rjust(capacity, b"\x00")
    dut.aligned_pattern.value = int.from_bytes(encoded, "big")
    dut.pattern_mask.value = sum(1 << i for i, byte in enumerate(reversed(encoded)) if byte == 0)
    dut.load_new_pattern.value = 1
    await FallingEdge(dut.clk)
    dut.load_new_pattern.value = 0


def make_input_beats(dut, entire_string) -> list[str]:
    assert entire_string.isascii()
    input_width = len(dut.in_data) // 8
    return [
        entire_string[start:start+input_width]
        for start in range(0, len(entire_string), input_width)
    ]

def pick_random_pattern(dut, test_str, pattern_len: int | None = None) -> str:
    assert test_str.isascii()

    max_pattern_chars = len(dut.aligned_pattern) // 8
    if pattern_len is None:
        pattern_len = max_pattern_chars

    assert 1 <= pattern_len <= max_pattern_chars
    assert pattern_len <= len(test_str)

    start = random.randint(0, len(test_str) - pattern_len)
    return test_str[start:start+pattern_len]

def encode_string(s: str, width: int) -> int:
    s_bytes = s.encode("ascii")
    padding_bits = width - len(s_bytes) * 8
    return int.from_bytes(s.encode("ascii"), "big") << padding_bits

@cocotb.test()
async def test_reset(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    dut.rst.value = 0
    dut.out_ready.value = 1

    for _ in range(4):
        await FallingEdge(dut.clk)
        assert dut.in_ready.value
        assert not dut.out_valid.value
        assert not dut.out_is_match.value

@cocotb.test()
async def test_match(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    test_str = "hello this is just a test!!!!!!!"
    test_beats = make_input_beats(dut, test_str)
    test_pattern = pick_random_pattern(dut, test_str)

    await set_pattern(dut, test_pattern)
    dut.out_ready.value = True

    matched = False
    for beat in test_beats:
        dut.in_data.value = encode_string(beat, len(dut.in_data))
        dut.in_byte_count.value = len(beat)
        dut.in_valid.value = True
        await Timer(1, unit="ns")
        assert dut.out_valid.value == True
        matched |= bool(dut.out_is_match.value)
        await FallingEdge(dut.clk)

    assert(matched)

@cocotb.test()
async def test_no_match(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    test_str = "a" * 100
    test_beats = make_input_beats(dut, test_str)
    test_pattern = "b"

    await set_pattern(dut, test_pattern)
    dut.out_ready.value = True

    matched = False
    for beat in test_beats:
        dut.in_data.value = encode_string(beat, len(dut.in_data))
        dut.in_byte_count.value = len(beat)
        dut.in_valid.value = True
        await Timer(1, unit="ns")
        assert dut.out_valid.value == True
        matched |= bool(dut.out_is_match.value)
        await FallingEdge(dut.clk)

    assert not matched

@cocotb.test()
async def test_invalid_cycles(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    test_str = "this is a test with invalid beats"
    test_beats = make_input_beats(dut, test_str)
    test_pattern = pick_random_pattern(dut, test_str)

    await reset(dut)
    await set_pattern(dut, test_pattern)
    dut.out_ready.value = True
    matched = False
    for beat in test_beats:
        dut.in_data.value = encode_string(beat, len(dut.in_data))
        dut.in_byte_count.value = len(beat)
        dut.in_valid.value = True
        await Timer(1, unit="ns")
        assert dut.out_valid.value == True
        matched |= bool(dut.out_is_match.value)
        await FallingEdge(dut.clk)

        dut.in_valid.value = False
        await Timer(1, unit="ns")
        assert dut.out_valid.value == False
        await FallingEdge(dut.clk)
    assert(matched)

@cocotb.test()
async def test_backpressure(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    test_str = "abcdefghijklmnopqrstuvwxyz"
    test_beats = make_input_beats(dut, test_str)
    test_pattern = "y"

    await reset(dut)
    await set_pattern(dut, test_pattern)
    matched = False

    for beat in test_beats:
        # out_ready = False triggers backpressure
        dut.out_ready.value = False
        dut.in_data.value = encode_string(beat, len(dut.in_data))
        dut.in_byte_count.value = len(beat)
        dut.in_valid.value = True

        # while we're backpressured, new inputs should not be accepted
        for _ in range(10):
            await Timer(1, unit="ns")
            assert dut.in_ready.value == False
            assert dut.out_valid.value == True
            assert bool(dut.out_is_match.value) == (test_pattern in beat)
            await FallingEdge(dut.clk)

        # release backpressure
        dut.out_ready.value = True
        await Timer(1, unit="ns")
        assert dut.in_ready.value == True
        assert dut.out_valid.value == True
        assert bool(dut.out_is_match.value) == (test_pattern in beat)
        await FallingEdge(dut.clk)

@cocotb.test()
async def test_rst_middle_of_operation(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    input_bytes = len(dut.in_data) // 8
    if input_bytes < 2:
        pytest.skip("Cross-beat reset test requires at least two bytes per beat")
    test_beat1 = "a" * (input_bytes - 2) + "cd"
    test_beat2 = "ef" + "b" * (input_bytes - 2)
    test_pattern = "cdef"

    if (
        len(test_beat1) * 8 > len(dut.in_data)
        or len(test_beat2) * 8 > len(dut.in_data)
        or len(test_pattern) * 8 > len(dut.aligned_pattern)
    ):
        pytest.skip("Both input beats and the pattern must fit their signal widths")

    await set_pattern(dut, test_pattern)
    dut.out_ready.value = True

    dut.in_data.value = encode_string(test_beat1, len(dut.in_data))
    dut.in_byte_count.value = len(test_beat1)
    dut.in_valid.value = True

    await Timer(1, unit="ns")
    assert dut.in_ready.value == True
    assert dut.out_valid.value == True
    assert bool(dut.out_is_match.value) == False
    await FallingEdge(dut.clk)

    # reset should clear the history, so that when we issue beat2, it doesn't work
    await reset(dut)
    await set_pattern(dut, test_pattern)
    dut.out_ready.value = True

    dut.in_data.value = encode_string(test_beat2, len(dut.in_data))
    dut.in_byte_count.value = len(test_beat2)
    dut.in_valid.value = True

    await Timer(1, unit="ns")
    assert dut.in_ready.value == True
    assert dut.out_valid.value == True
    assert bool(dut.out_is_match.value) == False
    await FallingEdge(dut.clk)

    # now it should match
    dut.in_data.value = encode_string(test_beat1, len(dut.in_data))
    dut.in_byte_count.value = len(test_beat1)
    dut.in_valid.value = True
    await FallingEdge(dut.clk)
    dut.in_data.value = encode_string(test_beat2, len(dut.in_data))
    dut.in_byte_count.value = len(test_beat2)
    dut.in_valid.value = True
    await Timer(1, unit="ns")
    assert dut.in_ready.value == True
    assert dut.out_valid.value == True
    assert bool(dut.out_is_match.value) == True
    await FallingEdge(dut.clk)

@cocotb.test()
async def test_exact_length_match(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    min_len = min(len(dut.in_data), len(dut.aligned_pattern))
    test_str = "a" * (min_len // 8)
    test_pattern = test_str

    await set_pattern(dut, test_pattern)
    dut.out_ready.value = True

    dut.in_data.value = encode_string(test_str, len(dut.in_data))
    dut.in_byte_count.value = len(test_str)
    dut.in_valid.value = True

    await Timer(1, unit="ns")
    assert dut.in_ready.value == True
    assert dut.out_valid.value == True
    assert bool(dut.out_is_match.value) == True
    await FallingEdge(dut.clk)

@cocotb.test()
async def overlapping_matches(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    test_str = "a" * 100
    test_beats = make_input_beats(dut, test_str)
    test_pattern = "a" * (len(dut.aligned_pattern) // 8)

    await reset(dut)
    await set_pattern(dut, test_pattern)
    dut.out_ready.value = True

    streamed_chars = 0
    for beat in test_beats:
        streamed_chars += len(beat)
        dut.in_data.value = encode_string(beat, len(dut.in_data))
        dut.in_byte_count.value = len(beat)
        dut.in_valid.value = True
        await Timer(1, unit="ns")
        assert dut.out_valid.value == True
        assert bool(dut.out_is_match.value) == (streamed_chars >= len(test_pattern))
        await FallingEdge(dut.clk)



@cocotb.test()
async def test_zero_pattern_bytes_are_wildcards(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)
    # A zero pattern byte must match a nonzero input byte.
    await set_pattern(dut, "\x00")
    dut.out_ready.value = 1
    dut.in_data.value = encode_string("q", len(dut.in_data))
    dut.in_byte_count.value = 1
    dut.in_valid.value = 1
    await Timer(1, unit="ns")
    assert dut.out_is_match.value == 1

    if len(dut.aligned_pattern) // 8 >= 3:
        await reset(dut)
        await set_pattern(dut, "A\x00B")
        dut.out_ready.value = 1
        matched = False
        for beat in make_input_beats(dut, "prefix AqB"):
            dut.in_data.value = encode_string(beat, len(dut.in_data))
            dut.in_byte_count.value = len(beat)
            dut.in_valid.value = 1
            await Timer(1, unit="ns")
            matched |= bool(dut.out_is_match.value)
            await FallingEdge(dut.clk)
        assert matched


@cocotb.test()
async def test_unused_input_lanes_are_zeroed(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    input_bytes = len(dut.in_data) // 8
    for byte_count in range(input_bytes + 1):
        for pattern in ("A", "B"):
            await reset(dut)
            await set_pattern(dut, pattern)
            # Valid bytes are A; every unused lane contains a potential false match.
            data = b"A" * byte_count + b"B" * (input_bytes - byte_count)
            dut.in_data.value = int.from_bytes(data, "big")
            dut.in_byte_count.value = byte_count
            dut.in_valid.value = 1
            expected = pattern == "A" and byte_count > 0
            # Check both stalled output and the eventual accepted beat.
            for ready in (0, 0, 1):
                dut.out_ready.value = ready
                await Timer(1, unit="ns")
                assert dut.out_valid.value == 1
                assert bool(dut.in_ready.value) == bool(ready)
                assert bool(dut.out_is_match.value) == expected
                await FallingEdge(dut.clk)


@cocotb.test()
async def test_cross_beat_match_with_dirty_final_padding(dut) -> None:
    input_bytes = len(dut.in_data) // 8
    if input_bytes < 2 or len(dut.aligned_pattern) < 16:
        pytest.skip("Requires two input and pattern bytes")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for byte_count in range(1, input_bytes):
        await reset(dut)
        await set_pattern(dut, "AB")
        dut.out_ready.value = 1
        dut.in_valid.value = 1
        dut.in_data.value = encode_string("x" * (input_bytes - 1) + "A", len(dut.in_data))
        dut.in_byte_count.value = input_bytes
        await FallingEdge(dut.clk)
        dut.in_data.value = int.from_bytes(b"B" + b"x" * (byte_count - 1) +
                                            b"B" * (input_bytes - byte_count), "big")
        dut.in_byte_count.value = byte_count
        await Timer(1, unit="ns")
        assert dut.out_valid.value == 1
        assert dut.out_is_match.value == 1


@cocotb.test()
async def test_full_beat_append_includes_zero_padding(dut) -> None:
    if len(dut.in_data) < 16 or len(dut.aligned_pattern) < 16:
        pytest.skip("Padding test requires two input and pattern bytes")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)
    await set_pattern(dut, "A\x00")
    dut.out_ready.value = 1
    dut.in_data.value = encode_string("A", len(dut.in_data))
    dut.in_byte_count.value = 1
    dut.in_valid.value = 1
    await Timer(1, unit="ns")
    assert dut.out_is_match.value == 1


@cocotb.test()
async def test_pattern_load_and_stream_reset(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)
    await set_pattern(dut, "A")
    dut.in_data.value = encode_string("A", len(dut.in_data))
    dut.in_byte_count.value = 1
    dut.in_valid.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")
    assert dut.out_is_match.value == 1

    # Prepared inputs may change for other matchers without changing this one.
    dut.aligned_pattern.value = ord("B")
    dut.in_valid.value = 0
    await FallingEdge(dut.clk)
    dut.in_valid.value = 1
    await Timer(1, unit="ns")
    assert dut.out_is_match.value == 1
    dut.in_valid.value = 0
    dut.load_new_pattern.value = 1
    await FallingEdge(dut.clk)
    dut.load_new_pattern.value = 0
    dut.in_valid.value = 1
    await Timer(1, unit="ns")
    assert dut.out_is_match.value == 0
    dut.in_data.value = encode_string("B", len(dut.in_data))
    await Timer(1, unit="ns")
    assert dut.out_is_match.value == 1

    # A changing mask is also ignored without a load. Stream reset must
    # preserve both the stored pattern and its original non-wildcard mask.
    dut.pattern_mask.value = (1 << len(dut.pattern_mask)) - 1
    dut.rst.value = 1
    dut.in_valid.value = 0
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    dut.in_valid.value = 1
    await Timer(1, unit="ns")
    assert dut.out_is_match.value == 1
    dut.in_data.value = encode_string("A", len(dut.in_data))
    await Timer(1, unit="ns")
    assert dut.out_is_match.value == 0
