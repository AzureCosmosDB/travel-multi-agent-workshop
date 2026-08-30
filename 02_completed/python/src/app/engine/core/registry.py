"""
A tiny registry — the single extension mechanism used across the engine.

Every pluggable area (detectors, policy domains, projections) owns a `Registry`.
Adding functionality is then always the same gesture, which is the point for
teaching: create a module in that folder and decorate your function/class:

    from ..core import Registry
    DETECTORS = Registry("detectors")

    @DETECTORS.register("structural.repeated_node")
    def repeated_node(nodes): ...

...and it is discovered automatically (the package __init__ imports its modules).
No framework, no magic — just a dict with a decorator.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator


class Registry:
    def __init__(self, name: str):
        self.name = name
        self._items: dict[str, Any] = {}

    def register(self, key: str) -> Callable:
        if key in self._items:
            raise ValueError(f"{self.name}: '{key}' already registered")

        def deco(obj):
            self._items[key] = obj
            return obj
        return deco

    def get(self, key: str) -> Any:
        return self._items[key]

    def keys(self) -> list[str]:
        return list(self._items.keys())

    def items(self) -> Iterator[tuple[str, Any]]:
        return iter(self._items.items())

    def __len__(self) -> int:
        return len(self._items)
