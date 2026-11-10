#!/usr/bin/env python3
"""Every ```iris-show example in skills/iris/SKILL.md validates against Iris's exported
`artifacts.show-spec` JSON Schema; every ```iris-doc example has a valid info string.

The schema lives in the iris repo (``IRIS_SCHEMA`` overrides the default sibling checkout);
without it the schema half is skipped with a message, the structural half still runs.

Run:  ~/.hermes/hermes-agent/venv/bin/python3 tests/test_iris_skill_artifacts.py
"""
import json
import os
import pathlib
import re
import shlex
import sys

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "iris" / "SKILL.md"
SCHEMA = pathlib.Path(
    os.environ.get("IRIS_SCHEMA", os.path.expanduser("~/SourceRoot/iris/contracts/schema/artifacts.show-spec.json"))
)

text = SKILL.read_text()
shows = [m.group(1) for m in re.finditer(r"^```iris-show\n(.*?)\n```$", text, re.M | re.S)]
docs = [(m.group(1), m.group(2)) for m in re.finditer(r"^```iris-doc ([^\n]*)\n(.*?)\n```$", text, re.M | re.S)]
failures = []

types = set()
for body in shows:
    spec = json.loads(body)
    types.add(spec["type"])
    if spec["type"] == "table":
        if any(len(r) != len(spec["columns"]) for r in spec["rows"]):
            failures.append(f"table row length != columns: {body[:60]}")
    if spec["type"] == "chart":
        if any(len(s["values"]) != len(spec["x"]) for s in spec["series"]):
            failures.append(f"chart values != x: {body[:60]}")
        if spec["kind"] == "pie" and len(spec["series"]) != 1:
            failures.append("pie needs exactly one series")
    if SCHEMA.exists():
        try:
            jsonschema.validate(spec, json.loads(SCHEMA.read_text()))
        except jsonschema.ValidationError as e:
            failures.append(f"{spec['type']}: {e.message[:120]}")
    print(f"iris-show {spec['type']}: checked")

for want in ("table", "chart", "stat", "list", "callout"):
    if want not in types:
        failures.append(f"no iris-show example for {want}")
if not SCHEMA.exists():
    print(f"SKIP schema validation: {SCHEMA} not found")

if not docs:
    failures.append("no iris-doc example")
for info, body in docs:
    pairs = dict(p.split("=", 1) for p in shlex.split(info))
    if set(pairs) - {"title", "format"} or pairs.get("format", "markdown") not in ("markdown", "html"):
        failures.append(f"bad iris-doc info: {info}")
    if not body.strip():
        failures.append("empty iris-doc body")
    print(f"iris-doc {pairs}: checked")

if failures:
    print("FAIL\n" + "\n".join(failures))
    sys.exit(1)
print("OK")
