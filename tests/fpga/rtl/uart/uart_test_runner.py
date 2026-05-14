from pathlib import Path

import pytest

import fpga.rtl.uart
import tests.fpga.rtl
import tests.fpga.rtl.uart.config


@pytest.mark.parametrize("module", ["uart_tx", "uart_rx"])
def test_uart(sim_build_dir: Path, module: str) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.uart.LIBRARY],
        hdl_toplevel=f"fdk_{module}",
        parameters={
            "CLK_FREQ_HZ": tests.fpga.rtl.uart.config.CLK_FREQ_HZ,
            "BAUD_RATE": tests.fpga.rtl.uart.config.BAUD_RATE,
        },
        build_dir=sim_build_dir / module,
        test_module=f"tests.fpga.rtl.uart.test_{module}",
    ).run()
