import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def get_git_info(folder):
    """Record the current commit and whether local changes exist."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=folder,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()

        changes = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=folder,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()

        return {
            "commit": commit,
            "working_tree_dirty": bool(changes),
        }

    except (subprocess.CalledProcessError, FileNotFoundError):
        return {
            "commit": None,
            "working_tree_dirty": None,
        }


def load_config(path):
    with open(path, encoding="utf-8") as file:
        config = json.load(file)

    for key in ["policies", "scenarios", "seeds"]:
        values = config.get(key)

        if not isinstance(values, list) or not values:
            raise ValueError(f"{key} must be a non-empty list.")

    # Keep policy/scenario names safe for use in folder paths.
    for key in ["policies", "scenarios"]:
        for name in config[key]:
            if not isinstance(name, str) or not name:
                raise ValueError(f"{key} must contain non-empty strings.")

            if not all(
                character.isascii()
                and (character.isalnum() or character in "_-")
                for character in name
            ):
                raise ValueError(
                    f"Invalid name: {name}. Use letters, numbers, _ or -."
                )

        if len(set(config[key])) != len(config[key]):
            raise ValueError(f"{key} contains duplicate entries.")

    for seed in config["seeds"]:
        if type(seed) is not int or seed < 0:
            raise ValueError("Seeds must be non-negative integers.")

    if len(set(config["seeds"])) != len(config["seeds"]):
        raise ValueError("Seeds contains duplicate entries.")

    if len(config["seeds"]) < 10:
        raise ValueError("Use at least 10 seeds for this experiment plan.")

    return config


def create_plan(config, output_dir, git_info):
    rows = []

    for policy in config["policies"]:
        for scenario in config["scenarios"]:
            for seed in config["seeds"]:
                rows.append({
                    "run_id": f"{policy}__{scenario}__seed_{seed}",
                    "policy": policy,
                    "scenario": scenario,
                    "seed": seed,
                    "status": "planned",
                    "output_directory": (
                        Path("runs")
                        / policy
                        / scenario
                        / f"seed_{seed}"
                    ).as_posix(),
                })

    # Refuse to overwrite an existing plan.
    output_dir.mkdir(parents=True, exist_ok=False)

    with open(
        output_dir / "config_snapshot.json", "w", encoding="utf-8"
    ) as file:
        json.dump(config, file, indent=2)
        file.write("\n")

    metadata = {
        "mode": "dry_run",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_info["commit"],
        "working_tree_dirty": git_info["working_tree_dirty"],
        "planned_runs": len(rows),
        "executed_runs": 0,
        "note": (
            "Experiment plan only. No simulations were executed. "
            "Policy identifiers and scenario paths require integration."
        ),
    }

    with open(
        output_dir / "plan_metadata.json", "w", encoding="utf-8"
    ) as file:
        json.dump(metadata, file, indent=2)
        file.write("\n")

    with open(
        output_dir / "experiment_plan.csv",
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Prepare the scheduling experiment grid."
    )

    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)

    # Execution is deliberately unavailable until simulator integration.
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if not args.dry_run:
        parser.error(
            "Simulator execution is not integrated. Use --dry-run."
        )

    config_path = Path(args.config).resolve()
    output_dir = Path(args.output).resolve()

    config = load_config(config_path)
    git_info = get_git_info(config_path.parent)

    total = create_plan(config, output_dir, git_info)

    print(f"Policies: {len(config['policies'])}")
    print(f"Scenarios: {len(config['scenarios'])}")
    print(f"Seeds: {len(config['seeds'])}")
    print(f"Planned experiments: {total}")
    print("Executed experiments: 0")
    print(f"Plan saved to: {output_dir}")


if __name__ == "__main__":
    main()