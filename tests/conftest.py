"""Output locations for the supported pytest suites."""

from pathlib import Path

import pytest

import build_tools.common
import build_tools.testing


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("fdk")
    group.addoption("--mode", choices=build_tools.common.BUILD_MODES)
    group.addoption("--host-build-dir", type=Path)
    group.addoption("--sim-build-root", type=Path)


@pytest.fixture(scope="session")
def host_build_dir(pytestconfig: pytest.Config) -> Path:
    mode = pytestconfig.getoption("--mode")
    build_dir = (pytestconfig.getoption("--host-build-dir") or build_tools.common.host_build_directory(mode or "debug")).resolve()
    if mode is not None:
        build_tools.common.configure_host(build_dir, mode=mode)
    return build_dir


@pytest.fixture
def sim_build_dir(request: pytest.FixtureRequest, pytestconfig: pytest.Config) -> Path:
    suite = request.path.parent.name
    mode = pytestconfig.getoption("--mode") or "debug"
    root = pytestconfig.getoption("--sim-build-root") or build_tools.common.build_root(mode) / "sim"
    return build_tools.testing.simulation_root(root) / suite
