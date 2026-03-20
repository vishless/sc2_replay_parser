import sys
import os
import sc2reader
from collections import defaultdict


def main():
    if len(sys.argv) != 2:
        print("Usage: python script.py <path_to_replay.SC2Replay>")
        sys.exit(1)

    replay_path = sys.argv[1]

    if not os.path.isfile(replay_path):
        print(f"Error: File not found -> {replay_path}")
        sys.exit(1)

    try:
        replay = sc2reader.load_replay(replay_path)
    except Exception as e:
        print(f"Error loading replay: {e}")
        sys.exit(1)

    output_path = os.path.splitext(replay_path)[0] + ".txt"

    control_groups = defaultdict(lambda: defaultdict(list))
    current_selection = defaultdict(list)

    with open(output_path, "w") as out:
        for event in replay.events:

            if not hasattr(event, "player") or event.player is None:
                continue

            player = event.player.name
            time = event.second

            # --- Set control group (uses current selection as the group contents) ---
            if event.name == "SetControlGroupEvent":
                sel = current_selection[player]
                control_groups[player][event.control_group] = list(sel)
                units = [u.name for u in sel]
                out.write(f"{time}s [{player}] SET group {event.control_group}: {units}\n")

            # --- Add to control group (adds current selection to the group) ---
            elif event.name == "AddToControlGroupEvent":
                sel = current_selection[player]
                control_groups[player][event.control_group].extend(sel)
                units = [u.name for u in sel]
                out.write(f"{time}s [{player}] ADD group {event.control_group}: {units}\n")

            # --- Recall control group ---
            elif event.name == "GetControlGroupEvent":
                units = control_groups[player][event.control_group]
                unit_names = [u.name for u in units]
                out.write(f"{time}s [{player}] RECALL group {event.control_group}: {unit_names}\n")

            # --- Direct selection ---
            elif event.name == "SelectionEvent":
                current_selection[player] = list(event.objects)
                units = [u.name for u in event.objects]
                out.write(f"{time}s [{player}] SELECT: {units}\n")

    print(f"Output written to {output_path}")


if __name__ == "__main__":
    main()
