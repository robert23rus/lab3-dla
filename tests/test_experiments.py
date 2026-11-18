from dla import experiments
from dla.model import DLAConfig


def test_matching_cache_reuses_the_measured_run(tmp_path, monkeypatch):
    config = DLAConfig(particles=30, seed=4)
    first, path = experiments.cached_run(config, tmp_path)

    def forbidden(_):
        raise AssertionError('A matching run should be reused')

    monkeypatch.setattr(experiments, 'simulate', forbidden)
    second, other_path = experiments.cached_run(config, tmp_path)
    assert path == other_path
    assert second.stats == first.stats


def test_changed_environment_does_not_inherit_previous_timings(tmp_path, monkeypatch):
    config = DLAConfig(particles=30, seed=7)
    first, _ = experiments.cached_run(config, tmp_path)
    changed = {**experiments.environment(), 'processor': 'a different machine'}
    original = experiments.simulate
    calls = []

    def measured(c):
        calls.append(c)
        return original(c)

    monkeypatch.setattr(experiments, 'environment', lambda: changed)
    monkeypatch.setattr(experiments, 'simulate', measured)
    second, _ = experiments.cached_run(config, tmp_path)
    assert len(calls) == 1
    assert second.stats['run_environment'] == changed
    assert first.stats['run_environment'] != second.stats['run_environment']
    assert (first.positions == second.positions).all()
