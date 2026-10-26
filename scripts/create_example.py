"""Create a new synthetic project, without launching a server or renderer."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project', type=Path, required=True)
args = parser.parse_args()
project = args.project.expanduser().resolve()
if project.exists():
    parser.error('Choose a new project directory; existing projects are preserved.')
source = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(source / 'scripts/launch_storyboard.py'),
                '--project', str(project), '--title', 'Synthetic product film',
                '--duration', '12', '--init-only'], check=True, stdout=subprocess.DEVNULL)
example = json.loads((source / 'examples/Synthetic_Product_Film.json').read_text())
(project / 'data/board.json').write_text(json.dumps(example, indent=2) + '\n')
print(json.dumps({'project': str(project), 'synthetic_example': True, 'renderer_started': False}))
