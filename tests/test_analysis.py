import numpy as np
import pytest

from dla.analysis import (cluster_metrics, ensemble_summary, growth_curve,
                          mass_radius_dimension, validate_random_walk)


def test_prefix_radius_matches_direct_calculation():
    p = np.array([[0, 0], [1, 0], [1, 1], [2, 1], [2, 2]])
    curve = growth_curve(p, samples=100)
    for n, rg in zip(curve['N'], curve['rg']):
        q = p[:n] - p[:n].mean(axis=0)
        assert rg == pytest.approx(np.sqrt(np.mean(np.sum(q*q, axis=1))))


def test_line_and_filled_square_have_different_dimensions():
    line = np.column_stack([np.arange(-500, 501), np.zeros(1001)])
    x, y = np.meshgrid(np.arange(-60, 61), np.arange(-60, 61))
    square = np.column_stack([x.ravel(), y.ravel()])
    assert mass_radius_dimension(line)['dimension'] == pytest.approx(1, abs=.03)
    assert mass_radius_dimension(square)['dimension'] == pytest.approx(2, abs=.03)


def test_too_small_cluster_does_not_claim_dimension():
    assert cluster_metrics(np.array([[0, 0], [1, 0]]))['dimension'] is None


def test_geometry_translation_invariance():
    p = np.random.default_rng(1).normal(size=(1000, 2))*20
    a, b = cluster_metrics(p), cluster_metrics(p + 50)
    assert a['rg'] == pytest.approx(b['rg'])
    assert a['dimension'] == pytest.approx(b['dimension'])


def test_first_random_walk_step_has_exact_unit_square_displacement():
    result = validate_random_walk(trials=500, steps=1, seed=3)
    assert result['measured_msd'] == 1
    assert result['standard_error'] == 0
    assert result['passed']


def test_walk_moments_with_many_independent_trials():
    result = validate_random_walk(trials=15000, steps=100, seed=9)
    assert result['passed']
    assert result['standard_error'] == pytest.approx(result['expected_standard_error'], rel=.06)


def test_ensemble_uses_sample_standard_deviation():
    rows = [dict(seed=s, N=10, p=1, rg=v, dimension=None, steps=v, elapsed_seconds=v)
            for s, v in [(1, 2), (2, 4)]]
    summary = ensemble_summary(rows)
    assert summary['rg_mean'] == 3
    assert summary['rg_std'] == pytest.approx(np.sqrt(2))
    assert summary['dimension_mean'] is None


@pytest.mark.parametrize('bad', [np.array([]), np.ones((2, 3)), np.array([[0, np.nan]])])
def test_invalid_geometry_is_rejected(bad):
    with pytest.raises(ValueError):
        cluster_metrics(bad)
