"""Keep late-sorting models available to the shared UI catalogue boundary."""
from __future__ import annotations

import pytest

from AI.processors import pipeline
from AI.views import actions


GLM_MODEL_ID = "z-ai/glm-5.3-flash"


class CatalogResponse:
    status_code = 200
    reason = "OK"
    url = "https://openrouter.ai/api/v1/models"

    def __init__(self, rows):
        self.rows = rows

    def json(self):
        return {"data": self.rows}

    def raise_for_status(self):
        return None


@pytest.fixture
def catalog(monkeypatch):
    # Exceed both historical picker slices (120/200) and the domain's hidden
    # 500-row ceiling, using isolated provider metadata without inference calls.
    rows = [
        {
            "id": f"synthetic/model-{index:04}",
            "name": f"Synthetic {index}",
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "supported_parameters": ["tools"],
        }
        for index in range(620)
    ]
    rows += [
        {
            "id": GLM_MODEL_ID,
            "name": "GLM 5.3 Flash",
            "pricing": {"prompt": "0.0000000052", "completion": "0.0000001985"},
            "supported_parameters": ["tools", "reasoning", "reasoning_effort"],
            "context_length": 200_000,
            "top_provider": {"max_completion_tokens": 64_000},
        },
        {
            "id": "minimax/minimax-m3.1-flash:free",
            "name": "Synthetic free tool model",
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["tools"],
        },
    ]
    monkeypatch.setattr(pipeline.requests, "get", lambda *args, **kwargs: CatalogResponse(rows))
    return rows


@pytest.mark.parametrize("loader", [pipeline.list_provider_models, actions.action_list_provider_models])
def test_complete_catalogue_includes_late_sorting_paid_model_and_metadata(catalog, loader):
    result = loader(provider_code="openrouter", free_only=False, limit=None)

    assert result.success, result.message
    data = result.data
    assert len(data["records"]) == data["total"] == data["returned_count"] == len(catalog)
    assert data["truncated"] is False
    assert data["free_total"] == 1
    model = data["records"][-1]
    assert model["id"] == GLM_MODEL_ID
    assert model["is_free"] is False
    assert "tools" in model["supported_parameters"]
    assert model["output_token_limit"] == 64_000
    assert model["pricing"] == catalog[-2]["pricing"]
    assert len(data["free_model_test_route"]["models"]) == len(catalog)


def test_omitting_limit_returns_complete_catalogue(catalog):
    result = pipeline.list_provider_models(provider_code="openrouter")

    assert result.success, result.message
    assert result.data["records"][-1]["id"] == GLM_MODEL_ID
    assert result.data["returned_count"] == len(catalog)
    assert result.data["truncated"] is False


@pytest.mark.parametrize("limit", [120, 200, 600])
def test_explicit_limit_is_honored_and_truncation_is_reported(catalog, limit):
    result = pipeline.list_provider_models(provider_code="openrouter", limit=limit)

    assert result.success, result.message
    data = result.data
    assert len(data["records"]) == data["returned_count"] == limit
    assert data["total"] == len(catalog)
    assert data["truncated"] is True
    # Truncating display rows must not truncate free-model routing evidence.
    assert len(data["free_model_test_route"]["models"]) == len(catalog)


def test_query_is_applied_to_full_catalogue_before_explicit_limit(catalog):
    result = pipeline.list_provider_models(provider_code="openrouter", query="GLM 5.3 Flash", limit=1)

    assert result.success, result.message
    assert [row["id"] for row in result.data["records"]] == [GLM_MODEL_ID]
    assert result.data["total"] == result.data["returned_count"] == 1
    assert result.data["truncated"] is False


def test_complete_catalogue_keeps_explicit_free_filter(catalog):
    result = pipeline.list_provider_models(provider_code="openrouter", free_only=True)

    assert result.success, result.message
    assert [row["id"] for row in result.data["records"]] == ["minimax/minimax-m3.1-flash:free"]
    assert result.data["total"] == result.data["free_total"] == result.data["returned_count"] == 1
    assert result.data["truncated"] is False
