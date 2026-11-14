"""Integration coverage through real CLI processes, files, and exit statuses."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CLIIntegrationTests(unittest.TestCase):
    def cli(self, *arguments):
        return subprocess.run(
            [sys.executable, '-m', 'pipelineguard', *map(str, arguments)],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )

    def test_inspect_apply_verify_and_healthy_control(self):
        contract = ROOT / 'examples/contract.json'
        source = ROOT / 'examples/orders-broken.csv'
        original = source.read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inspected = root / 'inspection'
            result = self.cli('inspect', '--contract', contract, '--input', source, '--out', inspected)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertTrue((inspected / 'report.html').is_file())
            plan = inspected / 'plan.json'
            self.assertEqual(len(json.loads(plan.read_text())['operations']), 2)

            repaired = root / 'repair'
            result = self.cli('apply', '--contract', contract, '--input', source, '--plan', plan, '--out', repaired)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with (repaired / 'repaired.csv').open(newline='') as stream:
                self.assertEqual([row['revenue'] for row in csv.DictReader(stream)], ['25', '8.75'])

            verified = root / 'verification'
            result = self.cli('verify', '--contract', contract, '--plan', plan,
                              '--cases', ROOT / 'examples/heldout.json', '--out', verified)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads((verified / 'report.json').read_text())['passed_cases'], 6)

            healthy = root / 'healthy'
            result = self.cli('inspect', '--contract', contract, '--input', ROOT / 'examples/orders-healthy.csv', '--out', healthy)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads((healthy / 'report.json').read_text())['findings'], [])

            before = (healthy / 'report.json').read_bytes()
            result = self.cli('inspect', '--contract', contract, '--input', source, '--out', healthy)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual((healthy / 'report.json').read_bytes(), before)
        self.assertEqual(source.read_bytes(), original)

    def test_rejected_data_and_tampered_plan_never_export_csv(self):
        contract = ROOT / 'examples/contract.json'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inspected = root / 'inspection'
            result = self.cli('inspect', '--contract', contract, '--input', ROOT / 'examples/orders-broken.csv', '--out', inspected)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            source = root / 'invalid.csv'
            source.write_text('order_id,quantity,unit_cost\nI-1,two,4\n')
            rejected = root / 'rejected'
            result = self.cli('apply', '--contract', contract, '--input', source,
                              '--plan', inspected / 'plan.json', '--out', rejected)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertFalse((rejected / 'repaired.csv').exists())
            self.assertFalse(json.loads((rejected / 'report.json').read_text())['output_written'])

            plan = json.loads((inspected / 'plan.json').read_text())
            plan['contract_sha256'] = 'tampered'
            tampered = root / 'tampered.json'
            tampered.write_text(json.dumps(plan))
            out = root / 'tampered-output'
            result = self.cli('apply', '--contract', contract, '--input', source, '--plan', tampered, '--out', out)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertFalse(out.exists())
