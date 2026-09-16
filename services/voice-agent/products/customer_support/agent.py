"""LiveKit adapter for the provider-neutral customer-support flow."""
from __future__ import annotations

from livekit.agents import Agent, ModelSettings, llm

from clients.backend_client import (
    fetch_account_status,
    fetch_invoice_status,
    fetch_order_status,
)
from clients.context_client import retrieve_context
from products.customer_support.flow import GREETING, SupportFlow
from voice_platform.chat import last_text


class RackoAgent(Agent):
    """Racko's LiveKit surface; support state lives in SupportFlow."""

    def __init__(
        self,
        llm_client,
        *,
        session_id: str = "",
        fetch_account=fetch_account_status,
        fetch_invoice=fetch_invoice_status,
        fetch_order=fetch_order_status,
        retrieve=retrieve_context,
    ) -> None:
        super().__init__(
            instructions=(
                "You are Racko, a voice customer-support agent. One concise spoken "
                "reply at a time. Do not use markdown."
            )
        )
        self.flow = SupportFlow(
            llm_client,
            fetch_account=fetch_account,
            fetch_invoice=fetch_invoice,
            fetch_order=fetch_order,
            retrieve=retrieve,
            session_id=session_id,
        )

    @property
    def llm_client(self):
        return self.flow.llm_client

    @property
    def session_id(self) -> str:
        return self.flow.session_id

    @property
    def unresolved_attempts(self) -> int:
        return self.flow.unresolved_attempts

    @property
    def escalated(self) -> bool:
        return self.flow.escalated

    @property
    def last_account_id(self) -> str | None:
        return self.flow.last_account_id

    @property
    def last_order_id(self) -> str | None:
        return self.flow.last_order_id

    async def _classify(self, user_text: str) -> str:
        return await self.flow.classify(user_text)

    def _entity_id_for_intent(self, intent: str, user_text: str) -> str | None:
        return self.flow.entity_id_for_intent(intent, user_text)

    async def _tool_payload(
        self, intent: str, user_text: str, entity_id: str
    ) -> dict | None:
        return await self.flow.tool_payload(intent, user_text, entity_id)

    async def _kb_snippets(self, user_text: str) -> list[str]:
        return await self.flow.kb_snippets(user_text)

    def _trigger_escalation(self, reason: str, user_text: str) -> str:
        return self.flow.trigger_escalation(reason, user_text)

    async def generate_reply_text(self, user_text: str | None) -> str:
        return await self.flow.generate_reply_text(user_text)

    async def on_enter(self) -> None:
        await self.session.say(GREETING)

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ):
        user_text = last_text(chat_ctx)
        yield await self.generate_reply_text(user_text or None)
