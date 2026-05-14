from pathlib import Path

import pytest

import fpga.rtl.message
import tests.fpga.rtl


@pytest.mark.parametrize("payload_bytes", [8, 12, 160])
def test_echo_request_handler(sim_build_dir: Path, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.message.LIBRARY],
        hdl_toplevel="fdk_message_echo_request_handler",
        parameters={"CHANNEL_PAYLOAD_BYTES": payload_bytes},
        build_dir=sim_build_dir / f"echo_request_handler_{payload_bytes}",
        test_module="tests.fpga.rtl.message.test_echo_request_handler",
    ).run()


@pytest.mark.parametrize("payload_bytes", [1, 4, 8, 10, 12, 16, 32])
def test_message_rx(sim_build_dir: Path, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.message.LIBRARY],
        hdl_toplevel="fdk_message_rx",
        parameters={"CHANNEL_PAYLOAD_BYTES": payload_bytes},
        build_dir=sim_build_dir / f"message_rx_{payload_bytes}",
        test_module="tests.fpga.rtl.message.test_message_rx",
    ).run()


@pytest.mark.parametrize("payload_bytes", [1, 4, 8, 10, 12, 16, 32])
def test_message_tx(sim_build_dir: Path, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.message.LIBRARY],
        hdl_toplevel="fdk_message_tx",
        parameters={"CHANNEL_PAYLOAD_BYTES": payload_bytes},
        build_dir=sim_build_dir / f"message_tx_{payload_bytes}",
        test_module="tests.fpga.rtl.message.test_message_tx",
    ).run()
