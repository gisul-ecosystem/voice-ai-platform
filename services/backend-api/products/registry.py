"""Map public product IDs to private worker and provider configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_agent_name(*keys: str, default: str) -> str:
    for key in keys:
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    return default


@dataclass(frozen=True)
class ProductProfile:
    product_id: str
    default_agent_name: str
    provider_env_prefix: str

    @property
    def agent_name(self) -> str:
        """Worker name LiveKit dispatches to (overridable per environment)."""
        if self.product_id == "interviewer":
            return _env_agent_name(
                "LIVEKIT_AGENT_NAME",
                "INTERVIEWER_AGENT_NAME",
                default=self.default_agent_name,
            )
        if self.product_id == "customer-support":
            return _env_agent_name(
                "RACKO_AGENT_NAME",
                "CUSTOMER_SUPPORT_AGENT_NAME",
                default=self.default_agent_name,
            )
        return self.default_agent_name

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
        default_agent_name="aaptor",
        provider_env_prefix="INTERVIEWER",
    ),
    "customer-support": ProductProfile(
        product_id="customer-support",
        default_agent_name="racko",
        provider_env_prefix="CUSTOMER_SUPPORT",
    ),
}


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
        # Allow legacy agent_name=aaptor even when env overrides worker to
        # aaptor-staging (product_id remains the source of truth).
        if (
            requested_agent
            and requested_agent != profile.agent_name
            and requested_agent != profile.default_agent_name
        ):
            raise ValueError(
                f"product_id {requested_product!r} does not use agent "
                f"{requested_agent!r}"
            )
        return profile

    if requested_agent:
        for profile in _PRODUCTS.values():
            if (
                requested_agent == profile.agent_name
                or requested_agent == profile.default_agent_name
            ):
                return profile
        raise ValueError(f"Unknown agent_name {requested_agent!r}")

    return _PRODUCTS["interviewer"]
