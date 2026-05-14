"""Build and run the AFK core Catch2 executable through pytest."""

from pathlib import Path
import subprocess

import build_tools.common


def test_server_executable(host_build_dir: Path) -> None:
    build_tools.common.build_host(host_build_dir, ["test_afk_core"])

    subprocess.run(
        [str(build_tools.common.executable_path(host_build_dir, "test_afk_core"))],
        check=True,
        timeout=30,
    )
