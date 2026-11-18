"""Model invariants, stochastic reproducibility and archive safety."""

import json

import numpy as np
import pytest

from dla.model import DLAConfig, load_result, save_result, simulate


def assert_sequential_connectivity(positions):
    occupied = {(0, 0)}
    for x, y in positions[1:]:
        point = (int(x), int(y))
        assert point not in occupied
        assert any((point[0] + dx, point[1] + dy) in occupied
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        occupied.add(point)


@pytest.mark.parametrize("probability", [1.0, 0.5, 0.2])
def test_cluster_is_unique_and_attaches_to_existing_cardinal_neighbour(probability):
    result = simulate(DLAConfig(particles=140, sticking_probability=probability,
                                grid_size=257, seed=108))
    assert result.positions.shape == (140, 2)
    assert result.positions.dtype == np.int32
    np.testing.assert_array_equal(result.positions[0], [0, 0])
    assert_sequential_connectivity(result.positions)
    assert result.stats["launches"] == 139 + result.stats["escapes"]
    assert result.stats["contact_attempts"] >= 139
    assert result.stats["steps"] > 0


def test_same_seed_reproduces_positions_and_work_statistics():
    config = DLAConfig(particles=100, sticking_probability=0.4, seed=47)
    a, b = simulate(config), simulate(config)
    np.testing.assert_array_equal(a.positions, b.positions)
    for name in ("steps", "launches", "escapes", "contact_attempts"):
        assert a.stats[name] == b.stats[name]


def test_different_seed_changes_realisation():
    a = simulate(DLAConfig(particles=100, seed=1))
    b = simulate(DLAConfig(particles=100, seed=2))
    assert not np.array_equal(a.positions, b.positions)


def test_python_and_accelerated_walks_use_the_same_transitions():
    from dla.model import _grow, _grow_python

    args = (35, 0.4, 257, 1.6, 3.0, 2_000_000)
    python_result = _grow_python(*args, np.random.default_rng(101))
    accelerated_result = _grow(*args, np.random.default_rng(101))
    np.testing.assert_array_equal(python_result[0], accelerated_result[0])
    assert python_result[1:] == accelerated_result[1:]


def test_one_particle_is_only_seed_and_performs_no_random_walk():
    result = simulate(DLAConfig(particles=1))
    np.testing.assert_array_equal(result.positions, [[0, 0]])
    assert result.stats["steps"] == result.stats["launches"] == 0


def test_budget_exhaustion_is_explicit_instead_of_saving_partial_cluster():
    with pytest.raises(RuntimeError, match="Step budget"):
        simulate(DLAConfig(particles=50, max_steps=1))


def test_grid_boundary_is_explicit_instead_of_clipping_cluster():
    with pytest.raises(RuntimeError, match="grid boundary"):
        simulate(DLAConfig(particles=150, grid_size=17, seed=42))


@pytest.mark.parametrize("changes", [
    {"particles": 0}, {"particles": True}, {"particles": 12.5},
    {"particles": 300, "grid_size": 17},
    {"grid_size": 16}, {"grid_size": 18},
    {"seed": -1}, {"seed": 2**63}, {"seed": 1.2},
    {"max_steps": 0}, {"max_steps": False},
    {"sticking_probability": 0}, {"sticking_probability": 1.1},
    {"sticking_probability": np.nan}, {"sticking_probability": np.inf},
    {"sticking_probability": "0.5"},
    {"launch_factor": 1.0}, {"kill_factor": 1.0},
])
def test_invalid_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        DLAConfig(**changes)


def test_numpy_scalar_configuration_normalises_for_json():
    config = DLAConfig(particles=np.int64(20), seed=np.int64(5),
                       sticking_probability=np.float64(0.5))
    assert type(config.particles) is int
    assert type(config.sticking_probability) is float


def test_archive_round_trip_without_pickle(tmp_path):
    result = simulate(DLAConfig(particles=75, seed=18))
    path = save_result(result, tmp_path / "nested" / "cluster")
    assert path.suffix == ".npz"
    restored = load_result(path)
    np.testing.assert_array_equal(restored.positions, result.positions)
    assert restored.config == result.config
    assert restored.stats == result.stats
    with np.load(path, allow_pickle=False) as archive:
        assert not archive["metadata_json"].dtype.hasobject


def test_archive_rejects_duplicate_coordinates(tmp_path):
    result = simulate(DLAConfig(particles=15))
    path = save_result(result, tmp_path / "valid.npz")
    with np.load(path, allow_pickle=False) as data:
        positions = data["positions"].copy()
        metadata = data["metadata_json"].copy()
    positions[-1] = positions[1]
    bad = tmp_path / "bad.npz"
    np.savez_compressed(bad, positions=positions, metadata_json=metadata)
    with pytest.raises(ValueError, match="duplicate"):
        load_result(bad)


def test_archive_rejects_unknown_version(tmp_path):
    result = simulate(DLAConfig(particles=3))
    path = save_result(result, tmp_path / "valid.npz")
    with np.load(path, allow_pickle=False) as data:
        positions = data["positions"].copy()
        metadata = json.loads(data["metadata_json"].item())
    metadata["format_version"] = 99
    bad = tmp_path / "bad.npz"
    np.savez_compressed(bad, positions=positions,
                        metadata_json=np.array(json.dumps(metadata)))
    with pytest.raises(ValueError, match="Unsupported"):
        load_result(bad)
