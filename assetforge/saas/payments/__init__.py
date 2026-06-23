"""Платёжный слой: единый интерфейс + подключаемые провайдеры."""
from .registry import get_provider

__all__ = ["get_provider"]
