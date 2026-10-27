"""Strict local exact3 call/JUnit join, not a native GPU provenance producer.

A structurally valid synthetic envelope can pass here; native activation must
add an independent authenticated producer and actual numerical dispatch trace.
"""
import hashlib
import json
import re
from xml.etree import ElementTree as ET

CASES = (
    "tests/test_bifactor_bootstrap_benchmark.py::test_joint_bootstrap_cpu_vs_gpu_wall_time_and_parity",
    "tests/test_bifactor_gpu.py::test_bifactor_gpu_equivalence_multigroup",
    "tests/test_bifactor_bootstrap_benchmark.py::test_joint_bootstrap_cpu_vs_gpu_wall_time_q121",
)
BINDING = frozenset(("source_sha", "extension_sha256", "supplier_sha", "run_id",
                     "attempt", "job", "lease"))
CALL = BINDING | {"nodeid", "call_id", "outcome"}


def _object(pairs):
    """Reject duplicate JSON keys before any equality check can hide them."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _properties(element):
    """Read exactly one closed JUnit property group with unique names."""
    groups = element.findall("properties")
    if len(groups) != 1 or any(child.tag != "property" for child in groups[0]):
        raise ValueError("JUnit property group invalid")
    result = {}
    for prop in groups[0]:
        if len(prop) or set(prop.attrib) != {"name", "value"} or prop.get("name") in result:
            raise ValueError("JUnit property invalid")
        result[prop.get("name")] = prop.get("value")
    return result


def _binding(binding):
    """Validate immutable identities without coercion or environment claims."""
    if type(binding) is not dict or set(binding) != BINDING:
        raise ValueError("binding shape invalid")
    for key in ("source_sha", "supplier_sha"):
        if type(binding[key]) is not str or not re.fullmatch(r"[0-9a-f]{40}", binding[key]):
            raise ValueError("source identity invalid")
    if type(binding["extension_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", binding["extension_sha256"]):
        raise ValueError("extension identity invalid")
    if type(binding["run_id"]) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", binding["run_id"]):
        raise ValueError("run identity invalid")
    if type(binding["attempt"]) is not int or binding["attempt"] < 1:
        raise ValueError("attempt invalid")
    if type(binding["job"]) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", binding["job"]):
        raise ValueError("job invalid")
    if type(binding["lease"]) is not str or not re.fullmatch(r"[0-9a-f]{32}", binding["lease"]):
        raise ValueError("lease identity invalid")


def validate(receipt, junit, expected):
    """Reject empty, extra, duplicate, nonpassed or wrong-source/run exact3.

    `expected` must come from the trusted caller, never the submitted envelope.
    This is an offline structural join, not proof of GPU execution or a CI gate.
    """
    if type(receipt) is not bytes or len(receipt) > 65536 or type(junit) is not bytes or len(junit) > 65536:
        raise ValueError("bounded byte inputs required")
    _binding(expected)
    try:
        data = json.loads(receipt.decode("utf-8"), object_pairs_hook=_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (RecursionError, UnicodeError) as error:
        raise ValueError("invalid bounded JSON") from error
    if type(data) is not dict or set(data) != {"schema", "scope", "binding", "calls", "junit_sha256"}:
        raise ValueError("receipt shape invalid")
    if data["schema"] != "local-exact3-v1" or data["scope"] != "synthetic-local-only":
        raise ValueError("receipt scope invalid")
    _binding(data["binding"])
    if any(type(data["binding"][key]) is not type(expected[key]) or data["binding"][key] != expected[key] for key in BINDING):
        raise ValueError("receipt binding does not match trusted expectation")
    if type(data["junit_sha256"]) is not str or data["junit_sha256"] != hashlib.sha256(junit).hexdigest():
        raise ValueError("JUnit bytes mismatch")
    calls = data["calls"]
    if type(calls) is not list or len(calls) != 3:
        raise ValueError("exactly three calls required")
    seen = set()
    by_node = {}
    for call in calls:
        if type(call) is not dict or set(call) != CALL:
            raise ValueError("call shape invalid")
        if call["nodeid"] not in CASES or call["nodeid"] in seen:
            raise ValueError("missing, duplicate or extra call")
        seen.add(call["nodeid"])
        if call["outcome"] != "passed" or type(call["outcome"]) is not str:
            raise ValueError("call not passed")
        if type(call["call_id"]) is not str or not re.fullmatch(r"[0-9a-f]{32}", call["call_id"]):
            raise ValueError("call identity invalid")
        for key in BINDING:
            if type(call[key]) is not type(expected[key]) or call[key] != expected[key]:
                raise ValueError("call binding mismatch")
        by_node[call["nodeid"]] = call["call_id"]
    if seen != set(CASES) or len(set(by_node.values())) != 3:
        raise ValueError("exact unique case/call identity required")
    try:
        text = junit.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("JUnit must be UTF-8") from error
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("DTD/non-UTF8 XML forbidden")
    try:
        suite = ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError("invalid JUnit XML") from error
    if suite.tag != "testsuite" or set(suite.attrib) != {"tests", "failures", "errors", "skipped"} or suite.attrib != {"tests": "3", "failures": "0", "errors": "0", "skipped": "0"}:
        raise ValueError("JUnit aggregate invalid")
    if set(_properties(suite)) != BINDING or _properties(suite) != {key: str(value) for key, value in expected.items()}:
        raise ValueError("JUnit binding invalid")
    tests = suite.findall("testcase")
    if len(tests) != 3 or len(list(suite)) != 4:
        raise ValueError("JUnit case count invalid")
    observed = set()
    for test in tests:
        if set(test.attrib) != {"classname", "name"} or len(list(test)) != 1:
            raise ValueError("JUnit test outcome invalid")
        node = next((n for n in CASES if n.endswith("::" + test.get("name")) and
                     n.split("::")[0][:-3].replace("/", ".") == test.get("classname")), None)
        if node is None or node in observed or _properties(test) != {"nodeid": node, "call_id": by_node[node]}:
            raise ValueError("JUnit exact case/call mismatch")
        observed.add(node)
    if observed != set(CASES):
        raise ValueError("JUnit exact3 incomplete")
    return CASES
