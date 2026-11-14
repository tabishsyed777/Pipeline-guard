"""Standard-library CSV validation and declarative transformations. No code execution."""
import csv
import hashlib
import json
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path


class InputError(ValueError):
    """Invalid input or unsupported contract."""


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def number(value, kind):
    try:
        parsed = Decimal(str(value).strip())
        if not parsed.is_finite() or (kind == "integer" and parsed != parsed.to_integral_value()):
            raise ValueError
        return parsed
    except (InvalidOperation, ValueError):
        raise InputError(f"Expected finite {kind}") from None


def validate_contract(contract):
    if not isinstance(contract, dict) or set(contract) - {"name", "columns", "transforms", "allow_extra_columns"}:
        raise InputError("Unsupported contract fields")
    columns = contract.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise InputError("Contract requires columns")
    seen = set(columns)
    if any(not isinstance(k, str) or not k for k in columns):
        raise InputError("Column names must be nonempty strings")
    for name, spec in columns.items():
        if not isinstance(spec, dict) or set(spec) - {"type", "nullable", "unique", "aliases", "default"}:
            raise InputError(f"Unsupported specification for {name}")
        if not isinstance(spec.get("type"), str) or spec["type"] not in {"string", "integer", "decimal"}:
            raise InputError(f"Unsupported type for {name}")
        for flag in ("nullable", "unique"):
            if flag in spec and not isinstance(spec[flag], bool):
                raise InputError(f"{flag} must be boolean")
        aliases = spec.get("aliases", [])
        if not isinstance(aliases, list):
            raise InputError("aliases must be a list")
        for alias in aliases:
            if not isinstance(alias, str) or not alias or alias in seen:
                raise InputError("Aliases must be globally unambiguous")
            seen.add(alias)
        if "default" in spec:
            if not isinstance(spec["default"], str) or (not spec["default"].strip() and not spec.get("nullable", False)):
                raise InputError("Defaults must be valid explicit CSV strings")
            if spec["default"].strip() and spec["type"] != "string":
                number(spec["default"], spec["type"])
    if "allow_extra_columns" in contract and not isinstance(contract["allow_extra_columns"], bool):
        raise InputError("allow_extra_columns must be boolean")
    transforms = contract.get("transforms", [])
    if not isinstance(transforms, list):
        raise InputError("transforms must be a list")
    available = {name for name, spec in columns.items() if spec["type"] != "string"}
    outputs = set(columns)
    for transform in transforms:
        if not isinstance(transform, dict) or set(transform) != {"output", "op", "left", "right"}:
            raise InputError("Transform requires output, op, left, right")
        if not isinstance(transform["op"], str) or transform["op"] not in {"multiply", "divide", "add", "subtract"}:
            raise InputError("Unsupported transform operation")
        if not isinstance(transform["output"], str) or not transform["output"] or transform["output"] in outputs:
            raise InputError("Transform output must be a new name")
        if not isinstance(transform["left"], str) or not isinstance(transform["right"], str) or transform["left"] not in available or transform["right"] not in available:
            raise InputError("Transform inputs must be earlier numeric columns")
        outputs.add(transform["output"])
        available.add(transform["output"])
    return contract


def read_csv(file):
    with Path(file).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames
        if not headers or any(not h for h in headers) or len(headers) != len(set(headers)):
            raise InputError("CSV requires distinct, nonempty column names")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise InputError("CSV row width differs from header")
    return headers, rows


def analyze(headers, rows, contract):
    validate_contract(contract)
    findings = []
    def issue(code, column=None, row=None, detail=None):
        findings.append({"code": code, "column": column, "row": row, "detail": detail})
    for name in contract["columns"]:
        if name not in headers:
            issue("missing_column", name)
    if not contract.get("allow_extra_columns", False):
        for name in headers:
            if name not in contract["columns"]:
                issue("unexpected_column", name)
    for transform in contract.get("transforms", []):
        if transform["output"] in headers:
            issue("reserved_output_column", transform["output"])
    if not rows:
        issue("empty_dataset")
    seen = {name: set() for name, spec in contract["columns"].items() if spec.get("unique")}
    computed = []
    for row_number, row in enumerate(rows, start=2):
        values = {}
        for name, spec in contract["columns"].items():
            if name not in headers:
                continue
            value = row[name]
            if not value.strip():
                if not spec.get("nullable", False):
                    issue("missing_value", name, row_number)
                continue
            if spec["type"] != "string":
                try:
                    values[name] = number(value, spec["type"])
                except InputError:
                    issue("type_error", name, row_number, f"Expected finite {spec['type']}")
                    continue
            else:
                values[name] = value
            if name in seen:
                if values[name] in seen[name]:
                    issue("duplicate_value", name, row_number)
                seen[name].add(values[name])
        result = dict(row)
        with localcontext() as context:
            context.prec = 28
            for transform in contract.get("transforms", []):
                output = transform["output"]
                if transform["left"] not in values or transform["right"] not in values:
                    issue("transformation_blocked", output, row_number, "Required numeric input is unavailable")
                    continue
                left, right = values[transform["left"]], values[transform["right"]]
                try:
                    op = transform["op"]
                    if op == "divide" and right == 0:
                        raise InputError("Division by zero")
                    value = {"multiply": lambda: left * right, "divide": lambda: left / right,
                             "add": lambda: left + right, "subtract": lambda: left - right}[op]()
                    if not value.is_finite():
                        raise InputError("Non-finite result")
                    values[output] = value
                    result[output] = format(value.normalize(), "f")
                except (ArithmeticError, InputError):
                    issue("transformation_error", output, row_number, "Arithmetic operation failed (including division by zero)")
        computed.append(result)
    return {"status": "failed" if findings else "passed", "row_count": len(rows),
            "findings": findings, "computed_rows": computed}


def propose(headers, rows, contract):
    """Use only the current input and declared rules, never expected test answers."""
    validate_contract(contract)
    operations = []
    for name, spec in contract["columns"].items():
        sources = [alias for alias in spec.get("aliases", []) if alias in headers]
        if name not in headers and len(sources) == 1:
            operations.append({"op": "rename_column", "source": sources[0], "column": name})
        # Do not invent columns; defaults fill existing/renamed cells only.
        source = name if name in headers else sources[0] if len(sources) == 1 else None
        if source and "default" in spec and any(not row[source].strip() for row in rows):
            operations.append({"op": "fill_default", "column": name})
    return {"version": 1, "contract_sha256": fingerprint(contract), "operations": operations}


def apply_plan(headers, rows, contract, plan):
    validate_contract(contract)
    if not isinstance(plan, dict) or set(plan) != {"version", "contract_sha256", "operations"} or plan["version"] != 1 or plan["contract_sha256"] != fingerprint(contract):
        raise InputError("Plan does not match this contract")
    if not isinstance(plan["operations"], list):
        raise InputError("Plan operations must be a list")
    headers, rows = list(headers), [dict(row) for row in rows]
    for operation in plan["operations"]:
        if not isinstance(operation, dict) or not isinstance(operation.get("column"), str) or operation["column"] not in contract["columns"]:
            raise InputError("Invalid repair operation")
        name = operation["column"]
        spec = contract["columns"][name]
        if operation.get("op") == "rename_column" and set(operation) == {"op", "source", "column"}:
            source = operation["source"]
            if source not in spec.get("aliases", []):
                raise InputError("Rename is not approved by contract")
            if source in headers and name in headers:
                raise InputError("Rename would overwrite an existing column")
            if source in headers:
                headers[headers.index(source)] = name
                for row in rows:
                    row[name] = row.pop(source)
        elif operation.get("op") == "fill_default" and set(operation) == {"op", "column"} and "default" in spec:
            if name in headers:
                for row in rows:
                    if not row[name].strip():
                        row[name] = spec["default"]
        else:
            raise InputError("Repair is not approved by contract")
    return headers, rows


def write_csv(file, headers, rows):
    # Exclusive creation: input and pre-existing outputs cannot be overwritten.
    with Path(file).open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
