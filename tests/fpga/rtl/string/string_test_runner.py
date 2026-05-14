from pathlib import Path

import pytest

import fpga.rtl.string
import tests.fpga.rtl


@pytest.mark.parametrize(
    "input_width, max_pattern_chars", [(8, 1), (8, 16), (8, 20), (32, 16), (128, 16)]
)
def test_fast_string_contains(
    sim_build_dir: Path, input_width: int, max_pattern_chars: int
) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.string.LIBRARY],
        hdl_toplevel="fdk_fast_string_contains",
        parameters={
            "INPUT_WIDTH": input_width,
            "MAX_PATTERN_CHARS": max_pattern_chars,
        },
        build_dir=sim_build_dir / f"fast_string_contains_{input_width}_{max_pattern_chars}",
        test_module="tests.fpga.rtl.string.test_fast_string_contains",
    ).run()
