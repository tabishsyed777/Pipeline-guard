import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from .core import InputError, analyze, apply_plan, fingerprint, propose, read_csv, validate_contract, write_csv
from .evaluation import verify
from .report import write_report


def load_json(file):
    # JSON's NaN/Infinity extensions are not part of the supported input format.
    def invalid(value):
        raise InputError(f'Non-finite JSON constant: {value}')
    return json.loads(Path(file).read_text(encoding='utf-8'), parse_constant=invalid)


def scan(input_file, contract):
    headers, rows = read_csv(input_file)
    result = analyze(headers, rows, contract)
    return headers, rows, result


def public_result(result, **extra):
    return {key: value for key, value in result.items() if key != 'computed_rows'} | extra


def main(argv=None):
    parser = argparse.ArgumentParser(description='PipelineGuard: CSV contracts, bounded repairs, and verification')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'apply', 'verify'):
        command = sub.add_parser(name)
        command.add_argument('--contract', required=True)
        command.add_argument('--out', required=True, help='New report directory; existing paths are never overwritten')
        if name in ('inspect', 'apply'):
            command.add_argument('--input', required=True)
        if name in ('apply', 'verify'):
            command.add_argument('--plan', required=True)
        if name == 'verify':
            command.add_argument('--cases', required=True)
    args = parser.parse_args(argv)
    try:
        contract = validate_contract(load_json(args.contract))
        out = Path(args.out)
        if out.exists():
            raise InputError('Output directory already exists; choose a new path')
        if args.command == 'inspect':
            headers, rows, result = scan(args.input, contract)
            plan = propose(headers, rows, contract)
            report = public_result(result, title='CSV contract inspection', plan=plan,
                                   input_sha256=hashlib.sha256(Path(args.input).read_bytes()).hexdigest(), contract_sha256=fingerprint(contract))
            write_report(out, report)
            (out / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
        elif args.command == 'apply':
            headers, rows = read_csv(args.input)
            plan = load_json(args.plan)
            headers, rows = apply_plan(headers, rows, contract, plan)
            result = analyze(headers, rows, contract)
            report = public_result(result, title='Repair candidate validation', plan_sha256=fingerprint(plan),
                                   input_sha256=hashlib.sha256(Path(args.input).read_bytes()).hexdigest(), contract_sha256=fingerprint(contract),
                                   output_written=result['status'] == 'passed')
            write_report(out, report)
            if result['status'] == 'passed':
                output_headers = headers + [t['output'] for t in contract.get('transforms', [])]
                write_csv(out / 'repaired.csv', output_headers, result['computed_rows'])
        else:
            report = verify(contract, load_json(args.plan), load_json(args.cases))
            write_report(out, report)
        print(f"{report['status']}: {out / 'report.html'}")
        return 0 if report['status'] == 'passed' else 1
    except (InputError, OSError, ValueError, csv.Error) as error:
        print(f'Input/setup error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
