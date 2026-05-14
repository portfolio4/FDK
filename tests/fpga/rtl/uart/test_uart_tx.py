import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

import tests.fpga.rtl.uart.config


async def reset(dut) -> None:
    dut.rst.value = 1
    dut.valid.value = 0
    dut.data.value = 0

    for _ in range(3):
        await FallingEdge(dut.clk)

    dut.rst.value = 0

@cocotb.test()
async def test_rst(dut) -> None:
    dut.rst.value = 1
    dut.valid.value = 0
    dut.data.value = 0
    cocotb.start_soon(Clock(dut.clk, tests.fpga.rtl.uart.config.CLOCK_PERIOD_NS, unit="ns").start())

    for _ in range(10):
        await FallingEdge(dut.clk)
        assert dut.tx.value  == 1, "TX should be high during reset"

    dut.rst.value = 0
    dut.valid.value = 0
    for _ in range(10):
        await FallingEdge(dut.clk)
        assert dut.tx.value  == 1, "TX should be high during non-valid data"

@cocotb.test()
@cocotb.parametrize(tx_byte=[0b00000000, 0b11111111, 0b01101011, 0b11010110, 0b10000000, 0b00000001])
async def test_transmit_byte(dut, tx_byte: int) -> None:
    cocotb.start_soon(Clock(dut.clk, tests.fpga.rtl.uart.config.CLOCK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    dut.rst.value = 0
    dut.valid.value = 1

    dut.data.value = tx_byte
    # note: UART sends least significant bit first
    expected_transmissions = [
        (tx_byte >> bit_index) & 1
        for bit_index in range(8)
    ]

    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
        await FallingEdge(dut.clk)
        assert dut.tx.value == 0, "TX should be 0 when to indicate start of transmit"
        assert dut.ready.value == 0, "DUT should not be ready mid transmission"

    for expected in expected_transmissions:
        for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
            await FallingEdge(dut.clk)
            assert dut.tx.value == expected, "TX did not transmit correct value"
            assert dut.ready.value == 0, "DUT should not be ready mid transmission"

        # flip every bit midway through transmission to ensure it doesn't affect
        # the current transmission
        dut.data.value = int(dut.data.value) ^ 0xFF

    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
        await FallingEdge(dut.clk)
        assert dut.tx.value == 1, "TX should be 1 when to indicate end of transmit"
        assert dut.ready.value == 0, "DUT should not be ready mid transmission"

    dut.valid.value = 0
    for _ in range(10):
        await FallingEdge(dut.clk)
        assert dut.ready.value == 1, "DUT should be ready post transmission"
        assert dut.tx.value == 1, "TX should be high post transmission"

@cocotb.test()
async def test_rst_mid_transmission(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, tests.fpga.rtl.uart.config.CLOCK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    dut.rst.value = 0
    dut.valid.value = 1

    dut.data.value = 0b11010110
    # note: UART sends least significant bit first
    expected_transmissions = [0, 1, 1, 0, 1, 0, 1, 1]

    # reset during the start-of-transmission bit
    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES // 2):
        await FallingEdge(dut.clk)
        assert dut.tx.value == 0, "TX should be 0 when to indicate start of transmit"

    dut.rst.value = 1
    for _ in range(10):
        await FallingEdge(dut.clk)
        assert dut.tx.value == 1, "TX should be 1 on reset"
    dut.rst.value = 0
    # ---------------------------------- #

    # reset during a payload bit
    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
        await FallingEdge(dut.clk)
        assert dut.tx.value == 0, "TX should be 0 when to indicate start of transmit"

    for expected in expected_transmissions[:5]:
        for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
            await FallingEdge(dut.clk)
            assert dut.tx.value == expected, "TX did not transmit correct value"

    dut.rst.value = 1
    for _ in range(10):
        await FallingEdge(dut.clk)
        assert dut.tx.value == 1, "TX should be 1 on reset"
    dut.rst.value = 0
    # -------------------------------- #

    # successful normal transmission
    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
        await FallingEdge(dut.clk)
        assert dut.tx.value == 0, "TX should be 0 when to indicate start of transmit"

    for expected in expected_transmissions:
        for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
            await FallingEdge(dut.clk)
            assert dut.tx.value == expected, "TX did not transmit correct value"

    for _ in range(tests.fpga.rtl.uart.config.BAUD_PERIOD_CYCLES):
        await FallingEdge(dut.clk)
        assert dut.tx.value == 1, "TX should be 1 when to indicate end of transmit"

