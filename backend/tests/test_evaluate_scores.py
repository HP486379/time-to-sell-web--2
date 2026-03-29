import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import PositionRequest, app
from tests.fixtures.mock_payload_overrides import apply_overrides
from tests.utils.mock_request import generate_mock_request_from_openapi


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture()
def mock_request():
    openapi = app.openapi()
    payload = generate_mock_request_from_openapi(openapi, path="/evaluate", method="post")
    return apply_overrides(payload)


def test_mock_request_matches_position_request_schema(mock_request):
    parsed = PositionRequest(**mock_request)

    assert isinstance(parsed.total_quantity, float)
    assert isinstance(parsed.avg_cost, float)
    assert parsed.index_type is not None


def test_openapi_has_evaluate_path_and_json_body(client):
    openapi = app.openapi()
    paths = openapi["paths"]
    assert "/api/evaluate" in paths
    assert "post" in paths["/api/evaluate"]
    content = paths["/api/evaluate"]["post"]["requestBody"]["content"]
    assert "application/json" in content
