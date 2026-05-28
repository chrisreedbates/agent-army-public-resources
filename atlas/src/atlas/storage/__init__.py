"""Storage backends for Atlas."""

from .base import Storage
from .local import LocalStorage

__all__ = ["Storage", "LocalStorage"]
