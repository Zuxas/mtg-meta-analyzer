"""
Gauntlet builder — auto-select top meta archetypes and export decklists.

Builds a testing gauntlet from the current meta: picks top N archetypes,
pulls average decklists, exports in formats compatible with mtg-sim.

Usage:
    from analysis.gauntlet_builder import build_gauntlet
    result = build_gauntlet("standard", top=8)
    # result["decks"] = list of {archetype, mainboard, sideboard, meta_share, ...}
    # result["field_csv"] = CSV string for mtg-sim
    # result["deck_files"] = {archetype: txt_content} for mtg-sim deck files
"""

import os
from datetime import datetime, timedelta


def build_gauntlet(format_name: str = "standard", top: int = 8,
                   weeks: int = 4, min_appearances: int = 10,
                   export_dir: str = None) -> dict:
    """
    Build a testing gauntlet from the current meta.

    Args:
        format_name: Format to build gauntlet for.
        top: Number of archetypes to include.
        weeks: Timeframe for meta standings.
        min_appearances: Minimum appearances to include.
        export_dir: If set, write deck files and field.csv here.

    Returns:
        {
            "format": str,
            "archetypes": int,
            "total_decks_analyzed": int,
            "decks": [
                {
                    "archetype": str,
                    "meta_share": float,
                    "win_rate": float | None,
                    "deck_count": int,       # how many lists averaged
                    "mainboard": dict,       # {card: qty}
                    "sideboard": dict,       # {card: qty}
                },
                ...
            ],
            "field_csv": str,          # archetype,share CSV for mtg-sim
            "deck_files": dict,        # {archetype: txt_content}
            "exported_to": str | None, # directory path if exported
        }
    """
    from analysis.win_rates import get_meta_standings
    from analysis.deck_analysis import get_average_deck

    since = datetime.now() - timedelta(weeks=weeks)
    standings = get_meta_standings(
        format_name, top=top, min_appearances=min_appearances, since=since,
    )

    if not standings:
        return {
            "format": format_name, "archetypes": 0, "total_decks_analyzed": 0,
            "decks": [], "field_csv": "", "deck_files": {}, "exported_to": None,
        }

    decks = []
    deck_files = {}
    field_lines = ["archetype,share"]

    for s in standings[:top]:
        arch = s["archetype"]
        avg = get_average_deck(arch, format_name, min_inclusion=0.20)
        if not avg or not avg.get("mainboard"):
            continue

        # Build card dicts: {name: suggested_qty}
        main = {}
        for c in avg["mainboard"]:
            qty = c.get("suggested_qty", round(c.get("avg_qty", 1)))
            if qty > 0:
                main[c["name"]] = qty

        side = {}
        for c in avg.get("sideboard", []):
            qty = c.get("suggested_qty", round(c.get("avg_qty", 1)))
            if qty > 0:
                side[c["name"]] = qty

        decks.append({
            "archetype": arch,
            "meta_share": s.get("meta_share", 0),
            "win_rate": s.get("est_match_winpct"),
            "deck_count": avg.get("deck_count", 0),
            "mainboard": main,
            "sideboard": side,
        })

        # Generate mtg-sim compatible deck file
        txt = _deck_to_txt(arch, main, side, avg.get("deck_count", 0))
        deck_files[arch] = txt

        # Field CSV line
        field_lines.append(f"{arch},{s.get('meta_share', 0):.4f}")

    field_csv = "\n".join(field_lines)

    # Export if directory specified
    exported_to = None
    if export_dir and decks:
        exported_to = _export_gauntlet(export_dir, format_name, deck_files, field_csv)

    return {
        "format": format_name,
        "archetypes": len(decks),
        "total_decks_analyzed": sum(d["deck_count"] for d in decks),
        "decks": decks,
        "field_csv": field_csv,
        "deck_files": deck_files,
        "exported_to": exported_to,
    }


def _deck_to_txt(archetype: str, main: dict, side: dict,
                 deck_count: int) -> str:
    """Convert a deck dict to mtg-sim compatible text format."""
    lines = [f"// {archetype} — Average of {deck_count} tournament lists"]

    # Mainboard sorted alphabetically
    for name in sorted(main.keys()):
        lines.append(f"{main[name]} {name}")

    if side:
        lines.append("")
        lines.append("// Sideboard")
        for name in sorted(side.keys()):
            lines.append(f"{side[name]} {name}")

    return "\n".join(lines)


def _export_gauntlet(export_dir: str, format_name: str,
                     deck_files: dict, field_csv: str) -> str:
    """Write deck files and field.csv to the export directory."""
    gauntlet_dir = os.path.join(export_dir, f"gauntlet_{format_name}")
    os.makedirs(gauntlet_dir, exist_ok=True)

    # Write field.csv
    with open(os.path.join(gauntlet_dir, "field.csv"), "w", encoding="utf-8") as f:
        f.write(field_csv)

    # Write individual deck files
    for arch, txt in deck_files.items():
        safe_name = arch.lower().replace(" ", "_").replace("/", "_")
        with open(os.path.join(gauntlet_dir, f"{safe_name}.txt"), "w", encoding="utf-8") as f:
            f.write(txt)

    return gauntlet_dir
