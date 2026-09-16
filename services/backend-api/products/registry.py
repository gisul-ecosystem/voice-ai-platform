"""Map public product IDs to private worker and provider configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProductProfile:
    product_id: str
    agent_name: str
    provider_env_prefix: str

    @property
    def provider_policy_id(self) -> str:
        return (
            os.getenv(f"{self.provider_env_prefix}_PROVIDER_POLICY")
            or f"{self.product_id}-default"
        ).strip()

    def provider_selection(self) -> dict[str, str]:
        selected: dict[str, str] = {}
        for modality in ("llm", "stt", "tts"):
            value = (
                os.getenv(f"{self.provider_env_prefix}_{modality.upper()}_PROVIDER")
                or ""
            ).strip()
            if value:
                selected[f"{modality}_provider"] = value
        return selected


_PRODUCTS = {
    "interviewer": ProductProfile(
        product_id="interviewer",
        agent_name="aaptor",
        provider_env_prefix="INTERVIEWER",
    ),
    "customer-support": ProductProfile(
        product_id="customer-support",
        agent_name="racko",
        provider_env_prefix="CUSTOMER_SUPPORT",
    ),
}
_BY_AGENT = {profile.agent_name: profile for profile in _PRODUCTS.values()}


def resolve_product(
    product_id: str | None,
    agent_name: str | None,
) -> ProductProfile:
    """Resolve new product IDs while retaining legacy worker-name callers."""
    requested_product = (product_id or "").strip().lower() or None
    requested_agent = (agent_name or "").strip().lower() or None

    if requested_product:
        profile = _PRODUCTS.get(requested_product)
        if profile is None:
            raise ValueError(f"Unknown product_id {requested_product!r}")
        if requested_agent and requested_agent != profile.agent_name:
            raise ValueError(
                f"product_id {requested_product!r} does not use agent "
                f"{requested_agent!r}"
            )
        return profile

    if requested_agent:
        profile = _BY_AGENT.get(requested_agent)
        if profile is None:
            raise ValueError(f"Unknown agent_name {requested_agent!r}")
        return profile

    return _PRODUCTS["interviewer"]
