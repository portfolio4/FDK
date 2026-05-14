"""Paths and subprocess helpers shared by the root entry points."""

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_MODES = {"debug", "release"}


def build_root(mode: str = "debug") -> Path:
    if mode not in BUILD_MODES:
        raise ValueError(f"Unsupported build mode: {mode}")
    return REPO_ROOT / f"build_{mode}"


def host_build_directory(mode: str = "debug") -> Path:
    return build_root(mode) / "host"


def application_directory(value: Path) -> Path:
    directory = value.resolve()
    try:
        directory.relative_to(REPO_ROOT)
    except ValueError:
        raise ValueError("--directory must be inside this repository") from None
    if not directory.is_dir():
        raise ValueError(f"Application directory does not exist: {directory}")
    return directory


def fpga_build_directory(directory: Path, mode: str = "debug") -> Path:
    directory = application_directory(directory)
    return build_root(mode) / "fpga" / directory.relative_to(REPO_ROOT)


def executable_path(build_dir: Path, target: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*", target):
        raise ValueError("--target must be a target name, not a path or option")
    return build_dir.resolve() / "bin" / target


def configure_host(build_dir: Path, *, mode: str | None = None) -> None:
    cmake_build_types = {"debug": "Debug", "release": "Release"}
    build_dir = build_dir.resolve()
    command = ["cmake", "-S", str(REPO_ROOT), "-B", str(build_dir)]
    new_build = not (build_dir / "CMakeCache.txt").exists()

    selected_mode = None
    if mode is not None:
        selected_mode = mode
    elif new_build:
        # Default to debug builds in new builds. Existing builds keep their build type.
        selected_mode = "debug"
    if selected_mode is not None:
        command += [f"-DCMAKE_BUILD_TYPE={cmake_build_types[selected_mode]}"]

    if new_build:
        command += ["-DBUILD_TESTING=ON"]
    subprocess.run(command, check=True)


def build_host(build_dir: Path, targets: list[str] | None = None, *, mode: str | None = None) -> None:
    if targets:
        for target in targets:
            executable_path(build_dir, target)
    configure_host(build_dir, mode=mode)
    command = ["cmake", "--build", str(build_dir.resolve()), "--parallel"]
    if targets:
        command += ["--target", *targets]
    subprocess.run(command, check=True)


def invoke_fpga(directory: Path, action: str, build_dir: Path | None = None, *, mode: str = "debug") -> None:
    directory = application_directory(directory)
    parts = directory.relative_to(REPO_ROOT).parts
    if not all(part.isidentifier() for part in parts):
        raise ValueError("FPGA application paths must use Python package identifiers")
    module_name = ".".join((*parts, action))
    if not (directory / f"{action}.py").is_file():
        raise ValueError(f"Application does not support this action: missing {action}.py in {directory}")
    output_dir = build_dir.resolve() if build_dir is not None else fpga_build_directory(directory, mode)
    command = [sys.executable, "-u", "-m", module_name, "--build-dir", str(output_dir)]
    print(shlex.join(command), flush=True)
    subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=True,
    )


def split_arguments(argv: list[str] | None = None) -> tuple[list[str], list[str]]:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--" not in args:
        return args, []
    index = args.index("--")
    return args[:index], args[index + 1:]


def application_parser(description: str | None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description,
        epilog="Applications may live anywhere in this repository, including examples/ and apps/.")
    parser.add_argument("--platform", choices=("host", "fpga"), required=True)
    parser.add_argument("--directory", type=Path, help="Application directory (required for fpga)")
    parser.add_argument("--target")
    parser.add_argument("--mode", choices=BUILD_MODES, default="debug",
                        help="Build mode and output directory (default: debug)")
    parser.add_argument("--build-dir", type=Path)
    return parser


def validate_application_options(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> Path | None:
    if args.platform == "host":
        if not args.target:
            parser.error("host requires --target")
        executable_path(args.build_dir or host_build_directory(args.mode), args.target)
        return application_directory(args.directory) if args.directory is not None else None
    elif args.platform == "fpga":
        if args.target is not None:
            parser.error("fpga does not accept --target")
        if args.directory is None:
            parser.error("fpga requires --directory")
        return application_directory(args.directory)
    else:
        parser.error(f"Unsupported platform: {args.platform}")

