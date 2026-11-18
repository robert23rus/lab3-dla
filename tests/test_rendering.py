"""Check that exported animations preserve the supplied attachment history."""

import numpy as np
from PIL import Image, ImageChops
import pytest

from dla.rendering import _Scene, _counts, _durations, render_cluster, render_comparison, render_growth


@pytest.fixture
def small_cluster():
    # One connected prefix at every index; no synthetic data enter project media.
    return np.array([(0, 0), (1, 0), (2, 0), (2, 1), (0, -1), (-1, -1), (-2, -1), (-2, -2)], dtype=np.int32)


def test_static_render_does_not_modify_positions(tmp_path, small_cluster):
    before = small_cluster.copy()
    path = render_cluster(small_cluster, tmp_path / "nested" / "cluster.png", width=480, height=480)
    assert path.is_file()
    with Image.open(path) as im:
        assert im.size == (480, 480)
        assert im.mode == "RGB"
    np.testing.assert_array_equal(small_cluster, before)


def test_gif_contains_first_and_final_prefix_with_fixed_camera(tmp_path, small_cluster):
    path = render_growth(small_cluster, tmp_path / "growth.gif", width=400, height=400, fps=24, frames=5)
    scene = _Scene(small_cluster.astype(float), 400, 400, 1.0, "DIFFUSION / AGGREGATION")
    with Image.open(path) as gif:
        assert gif.n_frames == 5
        assert gif.info["loop"] == 0
        frames = []
        durations = []
        for k in range(gif.n_frames):
            gif.seek(k)
            frames.append(gif.convert("RGB").copy())
            durations.append(gif.info["duration"])
    assert sum(durations) == round(5 / 24 * 100) * 10
    assert ImageChops.difference(frames[0], frames[-1]).getbbox() is not None
    # Match the actual first and last scientific states, allowing palette error.
    for actual, count in ((frames[0], 1), (frames[-1], len(small_cluster))):
        expected = np.asarray(scene.frame(count), dtype=float)
        error = np.abs(np.asarray(actual, dtype=float) - expected).mean()
        assert error < 4.0


def test_frame_prefix_selection_and_centisecond_timing():
    counts = _counts(1000, 110)
    assert counts[0] == 1 and counts[-1] == 1000
    assert np.all(np.diff(counts) > 0)
    durations = _durations(140, 24)
    assert set(durations) == {40, 50}
    assert abs(sum(durations) - 140 / 24 * 1000) <= 5


def test_comparison_has_equal_mass_and_exports(tmp_path, small_cluster):
    second = small_cluster[:, ::-1].copy()
    result = render_comparison([(1.0, small_cluster), (0.2, second)], tmp_path / "compare.png", width=800, height=440)
    with Image.open(result) as image:
        assert image.size == (800, 440)
    with pytest.raises(ValueError, match="same particle count"):
        render_comparison([(1, small_cluster), (0.2, second[:-1])], tmp_path / "bad.png")


@pytest.mark.parametrize("bad", [np.empty((0, 2)), [[1, 2, 3]], [[0.1, 0]], [[float('nan'), 0]]])
def test_invalid_positions_are_rejected(tmp_path, bad):
    with pytest.raises(ValueError, match="positions"):
        render_cluster(bad, tmp_path / "bad.png")


def test_invalid_movie_options_are_rejected_before_encoding(tmp_path, small_cluster):
    with pytest.raises(ValueError, match="fps"):
        render_growth(small_cluster, tmp_path / "bad.gif", fps=0)
    with pytest.raises(ValueError, match="probability"):
        render_growth(small_cluster, tmp_path / "bad.gif", probability=0)
