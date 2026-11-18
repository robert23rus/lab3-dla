"""Offline audit of the deliverable: links, media, raw data and provenance.

Unlike unit tests, this command checks the concrete saved experiment and all
files referenced by the README. It never starts new random-walk simulations.
"""

from __future__ import annotations

from collections import defaultdict
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import unquote
from zipfile import ZipFile

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dla.analysis import cluster_metrics, ensemble_summary
from dla.model import load_result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def equal(a, b):
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-10)


def anchors(path):
    found, occurrences = set(), defaultdict(int)
    for title in re.findall(r"^#{1,6}\s+(.+)$", path.read_text(encoding="utf-8"), flags=re.M):
        slug = re.sub(r"[^\w\s-]", "", title.lower().replace("`", ""))
        slug = re.sub(r"\s", "-", slug)
        count = occurrences[slug]
        found.add(slug + (f"-{count}" if count else ""))
        occurrences[slug] += 1
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-report", action="store_true", help="also audit locally generated DOCX/PDF")
    args = parser.parse_args(argv)
    count_links = 0
    for md in [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]:
        for link in re.findall(r"!?\[[^\]\n]*\]\(([^)\n]+)\)", md.read_text(encoding="utf-8")):
            link = unquote(link.strip("<>"))
            if re.match(r"[a-z]+://", link):
                continue
            filename, _, fragment = link.partition("#")
            target = (md.parent / filename).resolve() if filename else md
            require(target.exists(), f"Broken link in {md.name}: {link}")
            if fragment and target.suffix == ".md":
                require(fragment in anchors(target), f"Missing anchor in {target.name}: {fragment}")
            count_links += 1
    manifest = json.loads((ROOT / "docs/media/manifest.json").read_text(encoding="utf-8"))
    for relative, record in manifest["files"].items():
        path = ROOT / relative
        require(path.is_file(), f"Missing asset: {relative}")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], f"Changed asset: {relative}")
        if path.suffix == ".gif":
            with Image.open(path) as image:
                require(image.n_frames == record["frames"], f"GIF frame count: {relative}")
                require(image.size == (record["width"], record["height"]), f"GIF size: {relative}")
                require(image.info.get("loop") == 0, f"GIF must loop: {relative}")
                duration = 0
                first, last = None, None
                for i in range(image.n_frames):
                    image.seek(i)
                    duration += image.info["duration"]
                    if i == 0:
                        first = image.convert("RGB").tobytes()
                    last = image.convert("RGB").tobytes()
                require(first != last, f"GIF does not show growth: {relative}")
                require(duration == record["duration_ms"], f"GIF timing: {relative}")
    summary_path = ROOT / "docs/results/summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for relative, expected in summary["source_sha256"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        require(actual == expected, f"Source differs from measured version: {relative}")
    checked = set()
    for row in summary["runs"]:
        result = load_result(ROOT / row["archive"])
        require(result.config.seed == row["seed"], "Archive seed mismatch")
        require(result.config.particles == row["N"], "Archive N mismatch")
        require(result.config.sticking_probability == row["p"], "Archive p mismatch")
        require(result.stats["run_environment"] == summary["environment"], "Run environment mismatch")
        metrics = cluster_metrics(result.positions)
        for field in ["rg", "rmax", "dimension"]:
            require(equal(metrics[field], row[field]), f"Changed geometry {row['archive']}: {field}")
        for field in ["steps", "launches", "escapes", "contact_attempts", "elapsed_seconds"]:
            require(equal(result.stats[field], row[field]), f"Changed statistics: {field}")
        if row["archive"] not in checked:
            occupied = {(0, 0)}
            for x, y in result.positions[1:]:
                cell = (int(x), int(y))
                require(cell not in occupied, "Duplicate occupied cell")
                require(any(q in occupied for q in [(x+1, y), (x-1, y), (x, y+1), (x, y-1)]),
                        "A particle attached without a four-neighbour contact")
                occupied.add(cell)
            checked.add(row["archive"])
    for group in summary["experiments"]["sticking"]:
        rows = [r for r in summary["runs"] if r["experiment"] == "sticking" and r["p"] == group["p"]]
        actual = ensemble_summary(rows)
        for key in ["rg_mean", "rg_std", "dimension_mean", "dimension_std", "steps_mean", "seconds_mean"]:
            require(equal(group[key], actual[key]), f"Ensemble summary differs: {key}")
    if args.with_report:
        reports = list((ROOT / "report").glob("*.docx"))
        require(len(reports) == 1, "Exactly one report DOCX is expected")
        with ZipFile(reports[0]) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
            require(hashlib.sha256(summary_path.read_bytes()).hexdigest() in document_xml,
                    "Report was generated from a different summary.json")
            require("<m:oMath" in document_xml, "Report contains no native OfficeMath equations")
        require(reports[0].with_suffix(".pdf").exists(), "Report PDF is missing")
    print(f"OK: {count_links} local Markdown links; {len(manifest['files'])} asset hashes; "
          f"{len(checked)} measured runs; statistics" + (" and report provenance." if args.with_report else "."))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as error:
        print(f"AUDIT FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
