"""Mode selection across the build and run entry points."""

import sys

import pytest

import build
import build_tools.common as common
import run


@pytest.mark.parametrize("mode,cmake_type", [("debug", "Debug"), ("release", "Release")])
def test_build_mode_selects_directory_and_configuration(monkeypatch, mode, cmake_type):
    commands = []
    monkeypatch.setattr(common.subprocess, "run", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(sys, "argv", ["build.py", "--platform", "host", "--target", "afk_host", "--mode", mode])

    build.main()

    output = common.REPO_ROOT / f"build_{mode}" / "host"
    assert commands[0][:5] == ["cmake", "-S", str(common.REPO_ROOT), "-B", str(output)]
    assert f"-DCMAKE_BUILD_TYPE={cmake_type}" in commands[0]
    assert commands[1] == ["cmake", "--build", str(output), "--parallel", "--target", "afk_host"]


@pytest.mark.parametrize("mode", ["debug", "release"])
def test_run_uses_matching_mode_and_forwards_arguments(monkeypatch, mode):
    commands = []
    monkeypatch.setattr(common.subprocess, "run", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(sys, "argv", ["run.py", "--platform", "host", "--target", "afk_host",
                                     "--mode", mode, "--", "mount-afk"])

    run.main()

    assert commands == [[str(common.REPO_ROOT / f"build_{mode}" / "host" / "bin" / "afk_host"), "mount-afk"]]


def test_explicit_mode_updates_existing_custom_build(monkeypatch, tmp_path):
    (tmp_path / "CMakeCache.txt").write_text("CMAKE_BUILD_TYPE:STRING=Debug\n")
    commands = []
    monkeypatch.setattr(common.subprocess, "run", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(sys, "argv", ["build.py", "--platform", "host", "--target", "afk_host",
                                     "--mode", "release", "--build-dir", str(tmp_path)])

    build.main()

    assert commands[0][4] == str(tmp_path)
    assert "-DCMAKE_BUILD_TYPE=Release" in commands[0]
    assert commands[1][2] == str(tmp_path)


def test_default_mode_is_debug(monkeypatch):
    commands = []
    monkeypatch.setattr(common.subprocess, "run", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(sys, "argv", ["build.py", "--platform", "host", "--target", "afk_host"])

    build.main()

    assert commands[0][4] == str(common.REPO_ROOT / "build_debug" / "host")
    assert "-DCMAKE_BUILD_TYPE=Debug" in commands[0]
