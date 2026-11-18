"""Square-lattice diffusion-limited aggregation with an optional Numba backend.

Walkers make genuine nearest-neighbour random steps: there are no radial forces,
long-distance jumps or changes to the sticking law for rendering purposes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from numbers import Integral, Real
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

try:
    from numba import njit
except ImportError:  # A supported Python/NumPy combination may lack Numba.
    njit = None

BACKEND = "numba" if njit is not None else "python"
FORMAT_VERSION = 1


def _integer(name: str, value: Any, lower: int, upper: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if result < lower or result > upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return result


def _real(name: str, value: Any, lower: float, upper: float) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    result = float(value)
    if not np.isfinite(result) or not lower <= result <= upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return result


@dataclass(frozen=True)
class DLAConfig:
    """Reproducible model parameters; particle count includes the central seed.

    ``grid_size`` bounds the cluster, not the random walks. Occupancy outside
    the grid is zero. A walker is launched on the rounded circle of radius
    ``launch_factor * max(R_cluster, 5) + 5``; after crossing ``kill_factor``
    times this radius it is replaced by a newly launched walker. These finite
    launch/kill boundaries are part of the numerical model and should be varied
    in a sensitivity study. ``max_steps`` counts attempted lattice moves and
    causes an explicit failure instead of returning a biased partial aggregate.
    """

    particles: int = 3000
    sticking_probability: float = 1.0
    seed: int = 42
    grid_size: int = 1025
    launch_factor: float = 1.6
    kill_factor: float = 3.0
    max_steps: int = 500_000_000

    def __post_init__(self) -> None:
        integer_fields = (
            ("particles", 1, np.iinfo(np.int32).max),
            ("seed", 0, 2**63 - 1),
            ("grid_size", 17, 32767),
            ("max_steps", 1, np.iinfo(np.int64).max),
        )
        for name, lower, upper in integer_fields:
            object.__setattr__(self, name, _integer(name, getattr(self, name), lower, upper))
        if self.grid_size % 2 != 1:
            raise ValueError("grid_size must be odd so the seed has a central cell")
        if self.particles > self.grid_size**2:
            raise ValueError("particles cannot exceed the number of lattice cells")
        object.__setattr__(self, "sticking_probability", _real(
            "sticking_probability", self.sticking_probability,
            np.nextafter(0.0, 1.0), 1.0,
        ))
        object.__setattr__(self, "launch_factor", _real(
            "launch_factor", self.launch_factor, 1.01, 100.0,
        ))
        # The minimum gap exceeds circle-rounding error even for a tiny seed.
        object.__setattr__(self, "kill_factor", _real(
            "kill_factor", self.kill_factor, 1.1, 100.0,
        ))


@dataclass
class DLAResult:
    positions: np.ndarray
    config: DLAConfig
    stats: dict[str, Any]


def _grow_python(
    particles: int,
    probability: float,
    grid_size: int,
    launch_factor: float,
    kill_factor: float,
    max_steps: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, int, int, int, int, int, int]:
    positions = np.zeros((particles, 2), dtype=np.int32)
    occupied = np.zeros((grid_size, grid_size), dtype=np.uint8)
    adjacent = np.zeros((grid_size, grid_size), dtype=np.uint8)
    centre = grid_size // 2
    occupied[centre, centre] = 1
    adjacent[centre - 1, centre] = 1
    adjacent[centre + 1, centre] = 1
    adjacent[centre, centre - 1] = 1
    adjacent[centre, centre + 1] = 1
    count = 1
    radius = 0.0
    steps = 0
    launches = 0
    escapes = 0
    contacts = 0
    direction_bits = 0
    directions_remaining = 0

    while count < particles:
        launch_radius = launch_factor * max(radius, 5.0) + 5.0
        kill_radius_squared = (kill_factor * launch_radius)**2
        angle = rng.random() * (2.0 * np.pi)
        x = int(np.rint(launch_radius * np.cos(angle)))
        y = int(np.rint(launch_radius * np.sin(angle)))
        launches += 1

        while True:
            if x*x + y*y > kill_radius_squared:
                escapes += 1
                break

            ix, iy = x + centre, y + centre
            inside = 0 <= ix < grid_size and 0 <= iy < grid_size
            if inside and adjacent[ix, iy] != 0:
                contacts += 1
                # p=1 uses no unnecessary uniform deviate.
                if probability == 1.0 or rng.random() < probability:
                    if ix <= 0 or ix >= grid_size - 1 or iy <= 0 or iy >= grid_size - 1:
                        return positions, count, steps, launches, escapes, contacts, 2
                    positions[count, 0] = x
                    positions[count, 1] = y
                    count += 1
                    occupied[ix, iy] = 1
                    adjacent[ix - 1, iy] = 1
                    adjacent[ix + 1, iy] = 1
                    adjacent[ix, iy - 1] = 1
                    adjacent[ix, iy + 1] = 1
                    radius = max(radius, np.sqrt(float(x*x + y*y)))
                    break

            if steps >= max_steps:
                return positions, count, steps, launches, escapes, contacts, 1
            # Sixteen disjoint pairs of unbiased bits are sixteen independent
            # uniform directions. This buffers RNG calls without skipping any
            # lattice moves or modifying the random-walk transition kernel.
            if directions_remaining == 0:
                direction_bits = int(rng.integers(0, 4294967296))
                directions_remaining = 16
            direction = direction_bits & 3
            direction_bits >>= 2
            directions_remaining -= 1
            nx, ny = x, y
            if direction == 0:
                nx += 1
            elif direction == 1:
                nx -= 1
            elif direction == 2:
                ny += 1
            else:
                ny -= 1
            nix, niy = nx + centre, ny + centre
            if not (0 <= nix < grid_size and 0 <= niy < grid_size):
                x, y = nx, ny
            elif occupied[nix, niy] == 0:
                x, y = nx, ny
            # An attempted move into an occupied cell is rejected. At the next
            # iteration a walker still adjacent to the cluster can stick again.
            steps += 1

    return positions, count, steps, launches, escapes, contacts, 0


_grow = njit(cache=True)(_grow_python) if njit is not None else _grow_python


def warm_up() -> None:
    """Compile the accelerated kernel before measuring simulation wall time."""
    if njit is not None:
        _grow(1, 1.0, 17, 1.6, 3.0, 100, np.random.default_rng(0))


def simulate(config: DLAConfig | None = None) -> DLAResult:
    """Grow an aggregate; all returned positions are genuine sticking events."""
    if config is None:
        config = DLAConfig()
    if not isinstance(config, DLAConfig):
        raise TypeError("config must be a DLAConfig")
    warm_up()
    rng = np.random.default_rng(config.seed)
    start = perf_counter()
    positions, count, steps, launches, escapes, contacts, status = _grow(
        config.particles, config.sticking_probability, config.grid_size,
        config.launch_factor, config.kill_factor, config.max_steps, rng,
    )
    elapsed = perf_counter() - start
    if status == 1:
        raise RuntimeError(
            f"Step budget {config.max_steps} exhausted after {count} of "
            f"{config.particles} particles. Increase max_steps or reduce particles."
        )
    if status == 2:
        raise RuntimeError(
            f"Cluster reached the grid boundary after {count} particles. "
            "Increase grid_size; boundary clipping is not allowed."
        )
    return DLAResult(positions, config, {
        "steps": int(steps),
        "launches": int(launches),
        "escapes": int(escapes),
        "contact_attempts": int(contacts),
        "elapsed_seconds": float(elapsed),
        "backend": BACKEND,
        "rng": "numpy.random.Generator(PCG64)",
        "time_measurement": "perf_counter; kernel only; JIT excluded",
    })


def save_result(result: DLAResult, path: str | Path) -> Path:
    """Save coordinates and JSON metadata; the file never requires pickle."""
    target = Path(path)
    if target.suffix.lower() != ".npz":
        target = target.with_suffix(".npz")
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "format_version": FORMAT_VERSION,
        "config": asdict(result.config),
        "stats": result.stats,
    }
    np.savez_compressed(
        target, positions=np.asarray(result.positions, dtype=np.int32),
        metadata_json=np.array(json.dumps(metadata, ensure_ascii=False)),
    )
    return target


def load_result(path: str | Path) -> DLAResult:
    """Read an archive and reject malformed coordinates/configuration."""
    with np.load(Path(path), allow_pickle=False) as archive:
        positions = archive["positions"].copy()
        metadata = json.loads(str(archive["metadata_json"].item()))
    if metadata.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported DLA result format")
    config = DLAConfig(**metadata["config"])
    if positions.shape != (config.particles, 2) or positions.dtype != np.dtype(np.int32):
        raise ValueError("Invalid saved coordinates: expected int32 array (particles, 2)")
    if not np.array_equal(positions[0], [0, 0]):
        raise ValueError("The first particle must be the central seed")
    if np.any(np.abs(positions.astype(np.int64)) >= config.grid_size // 2):
        raise ValueError("Saved cluster coordinates exceed the grid interior")
    if len(np.unique(positions, axis=0)) != config.particles:
        raise ValueError("Saved cluster contains duplicate occupied cells")
    stats = metadata.get("stats")
    if not isinstance(stats, dict):
        raise ValueError("Invalid saved statistics")
    return DLAResult(positions, config, stats)
