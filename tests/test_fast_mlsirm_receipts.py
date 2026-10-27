"""Synthetic envelope validation, never native GPU provenance."""
import copy
import hashlib
import json
from xml.etree import ElementTree as ET

import pytest
from scripts.ci import fast_mlsirm_receipts as r

CASES = (
    "tests/test_bifactor_bootstrap_benchmark.py::test_joint_bootstrap_cpu_vs_gpu_wall_time_and_parity",
    "tests/test_bifactor_gpu.py::test_bifactor_gpu_equivalence_multigroup",
    "tests/test_bifactor_bootstrap_benchmark.py::test_joint_bootstrap_cpu_vs_gpu_wall_time_q121",
)


def fixture():
    binding = dict(source_sha="a" * 40, extension_sha256="b" * 64,
                   supplier_sha="c" * 40, run_id="123", attempt=1,
                   job="hardware-tests", lease="d" * 32)
    calls = [dict(nodeid=node, call_id=str(i + 1) * 32, outcome="passed",
                  **binding) for i, node in enumerate(CASES)]
    envelope = dict(schema="local-exact3-v1", scope="synthetic-local-only",
                    binding=binding, calls=calls)
    suite = ET.Element("testsuite", tests="3", failures="0", errors="0", skipped="0")
    properties = ET.SubElement(suite, "properties")
    for key, value in binding.items():
        ET.SubElement(properties, "property", name=key, value=str(value))
    for call in calls:
        file, name = call["nodeid"].split("::")
        case = ET.SubElement(suite, "testcase", classname=file[:-3].replace("/", "."), name=name)
        props = ET.SubElement(case, "properties")
        for key in ("nodeid", "call_id"):
            ET.SubElement(props, "property", name=key, value=call[key])
    xml = ET.tostring(suite)
    envelope["junit_sha256"] = hashlib.sha256(xml).hexdigest()
    return binding, envelope, xml


def test_exact_three_valid_join_is_not_unconditional_hold():
    binding, envelope, xml = fixture()
    result = r.validate(json.dumps(envelope).encode(), xml, binding)
    assert result == CASES


@pytest.mark.parametrize("change", ["missing", "duplicate", "extra", "skipped", "failed", "wrong-source", "wrong-run", "wrong-attempt", "call-id", "junit-call", "junit-source", "junit-run", "junit-duplicate", "junit-extra", "junit-skipped", "junit-failed"])
def test_mismatched_receipts_reject(change):
    binding, data, xml = fixture()
    tree = ET.fromstring(xml)
    if change == "missing": data["calls"].pop()
    if change == "duplicate": data["calls"][1] = copy.deepcopy(data["calls"][0])
    if change == "extra": data["calls"].append(copy.deepcopy(data["calls"][0]))
    if change in ("skipped", "failed"): data["calls"][0]["outcome"] = change
    if change == "wrong-source": data["calls"][0]["source_sha"] = "f" * 40
    if change == "wrong-run": data["calls"][0]["run_id"] = "999"
    if change == "wrong-attempt": data["calls"][0]["attempt"] = True
    if change == "call-id": data["calls"][1]["call_id"] = data["calls"][0]["call_id"]
    if change == "junit-call": tree.find("testcase/properties/property[@name='call_id']").set("value", "f" * 32)
    if change == "junit-source": tree.find("properties/property[@name='source_sha']").set("value", "f" * 40)
    if change == "junit-run": tree.find("properties/property[@name='run_id']").set("value", "999")
    if change == "junit-duplicate": tree.remove(tree.findall("testcase")[1]); tree.append(copy.deepcopy(tree.find("testcase")))
    if change == "junit-extra": tree.append(copy.deepcopy(tree.find("testcase")))
    if change == "junit-skipped": ET.SubElement(tree.find("testcase"), "skipped")
    if change == "junit-failed": ET.SubElement(tree.find("testcase"), "failure")
    xml = ET.tostring(tree)
    data["junit_sha256"] = hashlib.sha256(xml).hexdigest()
    with pytest.raises(ValueError):
        r.validate(json.dumps(data).encode(), xml, binding)


@pytest.mark.parametrize("target", ["source_sha", "extension_sha256", "supplier_sha", "run_id", "attempt", "job", "lease"])
def test_wholly_consistent_wrong_expectation_rejects(target):
    binding, data, xml = fixture()
    # Even a consistent report cannot choose the trusted caller's expectation.
    expected = dict(binding)
    expected[target] = 2 if target == "attempt" else ("9" * len(binding[target]))
    with pytest.raises(ValueError):
        r.validate(json.dumps(data).encode(), xml, expected)


@pytest.mark.parametrize("attack", ["utf16", "missing-name", "list-node", "depth", "duplicate-json", "nan", "empty"])
def test_malformed_inputs_have_bounded_handled_rejection(attack):
    binding, data, xml = fixture()
    if attack == "utf16": xml = ET.tostring(ET.fromstring(xml), encoding="utf-16")
    if attack == "missing-name":
        tree = ET.fromstring(xml)
        del tree.find("testcase").attrib["name"]
        xml = ET.tostring(tree)
    if attack == "list-node": data["calls"][0]["nodeid"] = []
    data["junit_sha256"] = hashlib.sha256(xml).hexdigest()
    receipt = json.dumps(data).encode()
    if attack == "depth": receipt = b"[" * 1100 + b"0" + b"]" * 1100
    if attack == "duplicate-json": receipt = receipt.replace(b'"schema":', b'"schema":"bad","schema":', 1)
    if attack == "nan": receipt = receipt.replace(b'"attempt": 1', b'"attempt": NaN', 1)
    if attack == "empty": receipt = b""
    with pytest.raises(ValueError):
        r.validate(receipt, xml, binding)


def test_nested_junit_property_content_is_not_valid_schema():
    binding, data, xml = fixture()
    tree = ET.fromstring(xml)
    ET.SubElement(tree.find("testcase/properties/property"), "skipped")
    xml = ET.tostring(tree)
    data["junit_sha256"] = hashlib.sha256(xml).hexdigest()
    with pytest.raises(ValueError):
        r.validate(json.dumps(data).encode(), xml, binding)
