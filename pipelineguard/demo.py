"""Run the synthetic demo, selecting the plan before reading held-out answers."""
import argparse
import json
from pathlib import Path
from .cli import main


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='runs/demo', help='New output directory')
    args = parser.parse_args()
    root = Path(args.out)
    if root.exists():
        parser.error('Output path already exists; choose a new --out path')
    examples = Path(__file__).resolve().parents[1] / 'examples'
    if not examples.exists():
        parser.error('Run this source-checkout demo from the repository; examples are not included in the wheel')
    contract = str(examples / 'contract.json')
    def step(command, *extra, directory):
        return main([command, '--contract', contract, '--out', str(root / directory), *map(str, extra)])
    broken = step('inspect', '--input', examples / 'orders-broken.csv', directory='inspection')
    plan = root / 'inspection' / 'plan.json'
    repaired = step('apply', '--input', examples / 'orders-broken.csv', '--plan', plan, directory='repair')
    heldout = step('verify', '--plan', plan, '--cases', examples / 'heldout.json', directory='verification')
    healthy = step('inspect', '--input', examples / 'orders-healthy.csv', directory='healthy')
    summary = {'seeded_issues': 2, 'inspection_failed_as_expected': broken == 1,
               'repair_passed': repaired == 0, 'heldout_verification_passed': heldout == 0,
               'healthy_control_passed': healthy == 0, 'model_calls': 0,
               'scope': 'Synthetic CSV fixtures; six authored replay cases, not a general accuracy estimate.'}
    root.mkdir(parents=True, exist_ok=True)
    (root / 'evaluation.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if all([broken == 1, repaired == 0, heldout == 0, healthy == 0]) else 1


if __name__ == '__main__':
    raise SystemExit(run())
