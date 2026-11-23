"""Stream existing JSONL records without importing hardware or model APIs."""
import argparse
import json
from pathlib import Path
def records(path):
    with Path(path).open(encoding="utf-8-sig") as source:
        for line in source:
            if line.strip(): yield json.loads(line)
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    args = parser.parse_args()
    for record in records(args.jsonl): print(json.dumps(record, ensure_ascii=False))
if __name__ == "__main__": main()
