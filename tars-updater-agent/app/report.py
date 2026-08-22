"""Print stored scan findings from the local SQLite DB. Run with `python -m app.report`."""
import argparse
from app.storage.db import get_vulnerability_findings, get_update_findings


def main():
    parser = argparse.ArgumentParser(description="View persisted Tars Updater Agent findings.")
    parser.add_argument("--limit", type=int, default=50, help="Max rows per category")
    args = parser.parse_args()

    vulns = get_vulnerability_findings(args.limit)
    print(f"\n=== Vulnerability findings (most recent {len(vulns)}) ===")
    for v in vulns:
        print(f"[{v['last_seen']}] {v['cve_id']} in {v['target']} "
              f"({v['pkg_name']} {v['installed_version']} -> {v['fixed_version']}) "
              f"first seen {v['first_seen']}")

    updates = get_update_findings(args.limit)
    print(f"\n=== Update findings (most recent {len(updates)}) ===")
    for u in updates:
        print(f"[{u['last_seen']}] {u['name']} ({u['type']}) -> {u['version']} "
              f"first seen {u['first_seen']}")


if __name__ == "__main__":
    main()
