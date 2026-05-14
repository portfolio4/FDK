from pathlib import Path

import pytest

import build_tools.common
import tests.fpga.rtl


@pytest.mark.parametrize(
    "input_width,payload_bytes",
    [(8, 8), (16, 8), (64, 8), (80, 8), (256, 8), (8, 16), (64, 16), (144, 16)],
)
def test_channel_rx(sim_build_dir: Path, input_width: int, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[],
        rtl_files=[build_tools.common.REPO_ROOT / "fpga/rtl/channel/channel_rx.sv"],
        hdl_toplevel="fdk_channel_rx",
        parameters={
            "INPUT_BEAT_WIDTH": input_width,
            "CHANNEL_PAYLOAD_BYTES": payload_bytes,
        },
        build_dir=sim_build_dir / f"channel_rx_{payload_bytes}_{input_width}",
        test_module="tests.fpga.rtl.channel.test_channel_rx",
    ).run()


@pytest.mark.parametrize(
    "output_width,payload_bytes",
    [(8, 8), (16, 8), (64, 8), (80, 8), (256, 8), (8, 16), (64, 16), (144, 16)],
)
def test_channel_tx(sim_build_dir: Path, output_width: int, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[],
        rtl_files=[build_tools.common.REPO_ROOT / "fpga/rtl/channel/channel_tx.sv"],
        hdl_toplevel="fdk_channel_tx",
        parameters={
            "OUTPUT_BEAT_WIDTH": output_width,
            "CHANNEL_PAYLOAD_BYTES": payload_bytes,
        },
        build_dir=sim_build_dir / f"channel_tx_{payload_bytes}_{output_width}",
        test_module="tests.fpga.rtl.channel.test_channel_tx",
    ).run()
