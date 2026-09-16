from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from models.schemas import InterviewPlanRequest
from routers import interviews


class FakeClient:
    response: httpx.Response
    payload: dict | None = None

    def __init__(self, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        pass

    async def post(self, url: str, *, json: dict, headers=None):
        self.__class__.payload = json
        return self.__class__.response


def _response(content: str) -> httpx.Response:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return httpx.Response(
        200,
        request=request,
        json={"choices": [{"message": {"content": content}}]},
    )


@pytest.mark.asyncio
async def test_openai_planning_uses_strict_schema(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_SERVICE_URL", "https://api.openai.com/v1")
    monkeypatch.setattr(interviews.httpx, "AsyncClient", FakeClient)
    FakeClient.response = _response(
        json.dumps(
            {
                "phases": [
                    {
                        "name": "Technical",
                        "duration_minutes": 10,
                        "topics": ["Python"],
                        "source": "jd",
                    }
                ]
            }
        )
    )

    outline = await interviews.create_interview_plan(
        InterviewPlanRequest(job_description="Engineer", resume_text="Python")
    )

    response_format = FakeClient.payload["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert outline.phases[0].name == "Technical"


@pytest.mark.asyncio
async def test_malformed_planning_response_becomes_502(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setattr(interviews.httpx, "AsyncClient", FakeClient)
    FakeClient.response = _response("not-json")

    with pytest.raises(HTTPException) as invalid:
        await interviews.create_interview_plan(
            InterviewPlanRequest(job_description="Engineer", resume_text="Python")
        )
    assert invalid.value.status_code == 502
