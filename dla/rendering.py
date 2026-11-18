"""Reproducible, dark-theme illustrations of actual DLA attachment histories.

Rendering never changes particle coordinates or invents branches.  The diffuse
halo is an optical effect, and every animation frame is a prefix of the supplied
attachment sequence.  The camera and colour scale stay fixed during a movie.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Sequence
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


_STOPS = np.array(
    [
        [86, 244, 233],
        [54, 167, 255],
        [111, 110, 255],
        [203, 97, 238],
        [249, 138, 146],
        [255, 207, 107],
    ],
    dtype=np.float64,
)
_INK = (226, 235, 249)
_MUTED = (122, 146, 173)
_FAINT = (54, 75, 99)


def _positions(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 2 or array.shape[1] != 2 or not len(array):
        raise ValueError("positions must be a nonempty array with shape (N, 2)")
    if not np.issubdtype(array.dtype, np.number):
        raise ValueError("positions must contain finite integer coordinates")
    if not np.isfinite(array).all() or not np.equal(array, np.rint(array)).all():
        raise ValueError("positions must contain finite integer coordinates")
    return np.asarray(array, dtype=np.float64)


def _validate_size(width: int, height: int, *, comparison: bool = False) -> None:
    minimum = (640, 360) if comparison else (320, 320)
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width < minimum[0]
        or height < minimum[1]
    ):
        raise ValueError(f"image size must be at least {minimum[0]} x {minimum[1]}")


def _probability(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= 1:
        raise ValueError("probability must be finite and belong to (0, 1]")
    return float(value)


@lru_cache(maxsize=32)
def _font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Use installed fonts; no user-specific absolute path is embedded."""
    if mono:
        names = ["DejaVuSansMono.ttf", "consola.ttf", "LiberationMono-Regular.ttf"]
    elif bold:
        names = ["DejaVuSans-Bold.ttf", "segoeuib.ttf", "arialbd.ttf"]
    else:
        names = ["DejaVuSans.ttf", "segoeui.ttf", "arial.ttf"]
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in names:
        for candidate in (name, str(windows_fonts / name)):
            try:
                return ImageFont.truetype(candidate, max(size, 8))
            except OSError:
                pass
    return ImageFont.load_default(size=max(size, 8))


def _colours(count: int, end_fraction: float = 1.0) -> np.ndarray:
    if count == 1:
        return _STOPS[:1].copy()
    t = np.linspace(0, (len(_STOPS) - 1) * end_fraction, count)
    lower = np.minimum(t.astype(int), len(_STOPS) - 2)
    f = (t - lower)[:, None]
    return _STOPS[lower] * (1 - f) + _STOPS[lower + 1] * f


def _background(width: int, height: int) -> Image.Image:
    y, x = np.mgrid[0:height, 0:width]
    radius = np.sqrt(((x / width - 0.5) / 0.65) ** 2 + ((y / height - 0.47) / 0.7) ** 2)
    glow = np.maximum(0, 1 - radius) ** 2
    arr = np.empty((height, width, 3), dtype=np.uint8)
    for k, (base, amplitude) in enumerate(((3, 5), (7, 9), (16, 15))):
        arr[:, :, k] = np.asarray(base + amplitude * glow, dtype=np.uint8)
    return Image.fromarray(arr)


def _camera(points: np.ndarray, box: tuple[int, int, int, int], extent: float | None = None) -> tuple[np.ndarray, float]:
    left, top, right, bottom = box
    half_range = max(float(np.abs(points).max()), 6.0) if extent is None else extent
    scale = min(right - left, bottom - top) / (2 * half_range * 1.12)
    pixels = np.empty_like(points, dtype=np.float64)
    pixels[:, 0] = (left + right) / 2 + points[:, 0] * scale
    pixels[:, 1] = (top + bottom) / 2 - points[:, 1] * scale
    return pixels, scale


def _draw_particles(
    canvas: Image.Image,
    pixels: np.ndarray,
    colours: np.ndarray,
    count: int,
    *,
    scale: float,
) -> None:
    """Rasterize markers at occupied lattice sites, then add an optical halo."""
    width, height = canvas.size
    core = Image.new("RGB", canvas.size)
    draw = ImageDraw.Draw(core)
    # The minimum optical marker radius keeps small-scale branches readable.
    radius = max(0.8, min(scale * 0.51, 2.1))
    for (x, y), colour in zip(pixels[:count], colours[:count]):
        rgb = tuple(int(v) for v in colour)
        if radius < 0.8:
            draw.point((round(x), round(y)), fill=rgb)
        else:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=rgb)
    fine = core.filter(ImageFilter.GaussianBlur(1.25))
    broad = core.filter(ImageFilter.GaussianBlur(4.2))
    base = np.asarray(canvas, dtype=np.float32)
    # Additive rendering preserves dark gaps; no geometry is inferred or filled.
    result = base + np.asarray(core, dtype=np.float32) * 0.88
    result += np.asarray(fine, dtype=np.float32) * 0.38
    result += np.asarray(broad, dtype=np.float32) * 0.18
    canvas.paste(Image.fromarray(np.clip(result, 0, 255).astype(np.uint8)))
    # One explicit seed marker is UI, not an extra simulated particle.
    sx, sy = pixels[0]
    mark = ImageDraw.Draw(canvas)
    if 0 <= sx < width and 0 <= sy < height:
        mark.ellipse((sx - 1.4, sy - 1.4, sx + 1.4, sy + 1.4), fill=(248, 252, 255))


def _gradient(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], end_fraction: float = 1.0) -> None:
    left, top, right, bottom = box
    gradient = _colours(max(2, right - left), end_fraction)
    for j, colour in enumerate(gradient):
        draw.line((left + j, top, left + j, bottom), fill=tuple(int(c) for c in colour))


class _Scene:
    def __init__(self, points: np.ndarray, width: int, height: int, probability: float, title: str):
        self.points = points
        self.width, self.height = width, height
        self.p = probability
        self.title = title
        self.factor = min(width / 1200, height / 900)
        self.margin = max(18, round(width * 0.044))
        self.header = max(73, round(height * 0.135))
        self.footer = max(72, round(height * 0.125))
        self.box = (self.margin, self.header, width - self.margin, height - self.footer)
        self.pixels, self.scale = _camera(points, self.box)
        self.colours = _colours(len(points))
        self.base = _background(width, height)
        draw = ImageDraw.Draw(self.base)
        # Thin frame corner marks keep the field visually quiet.
        l, t, r, b = self.box
        corner = max(10, round(18 * self.factor))
        for x, y, dx, dy in ((l, t, 1, 1), (r, t, -1, 1), (l, b, 1, -1), (r, b, -1, -1)):
            draw.line((x, y, x + dx * corner, y), fill=(31, 50, 71))
            draw.line((x, y, x, y + dy * corner), fill=(31, 50, 71))

    def frame(self, count: int) -> Image.Image:
        canvas = self.base.copy()
        _draw_particles(canvas, self.pixels, self.colours, count, scale=self.scale)
        draw = ImageDraw.Draw(canvas)
        f = self.factor
        m, w, h = self.margin, self.width, self.height
        title_size = max(17, round(26 * f))
        small = max(9, round(12 * f))
        tiny = max(8, round(10 * f))
        draw.text((m, max(14, round(27 * f))), "DLA", fill=_INK, font=_font(max(31, round(49 * f)), bold=True))
        title_x = m + max(82, round(127 * f))
        draw.text((title_x, max(19, round(34 * f))), self.title, fill=_INK, font=_font(title_size, bold=True))
        draw.text((title_x, max(42, round(68 * f))), "RANDOM WALKS  /  EMERGENT STRUCTURE", fill=_MUTED, font=_font(tiny, mono=True))
        # At narrow test sizes, move the probability to the footer.
        if w >= 680:
            p_text = f"p = {self.p:g}"
            draw.text((w - m, max(25, round(40 * f))), p_text, fill=(255, 207, 107), font=_font(max(13, round(19 * f)), mono=True), anchor="ra")
        bottom_y = h - self.footer + max(17, round(23 * f))
        draw.text((m, bottom_y), f"{count:,}".replace(",", " "), fill=_INK, font=_font(max(19, round(29 * f)), bold=True))
        label_x = m + max(78, round(139 * f))
        draw.text((label_x, bottom_y + max(5, round(10 * f))), "ATTACHED PARTICLES", fill=_MUTED, font=_font(tiny, mono=True))
        if w < 680:
            draw.text((w - m, bottom_y + 6), f"p={self.p:g}", fill=(255, 207, 107), font=_font(small, mono=True), anchor="ra")
        else:
            draw.text((w - m, bottom_y + max(8, round(12 * f))), "COLOUR = ATTACHMENT ORDER", fill=_MUTED, font=_font(tiny, mono=True), anchor="ra")
        bar_y = h - max(20, round(31 * f))
        bar_x1, bar_x2 = m, w - m
        draw.line((bar_x1, bar_y, bar_x2, bar_y), fill=(24, 37, 56), width=max(2, round(3 * f)))
        end = bar_x1 + max(1, round((bar_x2 - bar_x1) * count / len(self.points)))
        _gradient(draw, (bar_x1, bar_y - 1, end, bar_y + max(1, round(2 * f))), count / len(self.points))
        return canvas


def _counts(particles: int, frames: int) -> np.ndarray:
    if isinstance(frames, bool) or not isinstance(frames, int) or not 2 <= frames <= 200:
        raise ValueError("frames must be an integer between 2 and 200")
    return np.unique(np.rint(np.linspace(1, particles, min(frames, particles))).astype(int))


def _durations(count: int, fps: int) -> list[int]:
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 50:
        raise ValueError("fps must be an integer between 1 and 50")
    # GIF stores centiseconds; alternating intervals preserve the requested rate.
    boundaries = np.rint(np.arange(count + 1) * 100 / fps).astype(int)
    return (np.diff(boundaries) * 10).tolist()


def _write_gif(images: list[Image.Image], path: Path, fps: int) -> Path:
    if not images:
        raise ValueError("no frames to encode")
    durations = _durations(len(images), fps)
    # The final state includes every branch colour and all UI inks.
    palette = images[-1].quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    encoded = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in images]
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=encoded[1:],
        duration=durations,
        loop=0,
        optimize=False,
        disposal=1,
    )
    return path


def render_cluster(
    positions: np.ndarray,
    path: str | Path,
    *,
    probability: float = 1.0,
    title: str = "DIFFUSION / AGGREGATION",
    width: int = 1200,
    height: int = 900,
) -> Path:
    """Save a still image; the colour of a particle encodes its arrival index."""
    points = _positions(positions)
    _validate_size(width, height)
    p = _probability(probability)
    scene = _Scene(points, width, height, p, str(title))
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    scene.frame(len(points)).save(output)
    return output


def render_growth(
    positions: np.ndarray,
    path: str | Path,
    *,
    probability: float = 1.0,
    fps: int = 20,
    frames: int = 140,
    width: int = 960,
    height: int = 720,
) -> Path:
    """Save real growth prefixes with a fixed camera and a global GIF palette."""
    points = _positions(positions)
    _validate_size(width, height)
    p = _probability(probability)
    counts = _counts(len(points), frames)
    _durations(len(counts), fps)  # Validate before expensive rendering.
    scene = _Scene(points, width, height, p, "DIFFUSION / AGGREGATION")
    return _write_gif([scene.frame(int(n)) for n in counts], Path(path), fps)


def _comparison_frame(
    items: list[tuple[float, np.ndarray]],
    pixels: list[np.ndarray],
    scale: float,
    colours: np.ndarray,
    count: int,
    width: int,
    height: int,
) -> Image.Image:
    canvas = _background(width, height)
    draw = ImageDraw.Draw(canvas)
    margin = round(width * 0.035)
    draw.text((margin, 24), "SAME RULES. DIFFERENT CONTACT PROBABILITY.", fill=_INK, font=_font(max(13, round(width * 0.019)), bold=True))
    draw.text((margin, 58), "DLA  /  SEPARATE REALIZATIONS  /  EQUAL ATTACHED MASS", fill=_MUTED, font=_font(max(9, round(width * 0.009)), mono=True))
    for k, ((p, _), coords) in enumerate(zip(items, pixels)):
        _draw_particles(canvas, coords, colours, count, scale=scale)
        draw = ImageDraw.Draw(canvas)
        center = (k + 0.5) * width / len(items)
        draw.text((center, 99), f"p = {p:g}", anchor="ma", fill=(255, 207, 107), font=_font(max(14, round(width * 0.017)), mono=True))
        if k:
            x = round(k * width / len(items))
            draw.line((x, 122, x, height - 74), fill=(23, 38, 57))
    draw.text((margin, height - 54), f"N = {count:,}".replace(",", " "), fill=_INK, font=_font(max(13, round(width * 0.015)), bold=True))
    draw.text((width - margin, height - 48), "SHARED SPATIAL SCALE  /  COLOUR = ARRIVAL ORDER", anchor="ra", fill=_MUTED, font=_font(max(8, round(width * 0.008)), mono=True))
    bar_y = height - 20
    end = margin + max(1, round((width - 2 * margin) * count / len(items[0][1])))
    draw.line((margin, bar_y, width - margin, bar_y), fill=(24, 37, 56), width=3)
    _gradient(draw, (margin, bar_y - 1, end, bar_y + 1), count / len(items[0][1]))
    return canvas


def render_comparison(
    samples: Sequence[tuple[float, np.ndarray]],
    path: str | Path,
    *,
    fps: int = 20,
    frames: int = 110,
    width: int = 1280,
    height: int = 600,
) -> Path:
    """Render two/three equal-mass runs using one common lattice-unit scale.

    A ``.gif`` destination produces growth; other image suffixes save the final
    state.  Different runs are not claimed to be paired physical trajectories.
    """
    _validate_size(width, height, comparison=True)
    if not 2 <= len(samples) <= 3:
        raise ValueError("comparison requires two or three samples")
    items = [(_probability(p), _positions(positions)) for p, positions in samples]
    lengths = {len(points) for _, points in items}
    if len(lengths) != 1:
        raise ValueError("comparison samples must contain the same particle count")
    particles = lengths.pop()
    extent = max(6.0, *(float(np.abs(points).max()) for _, points in items))
    column = width / len(items)
    cameras = []
    scales = []
    for k, (_, points) in enumerate(items):
        box = (round(k * column + 15), 140, round((k + 1) * column - 15), height - 77)
        px, scale = _camera(points, box, extent)
        cameras.append(px)
        scales.append(scale)
    colours = _colours(particles)
    output = Path(path)
    if output.suffix.lower() == ".gif":
        counts = _counts(particles, frames)
        _durations(len(counts), fps)
        images = [_comparison_frame(items, cameras, min(scales), colours, int(n), width, height) for n in counts]
        return _write_gif(images, output, fps)
    output.parent.mkdir(parents=True, exist_ok=True)
    _comparison_frame(items, cameras, min(scales), colours, particles, width, height).save(output)
    return output
