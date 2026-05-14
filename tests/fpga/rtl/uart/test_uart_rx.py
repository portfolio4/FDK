import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

import tests.fpga.rtl.uart.config


async def reset(dut) -> None:
    dut.rst.value = 1
    dut.rx.value = 1

    for _ in range(3):
        await FallingEdge(dut.clk)

    dut.rst.value = 0

def assert_byte_invalid(dut) -> None:
    assert(dut.rx_byte_valid.value == 0), "rx_byte_valid should be low before entire byte is transmitted"
    assert dut.framing_error.value == 0, "framing_error should be low during transmission"

def assert_byte_valid(dut, expected_byte: int) -> None:
    assert dut.rx_byte_valid.value == 1, "rx_byte_valid should be high immediately after entire byte is transmitted"
    assert dut.rx_byte.value == expected_byte, "rx_byte should be correct"
    assert dut.framing_error.value == 0, "framing_error should be low after proper transmission"

async def wait_metastability_cycles(dut) -> None:
    # It takes 3 cycles for an rx bit to propagate through rx_sync into the
    # the FPGA logic that actually processes it
    for _ in range(3):
        assert dut.rx_byte_valid.value == 0, "rx_byte_valid should be low during metastability cycles accounting"
        await FallingEdge(dut.clk)

@cocotb.test()
async def test_rst(dut) -> None:
    dut.rst.value = 1
    dut.rx.value = 1
    cocotb.start_soon(Clock(dut.clk, tests.fpga.rtl.uart.config.CLOCK_PERIOD_NS, unit="ns").start())

    for _ in range(10):
        await FallingEdge(dut.clk)
        assert dut.rx_byte_valid.value == 0, "rx_byte should be invalid during reset"
        assert dut.framing_error.value == 0, "framing_error should be low during reset"

    dut.rst.value = 0

    for _ in range(10):
        await FallingEdge(dut.clk)
        assert dut.rx_byte_valid.value  == 0, "rx_byte should be invalid during non-valid data"
        assert dut.framing_error.value == 0, "framing_error should be low during non-valid data"


@cocotb.test()
@cocotb.parametrize(rx_byte=[0b00000000, 0b11111111, 0b01101011, 0b11010110, 0b10000000, 0b00000001])
async def test_receive_byte(dut, rx_byte: int) -> None:
    cocotb.start_soon(Clock(dut.clk, tests.fpga.rtl.uart.config.CLOCK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    dut.rst.value = 0

    rx_bits = [0] + [
        (rx_byte >> bit_index) & 1
        for bit_index in range(8)
    ]

    for bit in rx_bits:
        dut.rx.value = bit
        for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
            assert_byte_invalid(dut)
            await FallingEdge(dut.clk)

    # transmit stop bit
    dut.rx.value = 1
    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES // 2):
        assert_byte_invalid(dut)
        await FallingEdge(dut.clk)

    await wait_metastability_cycles(dut)

    assert_byte_valid(dut, rx_byte)

    # rx_byte_valid should just be a pulse, next cycle should become invalid
    await FallingEdge(dut.clk)
    assert(dut.rx_byte_valid.value == 0), "rx_byte_valid should pulse"


@cocotb.test()
async def test_rst_during_receive(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, tests.fpga.rtl.uart.config.CLOCK_PERIOD_NS, unit="ns").start())

    await reset(dut)

    dut.rst.value = 0

    rx_byte = 0b01101011
    rx_bits = [0] + [1, 1, 0, 1, 0, 1, 1, 0]

    # reset during start bit
    dut.rx.value = 0
    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES // 2):
        assert_byte_invalid(dut)
        await FallingEdge(dut.clk)

    dut.rst.value = 1
    await FallingEdge(dut.clk)
    assert_byte_invalid(dut)
    dut.rst.value = 0
    # ------------------------ #


    # reset during a payload bit
    for bit in rx_bits[:5]:
        dut.rx.value = bit
        for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
            assert_byte_invalid(dut)
            await FallingEdge(dut.clk)

    dut.rst.value = 1
    await FallingEdge(dut.clk)
    assert_byte_invalid(dut)
    dut.rst.value = 0
    # ------------------------ #

    # reset during stop bit
    for bit in rx_bits:
        dut.rx.value = bit
        for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
            assert_byte_invalid(dut)
            await FallingEdge(dut.clk)

    dut.rx.value = 1
    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES // 2 - 1):
        assert_byte_invalid(dut)
        await FallingEdge(dut.clk)

    dut.rst.value = 1
    await FallingEdge(dut.clk)
    assert_byte_invalid(dut)
    dut.rst.value = 0
    # ------------------------ #

    # receive proper bit afterwards
    for bit in rx_bits:
        dut.rx.value = bit
        for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
            assert_byte_invalid(dut)
            await FallingEdge(dut.clk)

    dut.rx.value = 1
    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES // 2):
        assert_byte_invalid(dut)
        await FallingEdge(dut.clk)

    await wait_metastability_cycles(dut)

    assert_byte_valid(dut, rx_byte)

@cocotb.test()
async def test_framing_error(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, tests.fpga.rtl.uart.config.CLOCK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    dut.rst.value = 0
    rx_byte = 0b01101011
    rx_bits = [0] + [1, 1, 0, 1, 0, 1, 1, 0]

    for bit in rx_bits:
        dut.rx.value = bit
        for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
            assert_byte_invalid(dut)
            await FallingEdge(dut.clk)

    dut.rx.value = 1
    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES // 2 - 1):
        assert_byte_invalid(dut)
        await FallingEdge(dut.clk)

    dut.rx.value = 0
    assert_byte_invalid(dut)
    await FallingEdge(dut.clk)

    await wait_metastability_cycles(dut)

    assert dut.rx_byte_valid.value == 0, "rx_byte_valid should be low on framing error"
    assert dut.framing_error.value == 1, "framing_error should be high on framing error"

    await FallingEdge(dut.clk)
    assert dut.framing_error.value == 0, "framing_error should only pulse"
