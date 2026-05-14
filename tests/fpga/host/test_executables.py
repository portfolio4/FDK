"""Run the channel and message Catch2 executables."""

from pathlib import Path
import subprocess

import pytest

import build_tools.common


@pytest.mark.parametrize("target", [
    "test_fdk_channel", "test_fdk_message", "test_fdk_message_sender", "test_fdk_message_reader",
])
def test_host_executable(host_build_dir: Path, target: str) -> None:
    build_tools.common.build_host(host_build_dir, [target])
    subprocess.run(
        [str(build_tools.common.executable_path(host_build_dir, target))],
        check=True,
        timeout=30,
    )
