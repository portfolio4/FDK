"""Build prerequisites and run host tests and/or FPGA simulations through pytest."""

import argparse
import subprocess
import sys
from pathlib import Path

import build_tools.common
import build_tools.testing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=build_tools.common.REPO_ROOT / "tests",
                        help="Test suite directory (default: all tests)")
    parser.add_argument("--host-build-dir", type=Path)
    parser.add_argument("--mode", choices=build_tools.common.BUILD_MODES, default="debug",
                        help="Build mode and output directory (default: debug)")
    parser.add_argument("--sim-build-root", type=Path)
    arguments, forwarded = build_tools.common.split_arguments()
    args = parser.parse_args(arguments)
    build_root = build_tools.common.build_root(args.mode)
    host_dir = (args.host_build_dir or build_root / "host").resolve()
    sim_root = (args.sim_build_root or build_root / "sim").resolve()
    sim_root = build_tools.testing.simulation_root(sim_root)
    tests_dir = build_tools.common.REPO_ROOT / "tests"
    collection_dir = args.directory.resolve()
    if not collection_dir.is_dir() or not collection_dir.is_relative_to(tests_dir):
        parser.error(f"--directory must be a directory inside {tests_dir}")
    options = ["--mode", args.mode, "--sim-build-root", str(sim_root), "--host-build-dir", str(host_dir)]
    subprocess.run([sys.executable, "-m", "pytest", str(collection_dir), *options, *forwarded],
                   cwd=build_tools.common.REPO_ROOT, check=True)


if __name__ == "__main__":
    main()
