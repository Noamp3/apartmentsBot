# bot/notifications/__init__.py
"""Notification and dispatch package."""

from bot.notifications.dispatcher import (
    BaseNotificationProvider,
    TelegramNotificationProvider,
    NotificationDispatcher
)
