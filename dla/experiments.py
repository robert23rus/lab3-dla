"""Repeatable Monte Carlo experiments; raw cluster archives remain available."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
from typing import Any, Callable

from .analysis import cluster_metrics, ensemble_summary, validate_random_walk
from .model import BACKEND, DLAConfig, DLAResult, load_result, save_result, simulate, warm_up
from .plots import plot_boundary, plot_geometry, plot_sticking, plot_validation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_json(value: Any, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return target


def source_hashes() -> dict[str, str]:
    return {str(p.relative_to(PROJECT_ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((PROJECT_ROOT / "dla").glob("*.py"))}


def environment() -> dict[str, Any]:
    versions = {}
    for package in ["numpy", "numba", "matplotlib", "Pillow"]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {"python": sys.version.split()[0], "platform": platform.platform(),
            "machine": platform.machine(), "processor": platform.processor(),
            "backend": BACKEND, "packages": versions}


def cached_run(config: DLAConfig, directory: str | Path) -> tuple[DLAResult, Path]:
    model_hash = hashlib.sha256((PROJECT_ROOT / "dla/model.py").read_bytes()).hexdigest()
    run_environment = environment()
    key = hashlib.sha256(json.dumps({"config": asdict(config), "model": model_hash}, sort_keys=True).encode()).hexdigest()[:20]
    path = Path(directory) / ("cluster_"+key+".npz")
    if path.exists():
        result = load_result(path)
        if (result.config == config and result.stats.get("model_sha256") == model_hash
                and result.stats.get("run_environment") == run_environment):
            return result, path
    result = simulate(config)
    result.stats["model_sha256"] = model_hash
    result.stats["run_environment"] = run_environment
    save_result(result, path)
    return result, path


def _relative(path: Path, directory: Path) -> str:
    return path.relative_to(directory).as_posix()


def run_study(directory: str | Path, *, particles: int = 3000, replicates: int = 6,
              probabilities: tuple[float, ...] = (1.0, .5, .2), seed: int = 100,
              validation_trials: int = 20000, validation_steps: int = 400,
              progress: Callable[[str], None] = print) -> dict[str, Any]:
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 2:
        raise ValueError("At least two independent replicates are required")
    if not probabilities or len(probabilities) > 4 or len(set(probabilities)) != len(probabilities):
        raise ValueError("Choose one to four distinct probabilities")
    for p in probabilities:
        DLAConfig(particles=particles, sticking_probability=p, seed=seed+replicates-1)
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    warm_up()
    seeds = list(range(seed, seed + replicates))
    rows, groups, curves, fits, representatives = [], [], [], [], []
    progress("Random-walk validation...")
    validation = validate_random_walk(trials=validation_trials, steps=validation_steps, seed=2026)
    figures = {"validation": _relative(plot_validation(validation, out / "validation.png"), out)}
    write_json(validation, out / "validation.json")
    for p in probabilities:
        group = []
        for j, s in enumerate(seeds):
            config = DLAConfig(particles=particles, sticking_probability=p, seed=s, max_steps=4_000_000_000)
            progress(f"Sticking p={p:g}, N={particles}, seed={s} ({j+1}/{replicates})")
            result, archive = cached_run(config, out / "runs")
            metrics = cluster_metrics(result.positions)
            row = {"experiment": "sticking", "N": particles, "p": p, "seed": s,
                   "launch_factor": config.launch_factor, "kill_factor": config.kill_factor,
                   "rg": metrics["rg"], "rmax": metrics["rmax"], "dimension": metrics["dimension"],
                   **result.stats, "archive": _relative(archive, out)}
            group.append(row)
            rows.append(row)
            if j == 0:
                curves.append((p, metrics["growth"]))
                fits.append((p, metrics["dimension_fit"]))
                representatives.append({"p": p, "seed": s, "archive": _relative(archive, out), "metrics": metrics})
        groups.append(ensemble_summary(group))
    boundary, boundary_n = [], min(1500, particles)
    for launch, kill in [(1.3, 3.0), (1.6, 3.0), (2.0, 3.0), (1.6, 5.0)]:
        group = []
        for s in seeds:
            config = DLAConfig(particles=boundary_n, sticking_probability=1., seed=s,
                               launch_factor=launch, kill_factor=kill, max_steps=4_000_000_000)
            progress(f"Boundary L={launch:g}, K={kill:g}, N={boundary_n}, seed={s}")
            result, archive = cached_run(config, out / "runs")
            metrics = cluster_metrics(result.positions)
            row = {"experiment": "boundary", "N": boundary_n, "p": 1., "seed": s,
                   "launch_factor": launch, "kill_factor": kill,
                   "rg": metrics["rg"], "rmax": metrics["rmax"], "dimension": metrics["dimension"],
                   **result.stats, "archive": _relative(archive, out)}
            rows.append(row)
            group.append(row)
        boundary.append({**ensemble_summary(group), "launch_factor": launch, "kill_factor": kill})
    figures.update({name: _relative(path, out) for name, path in plot_geometry(curves, fits, out).items()})
    figures["sticking"] = _relative(plot_sticking(groups, out / "sticking.png"), out)
    figures["boundary"] = _relative(plot_boundary(boundary, out / "boundary.png"), out)
    summary = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
               "environment": environment(), "source_sha256": source_hashes(),
               "parameters": {"particles": particles, "replicates": replicates, "seeds": seeds,
                              "probabilities": list(probabilities), "boundary_particles": boundary_n,
                              "launch_factor": 1.6, "kill_factor": 3., "grid_size": 1025,
                              "dimension_method": "mass-radius about final COM; 32 radii from max(4,0.12R) to 0.60R",
                              "dispersion": "sample standard deviation across independent seeds (ddof=1)"},
               "validation": {"random_walk": validation},
               "experiments": {"sticking": groups, "boundary": boundary},
               "representatives": representatives, "figures": figures, "runs": rows}
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (out / "runs.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    write_json(summary, out / "summary.json")
    progress(f"Study complete: {len(rows)} simulations; {out / 'summary.json'}")
    return summary
