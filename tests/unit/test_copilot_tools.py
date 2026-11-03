"""M9.1: tool definitions sent to the model."""

import json

from khataiq.copilot.tools import TOOLS


def test_every_tool_schema_is_closed_and_plain():
    for spec in TOOLS.values():
        definition = spec.definition()
        schema = definition["input_schema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        text = json.dumps(schema)
        assert '"title"' not in text and '"default"' not in text
        assert "business" not in text  # the server injects the business; the model can't pick


def test_list_transactions_caps_its_limit():
    props = TOOLS["list_transactions"].definition()["input_schema"]["properties"]
    assert props["limit"]["maximum"] == 50 and "from" in props
