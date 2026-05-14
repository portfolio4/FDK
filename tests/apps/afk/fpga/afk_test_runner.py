from pathlib import Path

import pytest

import apps.afk.fpga.build_fpga
import fpga.rtl.platforms.basys3
import tests.fpga.rtl


@pytest.mark.parametrize("payload_bytes", [1, 8, 10, 32, 100])
def test_stimulus_handler(sim_build_dir: Path, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.platforms.basys3.LIBRARY, *apps.afk.fpga.build_fpga.LIBRARIES],
        rtl_files=apps.afk.fpga.build_fpga.RTL_FILES,
        hdl_toplevel="afk_stimulus_handler",
        parameters={"CHANNEL_PAYLOAD_BYTES": payload_bytes},
        build_dir=sim_build_dir / f"stimulus_handler_{payload_bytes}",
        test_module="tests.apps.afk.fpga.test_stimulus_handler",
    ).run()


@pytest.mark.parametrize("payload_bytes", [1, 8, 16, 32])
def test_program_actions_handler(sim_build_dir: Path, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.platforms.basys3.LIBRARY, *apps.afk.fpga.build_fpga.LIBRARIES],
        rtl_files=[path for path in apps.afk.fpga.build_fpga.RTL_FILES if path.name != "afk_main.sv"],
        hdl_toplevel="afk_program_actions_handler",
        parameters={"CHANNEL_PAYLOAD_BYTES": payload_bytes},
        build_dir=sim_build_dir / f"program_actions_handler_{payload_bytes}",
        test_module="tests.apps.afk.fpga.test_program_actions_handler",
    ).run()


@pytest.mark.parametrize("reactions,payload_bytes", [(1, 1), (3, 8), (4, 16), (2, 128)])
def test_reaction_table(sim_build_dir: Path, reactions: int, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.platforms.basys3.LIBRARY, *apps.afk.fpga.build_fpga.LIBRARIES],
        rtl_files=apps.afk.fpga.build_fpga.RTL_FILES,
        hdl_toplevel="afk_reaction_table",
        parameters={"MAX_REACTIONS": reactions, "CHANNEL_PAYLOAD_BYTES": payload_bytes},
        build_dir=sim_build_dir / f"reaction_table_{reactions}_{payload_bytes}",
        test_module="tests.apps.afk.fpga.test_reaction_table",
    ).run()


@pytest.mark.parametrize("conditions,reactions,payload_bytes", [(1, 1, 1), (4, 3, 8), (8, 4, 16)])
def test_condition_evaluator(sim_build_dir: Path, conditions: int, reactions: int, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.platforms.basys3.LIBRARY, *apps.afk.fpga.build_fpga.LIBRARIES],
        rtl_files=apps.afk.fpga.build_fpga.RTL_FILES,
        hdl_toplevel="afk_condition_evaluator",
        parameters={"MAX_CONDITIONS": conditions, "MAX_REACTIONS": reactions,
                    "CHANNEL_PAYLOAD_BYTES": payload_bytes},
        build_dir=sim_build_dir / f"condition_evaluator_{conditions}_{reactions}_{payload_bytes}",
        test_module="tests.apps.afk.fpga.test_condition_evaluator",
    ).run()


@pytest.mark.parametrize("payload_bytes", [1, 8, 10, 16, 160])
def test_admin_handler(sim_build_dir: Path, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.platforms.basys3.LIBRARY, *apps.afk.fpga.build_fpga.LIBRARIES],
        rtl_files=apps.afk.fpga.build_fpga.RTL_FILES,
        hdl_toplevel="afk_admin_handler",
        parameters={"CHANNEL_PAYLOAD_BYTES": payload_bytes},
        build_dir=sim_build_dir / f"admin_handler_{payload_bytes}",
        test_module="tests.apps.afk.fpga.test_admin_handler",
    ).run()


@pytest.mark.parametrize("payload_bytes", [1, 8, 16, 32])
def test_afk_main(sim_build_dir: Path, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.platforms.basys3.LIBRARY, *apps.afk.fpga.build_fpga.LIBRARIES],
        rtl_files=apps.afk.fpga.build_fpga.RTL_FILES,
        hdl_toplevel="afk_main",
        parameters={"CLK_FREQ_HZ": 20_000_000, "BAUD_RATE": 1_000_000, "CHANNEL_PAYLOAD_BYTES": payload_bytes},
        build_dir=sim_build_dir / f"afk_main_{payload_bytes}",
        test_module="tests.apps.afk.fpga.test_afk_main",
    ).run()
