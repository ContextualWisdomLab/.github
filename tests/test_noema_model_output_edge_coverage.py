import pytest
from scripts.ci.noema_review_gate import _noema_verdict_json_schema, _noema_verdict_response_format

def test_noema_verdict_json_schema():
    schema = _noema_verdict_json_schema(3)
    assert schema["type"] == "object"
    assert schema["properties"]["adversarial_validation"]["properties"]["probes"]["minItems"] == 3

def test_noema_verdict_response_format():
    format_dict = _noema_verdict_response_format(3)
    assert format_dict["type"] == "json_schema"
    assert format_dict["json_schema"]["schema"]["properties"]["adversarial_validation"]["properties"]["probes"]["minItems"] == 3
