from __future__ import annotations

import copy
import json

import pytest

from tbench.constants import REPOSITORY_ROOT
from tbench.schema_contract import SchemaContractError, validate_native_tool_schemas

_EXPECTED = REPOSITORY_ROOT / "configs" / "native-tool-schemas.json"


def _schemas() -> list[dict]:
    return json.loads(_EXPECTED.read_text())["schemas"]


def test_frozen_native_tool_schemas_have_complete_per_tool_hashes() -> None:
    hashes = validate_native_tool_schemas(_schemas(), _EXPECTED)

    assert set(hashes) == {"bash", "read", "edit", "write"}
    assert all(len(digest) == 64 for digest in hashes.values())


@pytest.mark.parametrize("schema_index", range(4))
def test_mutation_to_each_complete_native_schema_is_rejected(schema_index: int) -> None:
    schemas = copy.deepcopy(_schemas())
    schemas[schema_index]["description"] += " mutated"

    with pytest.raises(SchemaContractError, match="frozen complete contract"):
        validate_native_tool_schemas(schemas, _EXPECTED)
