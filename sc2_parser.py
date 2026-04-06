import sys
import os
import sc2reader
from collections import defaultdict


WORKER_NAMES = {"SCV", "Drone", "Probe", "MULE"}


def fmt_time(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def main():
    if len(sys.argv) != 2:
        print("Usage: python sc2_parser.py <path_to_replay.SC2Replay>")
        sys.exit(1)

    replay_path = sys.argv[1]
    if not os.path.isfile(replay_path):
        print(f"Error: File not found -> {replay_path}")
        sys.exit(1)

    try:
        replay = sc2reader.load_replay(replay_path, load_level=4)
    except Exception as e:
        print(f"Error loading replay: {e}")
        sys.exit(1)

    output_path = os.path.splitext(replay_path)[0] + ".txt"

    # Per-player tracking
    control_groups = defaultdict(lambda: defaultdict(list))
    current_selection = defaultdict(list)
    last_worker_time = {}
    worker_gaps = defaultdict(list)
    stats_snapshots = defaultdict(list)
    units_produced = defaultdict(lambda: defaultdict(int))
    units_lost = defaultdict(lambda: defaultdict(int))
    upgrades_completed = defaultdict(list)

    # Build pid -> player name map (covers events that use pid instead of player obj)
    pid_to_name = {p.pid: p.name for p in replay.players}

    for p in replay.players:
        last_worker_time[p.name] = None

    with open(output_path, "w", encoding="utf-8") as out:

        # ------------------------------------------------------------------ #
        # METADATA
        # ------------------------------------------------------------------ #
        out.write("=" * 60 + "\n")
        out.write("REPLAY METADATA\n")
        out.write("=" * 60 + "\n")
        out.write(f"Map:        {getattr(replay, 'map_name', 'Unknown')}\n")
        out.write(f"Build:      {getattr(replay, 'release_string', 'Unknown')}\n")
        out.write(f"Game Type:  {getattr(replay, 'game_type', 'Unknown')}\n")
        out.write(f"Speed:      {getattr(replay, 'speed', 'Unknown')}\n")
        out.write(f"Region:     {getattr(replay, 'region', 'Unknown')}\n")

        duration = getattr(replay, 'length', None)
        if duration:
            out.write(f"Duration:   {fmt_time(duration.seconds)}\n")

        winner = getattr(replay, 'winner', None)
        if winner:
            names = ', '.join(p.name for p in winner.players)
            out.write(f"Winner:     Team {winner.number} ({names})\n")

        out.write("\n")

        # ------------------------------------------------------------------ #
        # PLAYERS
        # ------------------------------------------------------------------ #
        out.write("=" * 60 + "\n")
        out.write("PLAYERS\n")
        out.write("=" * 60 + "\n")
        for player in replay.players:
            race = getattr(player, 'play_race', getattr(player, 'pick_race', 'Unknown'))
            result = getattr(player, 'result', 'Unknown')
            apm = getattr(player, 'avg_apm', None)
            apm_str = f"{apm:.1f}" if isinstance(apm, float) else str(apm)
            out.write(f"  [{player.name}] Race={race}  Result={result}  APM={apm_str}\n")
        out.write("\n")

        # ------------------------------------------------------------------ #
        # CHRONOLOGICAL EVENTS
        # ------------------------------------------------------------------ #
        out.write("=" * 60 + "\n")
        out.write("EVENTS (chronological)\n")
        out.write("=" * 60 + "\n")

        for event in replay.events:
            ename = event.name
            time = event.second
            tstr = fmt_time(time)

            player = getattr(event, 'player', None)
            pname = player.name if player else None
            prefix = f"{tstr} [{pname}]" if pname else f"{tstr} [GAME]"

            # --- Selection ---
            if ename == "SelectionEvent":
                units = [u.name for u in event.objects]
                current_selection[pname] = list(event.objects)
                out.write(f"{prefix} SELECT: {units}\n")

            # --- Control Groups ---
            elif ename == "SetControlGroupEvent":
                sel = current_selection[pname]
                control_groups[pname][event.control_group] = list(sel)
                units = [u.name for u in sel]
                out.write(f"{prefix} SET group {event.control_group}: {units}\n")

            elif ename == "AddToControlGroupEvent":
                sel = current_selection[pname]
                control_groups[pname][event.control_group].extend(sel)
                units = [u.name for u in sel]
                out.write(f"{prefix} ADD group {event.control_group}: {units}\n")

            elif ename == "GetControlGroupEvent":
                units = control_groups[pname][event.control_group]
                unit_names = [u.name for u in units]
                out.write(f"{prefix} RECALL group {event.control_group}: {unit_names}\n")

            # --- Abilities / Commands ---
            elif ename == "BasicCommandEvent":
                ability = getattr(event, 'ability_name', None) or getattr(event, 'ability', 'Unknown')
                out.write(f"{prefix} ABILITY: {ability}\n")

            elif ename == "TargetPointCommandEvent":
                ability = getattr(event, 'ability_name', None) or getattr(event, 'ability', 'Unknown')
                loc = getattr(event, 'location', None)
                if loc:
                    lx, ly = (loc[0], loc[1]) if isinstance(loc, tuple) else (loc.x, loc.y)
                    loc_str = f" @ ({lx:.1f}, {ly:.1f})"
                else:
                    loc_str = ""
                out.write(f"{prefix} ABILITY: {ability}{loc_str}\n")

            elif ename == "TargetUnitCommandEvent":
                ability = getattr(event, 'ability_name', None) or getattr(event, 'ability', 'Unknown')
                target = getattr(event, 'target', None)
                tgt_str = f" -> {target.name}" if target and hasattr(target, 'name') else ""
                out.write(f"{prefix} ABILITY: {ability}{tgt_str}\n")

            # --- Unit Born ---
            elif ename == "UnitBornEvent":
                unit_name = getattr(event, 'unit_type_name', None) or event.unit.name
                control_pid = getattr(event, 'control_pid', None)
                owner = pid_to_name.get(control_pid)
                p_str = f"[{owner}]" if owner else "[NEUTRAL]"
                out.write(f"{tstr} {p_str} UNIT BORN: {unit_name}\n")

                if owner:
                    units_produced[owner][unit_name] += 1
                    if unit_name in WORKER_NAMES:
                        prev = last_worker_time[owner]
                        if prev is not None:
                            gap = time - prev
                            if gap > 30:
                                worker_gaps[owner].append((prev, time, gap))
                        last_worker_time[owner] = time

            # --- Unit Done (finished building/training) ---
            elif ename == "UnitDoneEvent":
                unit_name = event.unit.name
                out.write(f"{prefix} UNIT DONE: {unit_name}\n")

            # --- Unit Died ---
            elif ename == "UnitDiedEvent":
                unit_name = event.unit.name
                unit_owner_obj = getattr(event.unit, 'owner', None)
                unit_owner = unit_owner_obj.name if unit_owner_obj and hasattr(unit_owner_obj, 'name') else None

                killer = getattr(event, 'killer', None)
                killer_pid = getattr(event, 'killer_pid', None)
                killer_owner = pid_to_name.get(killer_pid)
                killer_name = killer.name if killer and hasattr(killer, 'name') else "Unknown"

                u_str = f"[{unit_owner}]" if unit_owner else "[?]"
                k_str = f"by {killer_name} ({killer_owner})" if killer_owner else f"by {killer_name}"
                out.write(f"{tstr} {u_str} UNIT DIED: {unit_name} — killed {k_str}\n")

                if unit_owner:
                    units_lost[unit_owner][unit_name] += 1

            # --- Unit Morph ---
            elif ename == "UnitTypeChangeEvent":
                new_type = getattr(event, 'unit_type_name', 'Unknown')
                out.write(f"{prefix} UNIT MORPHED: {event.unit.name} -> {new_type}\n")

            # --- Upgrades ---
            elif ename == "UpgradeCompleteEvent":
                upgrade = getattr(event, 'upgrade_type_name', 'Unknown')
                out.write(f"{prefix} UPGRADE COMPLETE: {upgrade}\n")
                if pname:
                    upgrades_completed[pname].append((time, upgrade))

            # --- Camera ---
            elif ename == "CameraEvent":
                loc = getattr(event, 'location', None)
                if loc:
                    if isinstance(loc, tuple):
                        out.write(f"{prefix} CAMERA: ({loc[0]:.1f}, {loc[1]:.1f})\n")
                    else:
                        out.write(f"{prefix} CAMERA: ({loc.x:.1f}, {loc.y:.1f})\n")

            # --- Chat ---
            elif ename == "ChatEvent":
                text = getattr(event, 'text', '')
                out.write(f"{prefix} CHAT: \"{text}\"\n")

            # --- Player Stats (every ~10s) ---
            elif ename == "PlayerStatsEvent":
                if pname:
                    snap = {
                        "time":             time,
                        "minerals_current": getattr(event, 'minerals_current', 0),
                        "vespene_current":  getattr(event, 'vespene_current', 0),
                        "minerals_rate":    getattr(event, 'minerals_collection_rate', 0),
                        "vespene_rate":     getattr(event, 'vespene_collection_rate', 0),
                        "workers_active":   getattr(event, 'workers_active_count', 0),
                        "food_used":        getattr(event, 'food_used', 0),
                        "food_made":        getattr(event, 'food_made', 0),
                        "food_army":        getattr(event, 'food_army', 0),
                        "food_workers":     getattr(event, 'food_workers', 0),
                        "minerals_lost":    getattr(event, 'minerals_lost_army', 0),
                        "vespene_lost":     getattr(event, 'vespene_lost_army', 0),
                        "minerals_killed":  getattr(event, 'minerals_killed_army', 0),
                        "vespene_killed":   getattr(event, 'vespene_killed_army', 0),
                    }
                    stats_snapshots[pname].append(snap)
                    out.write(
                        f"{prefix} STATS: "
                        f"Min={snap['minerals_current']} Gas={snap['vespene_current']} "
                        f"MinRate={snap['minerals_rate']} GasRate={snap['vespene_rate']} "
                        f"Workers={snap['workers_active']} "
                        f"Supply={snap['food_used']}/{snap['food_made']} "
                        f"Army={snap['food_army']} "
                        f"LostMin={snap['minerals_lost']} LostGas={snap['vespene_lost']}\n"
                    )

            # --- Everything else (with a player attached) ---
            elif pname:
                out.write(f"{prefix} EVENT: {ename}\n")

        # ------------------------------------------------------------------ #
        # EFFICIENCY SUMMARY
        # ------------------------------------------------------------------ #
        out.write("\n")
        out.write("=" * 60 + "\n")
        out.write("EFFICIENCY SUMMARY (per player)\n")
        out.write("=" * 60 + "\n")

        for player in replay.players:
            pname = player.name
            race = getattr(player, 'play_race', getattr(player, 'pick_race', '?'))
            result = getattr(player, 'result', '?')
            apm = getattr(player, 'avg_apm', 0) or 0

            out.write(f"\n--- {pname} ({race}) | {result} | APM: {apm:.1f} ---\n")

            # Units produced / lost
            produced = units_produced[pname]
            lost = units_lost[pname]
            if produced:
                out.write("  Units Produced:\n")
                for unit, count in sorted(produced.items(), key=lambda x: -x[1]):
                    out.write(f"    {unit}: {count} produced, {lost.get(unit, 0)} lost\n")

            # Worker production gaps
            gaps = worker_gaps[pname]
            out.write(f"  Worker Production Gaps (>30s): {len(gaps)}\n")
            for start, end, gap in gaps:
                out.write(f"    {fmt_time(start)} -> {fmt_time(end)} ({gap:.0f}s)\n")

            # Upgrades
            ups = upgrades_completed[pname]
            if ups:
                out.write("  Upgrades Completed:\n")
                for t, upg in ups:
                    out.write(f"    {fmt_time(t)} {upg}\n")

            # Stats-derived efficiency metrics
            snaps = stats_snapshots[pname]
            if snaps:
                avg_min = sum(s['minerals_current'] for s in snaps) / len(snaps)
                avg_gas = sum(s['vespene_current'] for s in snaps) / len(snaps)
                avg_workers = sum(s['workers_active'] for s in snaps) / len(snaps)
                supply_blocks = sum(
                    1 for s in snaps
                    if s['food_used'] >= s['food_made'] and s['food_made'] < 200
                )
                final = snaps[-1]
                out.write(f"  Avg Unspent Minerals:          {avg_min:.0f}\n")
                out.write(f"  Avg Unspent Gas:               {avg_gas:.0f}\n")
                out.write(f"  Avg Workers Active:            {avg_workers:.1f}\n")
                out.write(f"  Supply Block Snapshots:        {supply_blocks}\n")
                out.write(f"  Army Resources Lost (final):   {final['minerals_lost']} min / {final['vespene_lost']} gas\n")
                out.write(f"  Enemy Resources Killed (final):{final['minerals_killed']} min / {final['vespene_killed']} gas\n")

        out.write("\n" + "=" * 60 + "\n")

    print(f"Output written to {output_path}")


if __name__ == "__main__":
    main()
