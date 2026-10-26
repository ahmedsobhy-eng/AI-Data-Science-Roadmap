"""Read-only inventory and overlap report for the project's CSV files."""

from pathlib import Path
import unicodedata

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "archive"}
INVALID_PHYSICAL_ROWS = {"player", "squad total", "opponent total"}


def norm(value):
    if pd.isna(value):
        return ""
    return " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()


def load_csv(path):
    try:
        return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp1252", low_memory=False)


def key_set(frame):
    columns = set(frame.columns)
    injury_cols = {"Player", "Injury", "from", "until"}
    if injury_cols.issubset(columns):
        use = ["Player", "Injury", "from", "until"]
        if "Season" in columns:
            use.append("Season")
        return "player-injury-dates", {
            tuple(norm(value) for value in row)
            for row in frame[use].itertuples(index=False, name=None)
        }
    if {"Player", "Team", "Season"}.issubset(columns):
        return "player-team-season", {
            (norm(row.Player), norm(row.Team), norm(row.Season))
            for row in frame[["Player", "Team", "Season"]].itertuples(index=False)
        }
    return None, set()


def main():
    files = sorted(
        path
        for path in PROJECT_DIR.rglob("*.csv")
        if not any(part in SKIP_DIRS for part in path.relative_to(PROJECT_DIR).parts)
    )
    frames = {}
    print("CSV inventory")
    for path in files:
        relative = path.relative_to(PROJECT_DIR)
        try:
            frame = load_csv(path)
        except Exception as exc:
            print(f"- {relative}: unreadable ({exc})")
            continue
        frames[path] = frame
        key_kind, keys = key_set(frame)
        bad_rows = 0
        if "Player" in frame:
            bad_rows = int(frame.Player.map(norm).isin(INVALID_PHYSICAL_ROWS).sum())
        duplicate_keys = len(frame) - len(keys) if key_kind else "n/a"
        dimensions = []
        for column in ("Season", "Team"):
            if column in frame:
                dimensions.append(f"{column}={frame[column].nunique(dropna=True)}")
        print(
            f"- {relative}: rows={len(frame)}, {', '.join(dimensions)}, "
            f"key={key_kind or 'none'}, duplicate keys={duplicate_keys}, "
            f"header/summary rows={bad_rows}"
        )

    print("\nComparable file overlaps")
    entries = list(frames.items())
    for index, (path_a, frame_a) in enumerate(entries):
        kind_a, keys_a = key_set(frame_a)
        if not kind_a:
            continue
        for path_b, frame_b in entries[index + 1:]:
            kind_b, keys_b = key_set(frame_b)
            if kind_a != kind_b:
                continue
            common = len(keys_a & keys_b)
            if common:
                smaller = min(len(keys_a), len(keys_b))
                print(
                    f"- {path_a.relative_to(PROJECT_DIR)} <> "
                    f"{path_b.relative_to(PROJECT_DIR)}: shared {kind_a} keys="
                    f"{common}/{smaller} of smaller file"
                )


if __name__ == "__main__":
    main()
