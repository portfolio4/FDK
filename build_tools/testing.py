"""Simulation output path validation shared by pytest and test.py."""

from pathlib import Path


def simulation_root(path: Path) -> Path:
    path = path.resolve()
    if any(character.isspace() for character in str(path)):
        raise ValueError("Verilator's Make build requires --sim-build-root without whitespace")
    return path
