"""
Pluggable Notification Abstraction for Software Capsule Platform (Prompt 20 / FR-034).
Supports sending governance alerts, ownership transfer notices, grace-period warnings, and expiry notices.
Includes InMemoryNotificationSender for hermetic testing and ConsoleNotificationSender for local dev.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("capsule.notification")


@dataclass
class NotificationMessage:
    recipient: str
    subject: str
    template: str
    context: Dict[str, Any] = field(default_factory=dict)
    body: str = ""
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class NotificationSender(ABC):
    """Abstract interface for governance notifications."""

    @abstractmethod
    async def send(
        self,
        recipient: str,
        subject: str,
        template: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send a notification message asynchronously."""
        pass


class InMemoryNotificationSender(NotificationSender):
    """
    In-memory notification sender for testing and local verification.
    Records all messages sent so test suites can assert on them deterministically.
    """

    def __init__(self):
        self.sent_messages: List[NotificationMessage] = []

    async def send(
        self,
        recipient: str,
        subject: str,
        template: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        ctx = context or {}
        body = self._render_template(template, subject, ctx)
        msg = NotificationMessage(
            recipient=recipient,
            subject=subject,
            template=template,
            context=ctx,
            body=body,
            sent_at=datetime.now(timezone.utc),
        )
        self.sent_messages.append(msg)
        logger.info(f"[Notification] Sent to {recipient}: {subject}")
        return True

    def _render_template(self, template: str, subject: str, context: Dict[str, Any]) -> str:
        app_name = context.get("app_name", "Unknown Capsule")
        app_key = context.get("app_key", "")
        deadline = context.get("deadline", "")
        reason = context.get("reason", "")
        days = context.get("days_left", "")

        if template == "owner_left_grace_period":
            return (
                f"App '{app_name}' ({app_key}) owner has left the organization. "
                f"A {days}-day grace period has started. Assign a new owner before {deadline} "
                f"or the application will be automatically suspended."
            )
        elif template == "owner_grace_period_expired":
            return (
                f"App '{app_name}' ({app_key}) grace period has expired without a new owner assigned. "
                f"The application has been suspended."
            )
        elif template == "ownership_transferred":
            return (
                f"Ownership of app '{app_name}' ({app_key}) has been transferred to you. "
                f"Reason: {reason}."
            )
        elif template == "expiry_warning":
            return (
                f"App '{app_name}' ({app_key}) will expire in {days} days on {deadline}. "
                f"Please renew or export data before expiry."
            )
        elif template == "app_archived":
            return (
                f"App '{app_name}' ({app_key}) has expired and has been archived. "
                f"Data will be retained until {deadline} before purge."
            )
        elif template == "app_purged":
            return (
                f"App '{app_name}' ({app_key}) archive retention period has ended. "
                f"Application data has been purged."
            )
        return f"{subject}: {context}"

    def get_messages_for(self, recipient: str) -> List[NotificationMessage]:
        return [m for m in self.sent_messages if m.recipient.lower() == recipient.lower()]

    def clear(self) -> None:
        self.sent_messages.clear()


class ConsoleNotificationSender(InMemoryNotificationSender):
    """Logs notifications to standard out/logger while also maintaining memory history."""

    async def send(
        self,
        recipient: str,
        subject: str,
        template: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        await super().send(recipient, subject, template, context)
        last_msg = self.sent_messages[-1]
        print(f"\n[GOVERNANCE NOTIFICATION] To: {recipient} | Subject: {subject}\nBody: {last_msg.body}\n")
        return True


_global_notification_sender: NotificationSender = InMemoryNotificationSender()


def get_notification_sender() -> NotificationSender:
    global _global_notification_sender
    return _global_notification_sender


def set_notification_sender(sender: NotificationSender) -> None:
    global _global_notification_sender
    _global_notification_sender = sender
