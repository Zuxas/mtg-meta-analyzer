"""
Meta clustering — group archetypes by card-shell similarity within a format.

Jaccard similarity on each archetype's average-deck card list, then
greedy agglomerative merging: repeatedly join the pair of clusters with
the highest inter-cluster similarity until no pair exceeds a threshold.

Usage:
    from analysis.meta_clustering import cluster_archetypes
    clusters = cluster_archetypes("modern", top=15, threshold=0.35)
    for c in clusters:
        print(c["label"], c["archetypes"])
"""


def _avg_deck_cards(archetype: str, format_name: str) -> set:
    """Return the set of card names present in an archetype's average deck
    (mainboard only, inclusion >= 25%). Empty set if nothing found."""
    try:
        from analysis.deck_analysis import get_average_deck
        avg = get_average_deck(archetype, format_name, min_inclusion=0.25)
    except Exception:
        return set()
    if not avg:
        return set()
    # get_average_deck returns either a list of {card_name,...} dicts or a
    # dict with mainboard/sideboard; probe both shapes.
    if isinstance(avg, dict):
        mb = avg.get("mainboard") or []
    elif isinstance(avg, list):
        mb = avg
    else:
        mb = []
    names = set()
    for entry in mb:
        if isinstance(entry, dict):
            name = entry.get("card_name") or entry.get("name")
            if name:
                names.add(name)
    return names


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def cluster_archetypes(format_name: str, top: int = 15,
                       threshold: float = 0.35) -> list:
    """Return a list of clusters. Each cluster:
        {label, archetypes: [name], total_meta_share, avg_points}

    threshold: minimum Jaccard similarity required to merge two clusters.
    0.35 works for Modern; looser formats may need 0.25, tighter ones 0.45.
    """
    from analysis.win_rates import get_meta_standings

    standings = get_meta_standings(format_name, top=top, min_appearances=3)
    if not standings:
        return []

    # Build one cluster per archetype with its average-deck card set.
    clusters = []
    for s in standings:
        arch = s.get("archetype", "")
        if not arch:
            continue
        cards = _avg_deck_cards(arch, format_name)
        if not cards:
            # Skip archetypes with no scraped average deck — they can't
            # contribute to similarity. Keep them as singletons so the UI
            # still lists them.
            clusters.append({
                "archetypes": [arch],
                "cards": set(),
                "meta_share": _meta_share(s, standings),
                "avg_points": s.get("avg_points", 0),
                "singleton": True,
            })
            continue
        clusters.append({
            "archetypes": [arch],
            "cards": cards,
            "meta_share": _meta_share(s, standings),
            "avg_points": s.get("avg_points", 0),
            "singleton": False,
        })

    # Greedy agglomerative merging. Re-compute best pair each pass.
    # Stops when no pair exceeds the threshold.
    while True:
        best = None
        best_sim = threshold
        for i in range(len(clusters)):
            if clusters[i]["singleton"]:
                continue
            for j in range(i + 1, len(clusters)):
                if clusters[j]["singleton"]:
                    continue
                sim = _jaccard(clusters[i]["cards"], clusters[j]["cards"])
                if sim > best_sim:
                    best_sim = sim
                    best = (i, j)
        if best is None:
            break
        i, j = best
        a, b = clusters[i], clusters[j]
        merged = {
            "archetypes": a["archetypes"] + b["archetypes"],
            "cards": a["cards"] | b["cards"],
            "meta_share": a["meta_share"] + b["meta_share"],
            "avg_points": (a["avg_points"] * len(a["archetypes"])
                            + b["avg_points"] * len(b["archetypes"]))
                           / (len(a["archetypes"]) + len(b["archetypes"])),
            "singleton": False,
        }
        clusters = [c for k, c in enumerate(clusters) if k not in (i, j)]
        clusters.append(merged)

    # Label clusters by their largest-share archetype; rank by total share.
    clusters.sort(key=lambda c: -c["meta_share"])
    for c in clusters:
        c["label"] = c["archetypes"][0]
        # Drop the card set from the public contract (large + not useful to UI)
        c.pop("cards", None)
        c.pop("singleton", None)
        c["archetypes"] = sorted(c["archetypes"])
    return clusters


def _meta_share(stats: dict, standings: list) -> float:
    """Compute meta share from standings — appearances / total apps."""
    total = sum(s.get("appearances", 0) for s in standings)
    if not total:
        return 0.0
    return stats.get("appearances", 0) / total
