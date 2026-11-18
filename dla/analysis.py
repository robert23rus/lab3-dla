"""Geometry of finite DLA clusters and an independent random-walk check.

Regression diagnostics describe a finite range of scales. Correlated radii
inside a single cluster are not treated as independent statistical trials.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def _positions(value: np.ndarray) -> np.ndarray:
    points = np.asarray(value, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not len(points):
        raise ValueError("positions must have nonempty shape (N, 2)")
    if not np.isfinite(points).all():
        raise ValueError("positions must be finite")
    return points


def growth_curve(positions: np.ndarray, samples: int = 90) -> dict[str, Any]:
    """Exact prefix radii of gyration, sampled without rerunning the model."""
    points = _positions(positions)
    n = np.arange(1, len(points) + 1, dtype=np.float64)
    center = np.cumsum(points, axis=0) / n[:, None]
    mean_square = np.cumsum(np.sum(points * points, axis=1)) / n
    rg = np.sqrt(np.maximum(0, mean_square - np.sum(center * center, axis=1)))
    counts = np.unique(np.rint(np.geomspace(1, len(points), max(2, samples))).astype(int))
    return {"N": counts.tolist(), "rg": rg[counts - 1].tolist()}


def mass_radius_dimension(positions: np.ndarray) -> dict[str, Any]:
    """Fit log M(r) = D_eff log r + b about the FINAL center of mass.

    Fixed rule: 32 geometric radii from max(4, .12 R) to .60 R, where R
    is the greatest distance from the final center of mass. No search for
    a visually attractive straight segment is performed. The returned R^2
    is descriptive, not proof of a fractal scaling limit or a confidence band.
    """
    points = _positions(positions)
    distances = np.sort(np.linalg.norm(points - points.mean(axis=0), axis=1))
    outer = float(distances[-1])
    lower, upper = max(4.0, 0.12 * outer), 0.60 * outer
    empty = {"method": "mass_radius", "dimension": None, "r_squared": None,
             "r_min": lower, "r_max": upper, "radii": [], "mass": [], "fit_mass": []}
    if upper <= lower or len(points) < 50:
        return empty
    radii = np.geomspace(lower, upper, 32)
    masses = np.searchsorted(distances, radii, side="right")
    keep = masses >= 10
    radii, masses = radii[keep], masses[keep]
    if len(radii) < 8 or len(np.unique(masses)) < 5:
        return empty
    x, y = np.log(radii), np.log(masses)
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    sst = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - float(np.sum((y - predicted) ** 2)) / sst if sst else None
    return {"method": "mass_radius", "dimension": float(slope), "r_squared": r_squared,
            "r_min": float(radii[0]), "r_max": float(radii[-1]),
            "radii": radii.tolist(), "mass": masses.tolist(),
            "fit_mass": np.exp(predicted).tolist()}


def cluster_metrics(positions: np.ndarray) -> dict[str, Any]:
    points = _positions(positions)
    center = points.mean(axis=0)
    rg = float(np.sqrt(np.mean(np.sum((points - center) ** 2, axis=1))))
    rmax = float(np.linalg.norm(points, axis=1).max())
    fit = mass_radius_dimension(points)
    return {"N": len(points), "center_of_mass": center.tolist(), "rg": rg,
            "rmax": rmax, "disk_occupancy": len(points) / (math.pi * rmax**2) if rmax else None,
            "dimension": fit["dimension"], "dimension_fit": fit,
            "growth": growth_curve(points)}


def validate_random_walk(*, trials: int = 20000, steps: int = 400,
                         seed: int = 2026) -> dict[str, Any]:
    """Independent ensemble: four equiprobable unit steps, no aggregation.

    Exact moments: E[r²]=k and Var(r²)=k(k-1). A four-standard-error
    tolerance is a predeclared stochastic smoke check, not a theorem.
    """
    for name, value, minimum in [("trials", trials, 2), ("steps", steps, 1)]:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")
    if isinstance(seed, (bool, np.bool_)) or not isinstance(seed, (int, np.integer)) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    generator = np.random.default_rng(seed)
    xy = np.zeros((trials, 2), dtype=np.int64)
    checkpoints = set(np.rint(np.geomspace(1, steps, min(45, steps))).astype(int))
    records = []
    for step in range(1, steps + 1):
        direction = generator.integers(0, 4, size=trials, dtype=np.int8)
        xy[:, 0] += (direction == 0).astype(np.int8) - (direction == 1).astype(np.int8)
        xy[:, 1] += (direction == 2).astype(np.int8) - (direction == 3).astype(np.int8)
        if step in checkpoints:
            r2 = np.sum(xy * xy, axis=1)
            measured = float(r2.mean())
            error = float(r2.std(ddof=1) / np.sqrt(trials))
            z = (measured - step) / error if error else 0.0
            records.append({"steps": step, "expected_msd": float(step), "measured_msd": measured,
                            "standard_error": error, "expected_standard_error": math.sqrt(step * (step - 1) / trials),
                            "z_score": z})
    final = records[-1]
    return {**final, "trials": int(trials), "seed": int(seed), "step_length": 1,
            "diffusion_coefficient": 0.25, "mean_position": xy.mean(axis=0).tolist(),
            "relative_error": abs(final["measured_msd"] / steps - 1),
            "tolerance_standard_errors": 4.0, "passed": abs(final["z_score"]) <= 4,
            "curve": records}


def ensemble_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("An ensemble must contain at least one run")
    result: dict[str, Any] = {"replicates": len(rows), "seeds": [int(r["seed"]) for r in rows],
                              "N": int(rows[0]["N"]), "p": float(rows[0]["p"])}
    for source, destination in [("rg", "rg"), ("dimension", "dimension"),
                                ("steps", "steps"), ("elapsed_seconds", "seconds")]:
        values = np.asarray([r[source] for r in rows if r[source] is not None], dtype=float)
        result[destination + "_mean"] = float(values.mean()) if len(values) else None
        result[destination + "_std"] = float(values.std(ddof=1)) if len(values) > 1 else None
    return result
