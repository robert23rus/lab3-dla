"""Build the gallery and a self-contained publication dataset from real runs.

Usage: python scripts/build_readme_media.py --study results/study
Existing media are reused ONLY when the scene, parameters, input positions and
renderer SHA256 all match a previous manifest. No network access is required.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dla.analysis import cluster_metrics
from dla.experiments import cached_run, environment, source_hashes, write_json
from dla.model import DLAConfig, load_result, save_result
from dla.rendering import render_cluster, render_comparison, render_growth


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def image_info(path):
    with Image.open(path) as im:
        duration = 0
        for i in range(getattr(im, "n_frames", 1)):
            im.seek(i)
            duration += im.info.get("duration", 0)
        return {"width": im.width, "height": im.height, "frames": getattr(im, "n_frames", 1),
                "duration_ms": duration, "loop": im.info.get("loop")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, default=ROOT / "results/study")
    parser.add_argument("--hero-particles", type=int, default=12000)
    parser.add_argument("--hero-seed", type=int, default=42)
    parser.add_argument("--skip-hero-render", action="store_true", help="reuse an inspected existing hero, still record exact hashes")
    args = parser.parse_args(argv)
    study = args.study.resolve()
    summary = json.loads((study / "summary.json").read_text(encoding="utf-8"))
    for relative in ["dla/model.py", "dla/analysis.py"]:
        if summary.get("source_sha256", {}).get(relative) != digest(ROOT / relative):
            parser.error(f"Study was measured with different {relative}; rerun experiments first")
    media, published = ROOT / "docs/media", ROOT / "docs/results"
    data = ROOT / "docs/data"
    for directory in (media, published, data):
        directory.mkdir(parents=True, exist_ok=True)
    # Preserve every raw archive behind the tables, not just selected examples.
    archive_mapping = {}
    for row in summary["runs"]:
        source = study / row["archive"]
        destination = data / "runs" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        archive_mapping[row["archive"]] = destination.relative_to(ROOT).as_posix()
        row["archive"] = destination.relative_to(ROOT).as_posix()
    samples = []
    for representative in summary["representatives"]:
        source_relative = representative["archive"]
        representative["archive"] = archive_mapping[source_relative]
        result = load_result(ROOT / representative["archive"])
        samples.append((representative["p"], result.positions))
    if len(samples) != 3:
        parser.error("The README gallery expects exactly three sticking probabilities")
    config = DLAConfig(particles=args.hero_particles, sticking_probability=1., seed=args.hero_seed,
                       grid_size=1025, max_steps=8_000_000_000)
    showcase = ROOT / "results/showcase/cluster.npz"
    if showcase.exists():
        hero = load_result(showcase)
        if hero.config != config or hero.stats.get("model_sha256") != digest(ROOT / "dla/model.py"):
            hero, _ = cached_run(config, ROOT / "results/readme_cache")
    else:
        hero, _ = cached_run(config, ROOT / "results/readme_cache")
    hero_path = save_result(hero, data / "showcase.npz")
    renderer_hash = digest(ROOT / "dla/rendering.py")
    old_manifest_path = media / "manifest.json"
    old = json.loads(old_manifest_path.read_text(encoding="utf-8")) if old_manifest_path.exists() else {}
    scene = {"renderer_sha256": renderer_hash, "hero_config": asdict(config),
             "hero_positions_sha256": hashlib.sha256(hero.positions.tobytes()).hexdigest(),
             "comparison_positions_sha256": [hashlib.sha256(p.tobytes()).hexdigest() for _, p in samples],
             "probabilities": [p for p, _ in samples],
             "hero_render": {"frames": 140, "fps": 20, "width": 960, "height": 720},
             "comparison_render": {"frames": 110, "fps": 20, "width": 1280, "height": 600}}
    reuse = old.get("scene") == scene
    def valid_asset(name):
        path = media / name
        record = old.get("files", {}).get(path.relative_to(ROOT).as_posix(), {})
        return path.exists() and record.get("sha256") == digest(path)

    if not args.skip_hero_render and not (reuse and valid_asset("dla-growth.gif") and valid_asset("dla-poster.png")):
        print("Rendering 12k-particle growth...", flush=True)
        render_cluster(hero.positions, media / "dla-poster.png")
        render_growth(hero.positions, media / "dla-growth.gif", frames=140, fps=20)
    if not (media / "dla-poster.png").exists() or not (media / "dla-growth.gif").exists():
        parser.error("Hero media are missing; remove --skip-hero-render")
    if not (reuse and valid_asset("sticking.gif") and valid_asset("sticking-poster.png")):
        print("Rendering equal-mass sticking comparison...", flush=True)
        render_comparison(samples, media / "sticking-poster.png")
        render_comparison(samples, media / "sticking.gif", frames=110, fps=20)
    for name, relative in list(summary["figures"].items()):
        source = study / relative
        destination = published / source.name
        shutil.copy2(source, destination)
        summary["figures"][name] = destination.relative_to(ROOT).as_posix()
    summary["figures"].update(hero="docs/media/dla-poster.png", comparison="docs/media/sticking-poster.png")
    summary["archive_paths_relative_to"] = "project root"
    summary["showcase"] = {"config": asdict(config), "stats": hero.stats,
                            "metrics": cluster_metrics(hero.positions), "archive": hero_path.relative_to(ROOT).as_posix()}
    summary["source_sha256"] = source_hashes()
    shutil.copy2(study / "runs.csv", published / "runs.csv")
    shutil.copy2(study / "validation.json", published / "validation.json")
    # CSV remains a faithful copy of the original run log; its archive paths are
    # relative to results/study. Published JSON has repository-relative paths.
    summary["csv_archive_paths_relative_to"] = "results/study"
    write_json(summary, published / "summary.json")
    files = {}
    for path in sorted([*(media.glob("*.gif")), *(media.glob("*.png")),
                        *(published.glob("*.png")), *(data.rglob("*.npz"))]):
        info = {"sha256": digest(path), "bytes": path.stat().st_size}
        if path.suffix in {".png", ".gif"}:
            info.update(image_info(path))
        files[path.relative_to(ROOT).as_posix()] = info
    write_json({"schema_version": 1, "scene": scene, "environment": environment(), "files": files,
                "source_summary": "docs/results/summary.json", "data": "docs/data",
                "animation_time": "presentation time; frames are prefixes by attached-particle count"}, media / "manifest.json")
    print(f"Gallery and self-contained data: {media}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
