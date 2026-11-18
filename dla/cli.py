"""User-facing commands. Expensive computations are separate from rendering."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import sys

import numpy as np

from .analysis import cluster_metrics, validate_random_walk
from .experiments import environment, run_study, source_hashes, write_json
from .model import BACKEND, DLAConfig, load_result, save_result, simulate
from .plots import plot_geometry, plot_validation
from .rendering import render_cluster, render_growth


def _integer(lower: int, upper: int = 2**63-1):
    def parse(value):
        try:
            result = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("нужно целое число") from exc
        if not lower <= result <= upper:
            raise argparse.ArgumentTypeError(f"допустимый диапазон: {lower}…{upper}")
        return result
    return parse


def _p(value):
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("нужно число от 0 до 1, исключая 0") from exc
    if not np.isfinite(number) or not 0 < number <= 1:
        raise argparse.ArgumentTypeError("вероятность должна принадлежать (0, 1]")
    return number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="ЛР №3: диффузионно-ограниченная агрегация (DLA)")
    sub = root.add_subparsers(dest="command", required=True)
    sim = sub.add_parser("simulate", help="вырастить один кластер и сохранить координаты")
    sim.add_argument("--particles", type=_integer(1), default=3000, help="число частиц вместе с зародышем (3000)")
    sim.add_argument("--p", type=_p, default=1., help="вероятность прилипания (1)")
    sim.add_argument("--seed", type=_integer(0), default=42)
    sim.add_argument("--grid-size", type=_integer(17, 32767), default=1025, help="нечётный размер поля кластера")
    sim.add_argument("--launch-factor", type=float, default=1.6)
    sim.add_argument("--kill-factor", type=float, default=3.)
    sim.add_argument("--max-steps", type=_integer(1), default=4_000_000_000,
                     help="защитный лимит попыток шага; при исчерпании явная ошибка")
    sim.add_argument("--out", type=Path, default=Path("results/demo"))
    render = sub.add_parser("render", help="перерисовать сохранённый NPZ без повторного расчёта")
    render.add_argument("--input", type=Path, required=True)
    render.add_argument("--out", type=Path, default=Path("results/render"))
    for target in [sim, render]:
        target.add_argument("--animate", action="store_true", help="сохранить growth.gif")
        target.add_argument("--fps", type=_integer(1, 50), default=20)
        target.add_argument("--frames", type=_integer(2, 200), default=140)
    validate = sub.add_parser("validate", help="проверить свободную диффузию на ансамбле траекторий")
    validate.add_argument("--trials", type=_integer(2), default=20000)
    validate.add_argument("--steps", type=_integer(1), default=400)
    validate.add_argument("--seed", type=_integer(0), default=2026)
    validate.add_argument("--out", type=Path, default=Path("results/validation"))
    study = sub.add_parser("experiments", help="серия по p, независимым seed и границам")
    study.add_argument("--particles", type=_integer(100), default=3000)
    study.add_argument("--replicates", type=_integer(2, 1000), default=6)
    study.add_argument("--probabilities", type=_p, nargs="+", default=[1., .5, .2])
    study.add_argument("--seed", type=_integer(0), default=100, help="первый seed; следующие идут подряд")
    study.add_argument("--out", type=Path, default=Path("results/study"))
    return root


def _outputs(result, out: Path, animate: bool, fps: int, frames: int):
    out.mkdir(parents=True, exist_ok=True)
    metrics = cluster_metrics(result.positions)
    write_json({"config": asdict(result.config), "stats": result.stats, "geometry": metrics,
                "environment": environment(), "source_sha256": source_hashes()}, out / "metrics.json")
    render_cluster(result.positions, out / "poster.png", probability=result.config.sticking_probability)
    plot_geometry([(result.config.sticking_probability, metrics["growth"])],
                  [(result.config.sticking_probability, metrics["dimension_fit"])], out)
    if animate:
        print("Сохранение GIF по истории реальных присоединений…", flush=True)
        render_growth(result.positions, out / "growth.gif", probability=result.config.sticking_probability,
                      fps=fps, frames=frames)
    print(f"Готово: {out.resolve()}", flush=True)


def main(argv=None) -> int:
    root = parser()
    args = root.parse_args(argv)
    try:
        if args.command == "simulate":
            config = DLAConfig(particles=args.particles, sticking_probability=args.p, seed=args.seed,
                               grid_size=args.grid_size, launch_factor=args.launch_factor,
                               kill_factor=args.kill_factor, max_steps=args.max_steps)
            print(f"DLA: N={config.particles}, p={config.sticking_probability:g}, seed={config.seed}; {BACKEND}", flush=True)
            result = simulate(config)
            save_result(result, args.out / "cluster.npz")
            np.savetxt(args.out / "positions.csv", result.positions, fmt="%d", delimiter=",", header="x,y", comments="")
            print(f"Шагов: {result.stats['steps']:,}; время ядра: {result.stats['elapsed_seconds']:.3f} с (без JIT)", flush=True)
            _outputs(result, args.out, args.animate, args.fps, args.frames)
        elif args.command == "render":
            _outputs(load_result(args.input), args.out, args.animate, args.fps, args.frames)
        elif args.command == "validate":
            data = validate_random_walk(trials=args.trials, steps=args.steps, seed=args.seed)
            write_json(data, args.out / "validation.json")
            plot_validation(data, args.out / "validation.png")
            print(f"⟨r²⟩ = {data['measured_msd']:.4f}; теория = {data['expected_msd']:g}; z = {data['z_score']:.3f}")
            print("Проверка пройдена." if data["passed"] else "Отклонение превышает предзаданный порог 4 SE.")
            return 0 if data["passed"] else 1
        elif args.command == "experiments":
            data = run_study(args.out, particles=args.particles, replicates=args.replicates,
                             probabilities=tuple(args.probabilities), seed=args.seed,
                             progress=lambda s: print(s, flush=True))
            return 0 if data["validation"]["random_walk"]["passed"] else 1
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    return 0
