from __future__ import annotations

import pytest

from products.interviewer.worker import (
    InterviewPlanUnavailableError,
    published_plan_required,
    resolve_live_outline,
)


def test_published_plan_required_when_definition_is_bound() -> None:
    assert published_plan_required(definition_id="idef_1", app_env="development") is True
    assert published_plan_required(definition_id=None, app_env="production") is True
    assert published_plan_required(definition_id=None, app_env="staging") is True
    assert published_plan_required(definition_id=None, app_env="development") is False


def test_resolve_live_outline_rejects_generic_fallback_in_production() -> None:
    with pytest.raises(InterviewPlanUnavailableError):
        resolve_live_outline(
            interview_definition=None,
            definition_id=None,
            app_env="production",
        )


@pytest.mark.asyncio
async def test_build_outline_raises_when_published_plan_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from products.interviewer.worker import build_outline

    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(InterviewPlanUnavailableError, match="generated_plan_not_allowed"):
        await build_outline(SimpleNamespace())


def test_local_development_may_use_generated_plan() -> None:
    outline, source = resolve_live_outline(
        interview_definition=None,
        definition_id=None,
        app_env="development",
    )
    assert outline is None
    assert source == "generated_plan"
