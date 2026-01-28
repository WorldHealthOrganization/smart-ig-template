#!/usr/bin/env python3
"""
Post-Check Script: Add StructureDefinition dates from structuredefinitions.json to index page

This script reads temp/pages/_data/structuredefinitions.json, extracts all
StructureDefinition names and dates, and adds them to the output/index.html page.

This runs after Jekyll builds the final output.

Usage:
    python 00_add_resource_date_to_index.py [ig_root_path]
"""

import sys
import json
import re
from pathlib import Path


def get_structuredefinitions(ig_root: Path) -> list:
    """Read all StructureDefinitions from structuredefinitions.json."""

    sd_json_path = ig_root / "temp" / "pages" / "_data" / "structuredefinitions.json"

    if not sd_json_path.exists():
        print(f"Warning: structuredefinitions.json not found at {sd_json_path}")
        return []

    print(f"Reading structuredefinitions.json from: {sd_json_path}")

    with open(sd_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # The structure is: {"ResourceName": {"name": "...", "date": "...", ...}, ...}
    resources = []
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                name = value.get('name', key)
                date = value.get('date', 'N/A')
                resources.append({'name': name, 'date': date})

    print(f"Found {len(resources)} StructureDefinitions")
    return resources



def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        ig_root = Path(sys.argv[1])
    else:
        ig_root = Path(".")

    print(f"Post-Check: Adding StructureDefinition dates to index page")
    print(f"IG root directory: {ig_root.absolute()}")




if __name__ == "__main__":
    main()
