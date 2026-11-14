import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from pipelineguard.core import InputError, analyze, apply_plan, propose, read_csv, validate_contract
from pipelineguard.cli import main
from pipelineguard.evaluation import verify
from pipelineguard.report import write_report

ROOT = Path(__file__).resolve().parents[1]


class PipelineGuardTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / 'examples/contract.json').read_text())
        self.headers, self.rows = read_csv(ROOT / 'examples/orders-broken.csv')
        self.plan = propose(self.headers, self.rows, self.contract)

    def test_seeded_schema_and_missing_data_are_detected(self):
        result = analyze(self.headers, self.rows, self.contract)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue({'missing_column', 'unexpected_column', 'missing_value', 'transformation_blocked'} <= {f['code'] for f in result['findings']})

    def test_repair_is_non_mutating_and_financial_arithmetic_is_decimal(self):
        before = copy.deepcopy(self.rows)
        headers, rows = apply_plan(self.headers, self.rows, self.contract, self.plan)
        result = analyze(headers, rows, self.contract)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual([r['revenue'] for r in result['computed_rows']], ['25', '8.75'])
        self.assertEqual(before, self.rows)
        self.assertEqual(self.headers, ['order_id', 'quantity', 'unit_cost'])

    def test_six_separate_replay_cases_pass(self):
        cases = json.loads((ROOT / 'examples/heldout.json').read_text())
        result = verify(self.contract, self.plan, cases)
        self.assertEqual(result['passed_cases'], 6)
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(all(c['passed'] for c in result['cases']))

    def test_verifier_rejects_incorrect_expected_answers(self):
        cases = json.loads((ROOT / 'examples/heldout.json').read_text())
        cases[0]['expected_outputs'][0]['revenue'] = '999'
        self.assertEqual(verify(self.contract, self.plan, cases)['status'], 'failed')

    def test_zero_is_preserved_and_defaults_apply_only_when_missing(self):
        rows = [{'order_id': 'Z1', 'quantity': '0', 'unit_cost': '100'}]
        headers, repaired = apply_plan(self.headers, rows, self.contract, self.plan)
        self.assertEqual(repaired[0]['quantity'], '0')
        self.assertEqual(analyze(headers, repaired, self.contract)['computed_rows'][0]['revenue'], '0')

    def test_healthy_control_has_no_findings(self):
        headers, rows = read_csv(ROOT / 'examples/orders-healthy.csv')
        self.assertEqual(analyze(headers, rows, self.contract)['findings'], [])
        self.assertEqual(propose(headers, rows, self.contract)['operations'], [])

    def test_contract_hash_and_unapproved_operations_are_rejected(self):
        bad = copy.deepcopy(self.plan)
        bad['contract_sha256'] = 'wrong'
        with self.assertRaises(InputError):
            apply_plan(self.headers, self.rows, self.contract, bad)
        bad = copy.deepcopy(self.plan)
        bad['operations'] = [{'op': 'fill_default', 'column': 'unit_price'}]
        with self.assertRaises(InputError):
            apply_plan(self.headers, self.rows, self.contract, bad)
        bad['operations'] = [{'op': 'rename_column', 'source': 'order_id', 'column': 'unit_price'}]
        with self.assertRaises(InputError):
            apply_plan(self.headers, self.rows, self.contract, bad)

    def test_rename_collision_is_rejected(self):
        with self.assertRaises(InputError):
            apply_plan(self.headers + ['unit_price'], [dict(self.rows[0], unit_price='1')], self.contract, self.plan)

    def test_integer_nonfinite_and_duplicate_checks(self):
        for value in ['1.2', 'NaN', 'Infinity', 'bad']:
            rows = [{'order_id': 'N1', 'quantity': value, 'unit_price': '2'}]
            result = analyze(['order_id', 'quantity', 'unit_price'], rows, self.contract)
            self.assertIn('type_error', [f['code'] for f in result['findings']])
        headers, rows = apply_plan(self.headers, [self.rows[0], self.rows[0]], self.contract, self.plan)
        self.assertIn('duplicate_value', [f['code'] for f in analyze(headers, rows, self.contract)['findings']])

    def test_division_failure_and_blocked_chained_transform(self):
        contract = copy.deepcopy(self.contract)
        contract['transforms'][0]['op'] = 'divide'
        contract['transforms'].append({'output': 'double', 'op': 'add', 'left': 'revenue', 'right': 'revenue'})
        result = analyze(['order_id', 'quantity', 'unit_price'], [{'order_id': 'D1', 'quantity': '3', 'unit_price': '0'}], contract)
        self.assertTrue({'transformation_error', 'transformation_blocked'} <= {f['code'] for f in result['findings']})

    def test_rejects_invalid_contracts(self):
        for mutate in [lambda c: c['columns']['quantity'].update(type='python'),
                       lambda c: c['columns']['quantity'].update(default='no'),
                       lambda c: c['columns']['quantity'].update(aliases=['unit_price']),
                       lambda c: c['transforms'][0].update(op='eval'),
                       lambda c: c['transforms'][0].update(right='order_id')]:
            contract = copy.deepcopy(self.contract)
            mutate(contract)
            with self.assertRaises(InputError):
                validate_contract(contract)

    def test_malformed_csvs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'bad.csv'
            for content in ['id,id\na,b\n', 'id,value\na\n', 'id\na,b\n', '']:
                file.write_text(content)
                with self.assertRaises(InputError):
                    read_csv(file)

    def test_empty_dataset_and_reserved_outputs_fail(self):
        self.assertEqual(analyze(self.headers, [], self.contract)['status'], 'failed')
        contract = copy.deepcopy(self.contract)
        contract['allow_extra_columns'] = True
        headers = ['order_id', 'quantity', 'unit_price', 'revenue']
        rows = [dict(zip(headers, ['O1', '2', '3', '999']))]
        self.assertIn('reserved_output_column', [f['code'] for f in analyze(headers, rows, contract)['findings']])

    def test_cli_evidence_excludes_raw_rows_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = ROOT / 'examples/orders-broken.csv'
            original = source.read_bytes()
            common = ['--contract', str(ROOT / 'examples/contract.json')]
            out = root / 'inspect'
            self.assertEqual(main(['inspect', *common, '--input', str(source), '--out', str(out)]), 1)
            report = json.loads((out / 'report.json').read_text())
            self.assertNotIn('computed_rows', report)
            self.assertNotIn('A-101', (out / 'report.json').read_text())
            self.assertEqual(main(['inspect', *common, '--input', str(source), '--out', str(out)]), 2)
            repaired = root / 'repair'
            self.assertEqual(main(['apply', *common, '--input', str(source), '--plan', str(out / 'plan.json'), '--out', str(repaired)]), 0)
            with (repaired / 'repaired.csv').open() as stream:
                self.assertEqual([r['revenue'] for r in csv.DictReader(stream)], ['25', '8.75'])
            self.assertEqual(original, source.read_bytes())

    def test_failed_repair_does_not_write_output_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.csv'
            source.write_text('order_id,quantity,unit_cost\nU1,two,3\n')
            plan_file = root / 'plan.json'
            plan_file.write_text(json.dumps(self.plan))
            out = root / 'out'
            self.assertEqual(main(['apply', '--input', str(source), '--contract', str(ROOT / 'examples/contract.json'), '--plan', str(plan_file), '--out', str(out)]), 1)
            self.assertFalse((out / 'repaired.csv').exists())

    def test_html_escapes_untrusted_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'report'
            write_report(out, {'title': '<script>alert(1)</script>', 'status': 'failed', 'findings': []})
            rendered = (out / 'report.html').read_text()
            self.assertNotIn('<script>', rendered)
            self.assertIn('&lt;script&gt;', rendered)


if __name__ == '__main__':
    unittest.main()
