"""Publication figures with explicit units and between-run dispersion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

COLOURS = ["#087f99", "#9e459b", "#db8b23", "#576aa4"]


def _setup():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": .18,
                         "figure.facecolor": "white", "savefig.facecolor": "white"})


def _save(figure, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=190, bbox_inches="tight")
    plt.close(figure)
    return target


def plot_validation(validation: dict[str, Any], path: str | Path) -> Path:
    _setup()
    c = validation["curve"]
    k = np.array([v["steps"] for v in c])
    measured = np.array([v["measured_msd"] for v in c])
    se = np.array([v["standard_error"] for v in c])
    fig, ax = plt.subplots(1, 2, figsize=(10.2, 4))
    ax[0].plot(k, k, color="#19283e", lw=1.6, label="Теория: ⟨r²⟩ = k")
    ax[0].plot(k, measured, "o", ms=3, color=COLOURS[0], label="Среднее по реализациям")
    ax[0].fill_between(k, measured-1.96*se, measured+1.96*se, color=COLOURS[0], alpha=.2,
                       label="Приближённый 95% ДИ среднего")
    ax[0].set(xlabel="Число шагов k", ylabel="⟨r²⟩, клетка²", title="Проверка свободной диффузии")
    ax[0].legend(fontsize=8)
    ax[1].axhline(0, color="#19283e", lw=1)
    ax[1].errorbar(k, 100*(measured/k-1), yerr=100*1.96*se/k, fmt="o", ms=3,
                   color=COLOURS[0], lw=.7, capsize=2)
    ax[1].set(xlabel="Число шагов k", ylabel="Отклонение среднего от теории, %",
              title=f"Независимых траекторий: {validation['trials']:,}")
    fig.tight_layout()
    return _save(fig, path)


def plot_geometry(curves: list[tuple[float, dict]], fits: list[tuple[float, dict]],
                  directory: str | Path) -> dict[str, Path]:
    _setup()
    directory = Path(directory)
    fig, ax = plt.subplots(figsize=(9, 4.9))
    for i, (p, curve) in enumerate(curves):
        n, rg = np.array(curve["N"]), np.array(curve["rg"])
        valid = (n >= 10) & (rg > 0)
        ax.loglog(n[valid], rg[valid], color=COLOURS[i % 4], lw=1.7, label=f"p = {p:g}")
    ax.set(xlabel="Число присоединившихся частиц N (включая зародыш)",
           ylabel="Радиус инерции Rg, клетка", title="Геометрия роста: по одной реализации для каждого p")
    ax.legend()
    growth = _save(fig, directory / "growth.png")
    fig, ax = plt.subplots(figsize=(9, 4.9))
    for i, (p, fit) in enumerate(fits):
        if fit["dimension"] is None:
            continue
        colour = COLOURS[i % 4]
        ax.loglog(fit["radii"], fit["mass"], "o", ms=3, color=colour, label=f"p = {p:g}; Dэфф = {fit['dimension']:.3f}")
        ax.loglog(fit["radii"], fit["fit_mass"], "--", lw=1.1, color=colour)
    ax.set(xlabel="Радиус вокруг конечного центра масс r, клетка", ylabel="Число частиц M(r)",
           title="Оценка размерности на фиксированном промежуточном диапазоне")
    ax.legend(fontsize=9)
    dimension = _save(fig, directory / "dimension.png")
    return {"growth": growth, "dimension": dimension}


def plot_sticking(groups: list[dict], path: str | Path) -> Path:
    _setup()
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 4.1))
    for ax, field, label, factor in zip(axes, ["rg", "dimension", "steps"],
            ["Радиус инерции, клетка", "Эффективная размерность", "Число случайных шагов, млн"], [1, 1, 1e-6]):
        x = np.arange(len(groups))
        values = [g[field+"_mean"] * factor if g[field+"_mean"] is not None else np.nan for g in groups]
        error = [(g[field+"_std"] or 0) * factor for g in groups]
        ax.bar(x, values, yerr=error, color=COLOURS[:len(groups)], alpha=.85, capsize=4, width=.6)
        ax.set(xticks=x, xticklabels=[f"{g['p']:g}" for g in groups], xlabel="Вероятность прилипания p", ylabel=label)
        if field == "dimension":
            ax.set_ylim(0, max(2.2, max(values)+max(error)+.1))
    fig.suptitle("Среднее ± выборочное СКО между независимыми реализациями", fontsize=11)
    fig.tight_layout()
    return _save(fig, path)


def plot_boundary(groups: list[dict], path: str | Path) -> Path:
    _setup()
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.5))
    x = np.arange(len(groups))
    labels = [f"L={g['launch_factor']:g}\nK={g['kill_factor']:g}" for g in groups]
    for ax, field, label in zip(axes, ["rg", "dimension"], ["Радиус инерции, клетка", "Эффективная размерность"]):
        values = [g[field+"_mean"] if g[field+"_mean"] is not None else np.nan for g in groups]
        error = [g[field+"_std"] or 0 for g in groups]
        ax.errorbar(x, values, yerr=error, fmt="o", ms=7, color=COLOURS[0], capsize=5)
        ax.set(xticks=x, xticklabels=labels, ylabel=label, xlabel="Коэффициенты запуска L и перезапуска K")
    fig.suptitle("Чувствительность к границам: среднее ± СКО; p = 1", fontsize=11)
    fig.tight_layout()
    return _save(fig, path)
