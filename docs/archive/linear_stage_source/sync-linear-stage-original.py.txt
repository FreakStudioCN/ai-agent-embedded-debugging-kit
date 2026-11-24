"""Record the pinned submodule and sync only kit integration assets."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'drivers/micropython/linear_stage'
FILES = {
    'tb6600.py': 'drivers/micropython/linear_stage/tb6600.py',
    'linear_stage_inputs.py': 'drivers/micropython/linear_stage/linear_stage_inputs.py',
    'firmware/linear_stage/bringup.py': 'firmware/linear_stage/bringup.py',
    'examples/exercise.py': 'examples/linear_stage/exercise.py',
    'docs/inputs.md': 'hardware/linear_stage/sensor-inputs.md',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', default=str(SOURCE),
                        help='initialized drivers/micropython/linear_stage submodule')
    args = parser.parse_args()
    source = Path(args.source).resolve()
    if source != SOURCE.resolve():
        parser.error('update the submodule first; sibling source-copy sync is retired')
    if not (source / '.git').exists():
        parser.error('run git submodule update --init --recursive first')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True)
    if dirty.strip():
        parser.error('commit and push submodule source changes before syncing')
    payloads = {name: subprocess.check_output(['git', 'show', commit + ':' + name], cwd=source) for name in FILES}
    records = []
    for name, data in payloads.items():
        target = ROOT / FILES[name]
        if target.resolve() != (source / name).resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        records.append({'source': name, 'target': FILES[name],
                        'sha256': hashlib.sha256(data).hexdigest()})
    manifest = {
        'source_repository': 'https://github.com/FreakStudioCN/micropython-linear-stage.git',
        'source_commit': commit,
        'submodule_path': 'drivers/micropython/linear_stage',
        'hash_normalization': 'LF text bytes from pinned Git blobs',
        'files': records,
        'note': 'Driver sources live only in the pinned submodule; kit board/example/docs assets are synchronized.'}
    (ROOT / 'hardware/linear_stage/source-lock.json').write_text(
        json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Recorded submodule', commit, 'and synchronized 3 integration assets')


if __name__ == '__main__':
    main()
