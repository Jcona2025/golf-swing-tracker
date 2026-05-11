"""Stats engine for SwingLogger rounds.

Reads each web_runs/<id>/overlay.geojson and meta.json, returns JSON
shaped for the web UI (and later, the Android app — same module).

Three views:
    list_rounds()        round-history table data
    overall_stats()      timeline + headline numbers
    per_course_stats()   averages, best/worst, per-hole stats per course
"""
from pathlib import Path
import json
from collections import defaultdict
from statistics import mean


def _round_summary(run_dir: Path) -> dict | None:
    """Compute one round's summary from its overlay.geojson + meta.json."""
    overlay_path = run_dir / "overlay.geojson"
    meta_path = run_dir / "meta.json"
    if not overlay_path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    overlay = json.loads(overlay_path.read_text())

    holes = [f["properties"] for f in overlay["features"]
             if f["properties"].get("kind") == "green" and f["properties"].get("score") is not None]
    if not holes:
        return None

    n_holes = len(holes)
    score = sum(int(h["score"]) for h in holes)
    n_putts = sum(int(h.get("n_putts", 0)) for h in holes)
    n_chips = sum(int(h.get("n_chips", 0)) for h in holes)
    greens_hit = sum(1 for h in holes if h.get("pitch_on_green") is True)
    greens_played = sum(1 for h in holes if h.get("pitch_on_green") is not None)
    up_and_downs = sum(1 for h in holes if h.get("up_and_down") is True)

    return {
        "run_id": run_dir.name,
        "course": meta.get("course", "").replace(".json", ""),
        "course_display": (overlay.get("name") or "").replace(" round overlay", ""),
        "date": meta.get("date"),  # ISO string, may be None for older runs
        "original_fit": meta.get("original_fit"),
        "n_holes": n_holes,
        "score": score,
        "n_putts": n_putts,
        "n_chips": n_chips,
        "greens_hit": greens_hit,
        "greens_played": greens_played,
        "gir_pct": (100 * greens_hit / greens_played) if greens_played else None,
        "putts_per_hole": n_putts / n_holes,
        "up_and_downs": up_and_downs,
        "per_hole": [
            {
                "hole": int(h["hole"]),
                "score": int(h["score"]),
                "n_putts": int(h.get("n_putts", 0)),
                "n_chips": int(h.get("n_chips", 0)),
                "pitch_on_green": h.get("pitch_on_green"),
                "up_and_down": bool(h.get("up_and_down", False)),
            }
            for h in sorted(holes, key=lambda x: int(x["hole"]))
        ],
    }


def list_rounds(runs_dir: Path) -> list[dict]:
    """All rounds, newest first."""
    rounds = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        summary = _round_summary(run_dir)
        if summary:
            rounds.append(summary)
    # Sort by date descending if available, else by run_id
    rounds.sort(key=lambda r: (r["date"] or "", r["run_id"]), reverse=True)
    return rounds


def overall_stats(rounds: list[dict]) -> dict:
    """Headline metrics + timeline series across all rounds (chronological)."""
    if not rounds:
        return {"n_rounds": 0, "timeline": [], "headlines": {}}

    chrono = sorted(rounds, key=lambda r: (r["date"] or "", r["run_id"]))
    timeline = [
        {
            "date": r["date"],
            "course": r["course"],
            "score": r["score"],
            "putts_per_hole": round(r["putts_per_hole"], 2),
            "gir_pct": round(r["gir_pct"], 1) if r["gir_pct"] is not None else None,
            "n_holes": r["n_holes"],
        }
        for r in chrono
    ]

    scores = [r["score"] for r in rounds]
    putts = [r["putts_per_hole"] for r in rounds]
    girs = [r["gir_pct"] for r in rounds if r["gir_pct"] is not None]

    headlines = {
        "n_rounds": len(rounds),
        "best_score": min(scores),
        "avg_score": round(mean(scores), 1),
        "avg_putts_per_hole": round(mean(putts), 2),
        "avg_gir_pct": round(mean(girs), 1) if girs else None,
        "total_chips": sum(r["n_chips"] for r in rounds),
        "total_up_and_downs": sum(r["up_and_downs"] for r in rounds),
    }
    return {"timeline": timeline, "headlines": headlines}


def callouts(rounds: list[dict]) -> list[dict]:
    """Auto-generated friendly insights for the dashboard.
    Each callout: {kind, headline, detail}."""
    if not rounds:
        return []

    out = []

    # Best round
    best = min(rounds, key=lambda r: (r["score"], -r["n_holes"]))
    out.append({
        "kind": "best_round",
        "headline": f"Best round: {best['score']}",
        "detail": f"on {best['course']} ({best['date'][:10] if best['date'] else '—'})",
    })

    # Strongest / toughest hole (across all courses, hole+course pair)
    pair_scores = defaultdict(list)
    for r in rounds:
        for h in r["per_hole"]:
            pair_scores[(r["course"], h["hole"])].append(h["score"])
    avgs = [
        {"course": c, "hole": h, "avg": mean(scs), "n": len(scs)}
        for (c, h), scs in pair_scores.items() if len(scs) >= 2
    ]
    if avgs:
        strongest = min(avgs, key=lambda x: x["avg"])
        toughest = max(avgs, key=lambda x: x["avg"])
        out.append({
            "kind": "strongest_hole",
            "headline": f"Strongest hole: {strongest['course'].title()} H{strongest['hole']}",
            "detail": f"avg {strongest['avg']:.1f} over {strongest['n']} plays",
        })
        out.append({
            "kind": "toughest_hole",
            "headline": f"Toughest hole: {toughest['course'].title()} H{toughest['hole']}",
            "detail": f"avg {toughest['avg']:.1f} over {toughest['n']} plays",
        })

    # Best putting round
    best_putt = min(rounds, key=lambda r: r["putts_per_hole"])
    out.append({
        "kind": "best_putting",
        "headline": f"Best putting: {best_putt['putts_per_hole']:.2f}/hole",
        "detail": f"on {best_putt['course']} ({best_putt['date'][:10] if best_putt['date'] else '—'})",
    })

    return out


def per_course_stats(rounds: list[dict]) -> list[dict]:
    """For each course: round count, best/avg/worst score, per-hole avg score."""
    by_course = defaultdict(list)
    for r in rounds:
        by_course[r["course"]].append(r)

    out = []
    for course, course_rounds in sorted(by_course.items()):
        scores = [r["score"] for r in course_rounds]

        # Aggregate per-hole across rounds (only holes that appear)
        per_hole_scores = defaultdict(list)
        per_hole_putts = defaultdict(list)
        per_hole_chips = defaultdict(list)
        per_hole_gir = defaultdict(list)
        for r in course_rounds:
            for h in r["per_hole"]:
                per_hole_scores[h["hole"]].append(h["score"])
                per_hole_putts[h["hole"]].append(h["n_putts"])
                per_hole_chips[h["hole"]].append(h["n_chips"])
                if h["pitch_on_green"] is not None:
                    per_hole_gir[h["hole"]].append(1 if h["pitch_on_green"] else 0)

        per_hole = []
        for hole in sorted(per_hole_scores.keys()):
            scs = per_hole_scores[hole]
            per_hole.append({
                "hole": hole,
                "n_played": len(scs),
                "avg_score": round(mean(scs), 2),
                "best_score": min(scs),
                "worst_score": max(scs),
                "avg_putts": round(mean(per_hole_putts[hole]), 2),
                "gir_pct": round(100 * mean(per_hole_gir[hole]), 0) if per_hole_gir[hole] else None,
            })

        out.append({
            "course": course,
            "n_rounds": len(course_rounds),
            "best_score": min(scores),
            "avg_score": round(mean(scores), 1),
            "worst_score": max(scores),
            "per_hole": per_hole,
        })
    return out
