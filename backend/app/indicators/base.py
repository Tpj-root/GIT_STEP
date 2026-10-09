"""Indicator registry.

An indicator declares its parameters, the series it draws (overlay or its own
pane), and optionally a signal function. The chart component renders whatever
the registry describes, so adding RSI/EMA/MACD later touches no chart code.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Literal, Optional, Protocol


@dataclass
class ParamSpec:
    name: str
    label: str
    kind: Literal["int", "float"]
    default: float
    min: float
    max: float
    step: float = 1.0


@dataclass
class SeriesSpec:
    key: str
    label: str
    pane: Literal["overlay", "separate"] = "overlay"
    kind: Literal["line", "histogram"] = "line"


@dataclass
class IndicatorSpec:
    id: str
    label: str
    params: list[ParamSpec]
    series: list[SeriesSpec]
    emits_signals: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "emits_signals": self.emits_signals,
            "params": [asdict(p) for p in self.params],
            "series": [asdict(s) for s in self.series],
        }


class Engine(Protocol):
    """Stateful, incremental indicator. `update` is called once per CLOSED bar."""
    def update(self, bar) -> dict: ...
    def snapshot(self) -> dict: ...


_REGISTRY: dict[str, tuple[IndicatorSpec, Callable[..., Engine]]] = {}
# Display-only indicators: compute(bars, **params) -> {series_key: [{epoch,value}]}
_OVERLAYS: dict[str, tuple[IndicatorSpec, Callable[..., dict]]] = {}


def register_overlay(spec: IndicatorSpec, compute: Callable[..., dict]) -> None:
    _OVERLAYS[spec.id] = (spec, compute)


def overlay_specs() -> list[dict]:
    return [s.to_dict() for s, _ in _OVERLAYS.values()]


def compute_overlay(indicator_id: str, bars, **params) -> dict:
    if indicator_id not in _OVERLAYS:
        raise KeyError(f"unknown overlay {indicator_id!r}")
    return _OVERLAYS[indicator_id][1](bars, **params)


def register(spec: IndicatorSpec, factory: Callable[..., Engine]) -> None:
    _REGISTRY[spec.id] = (spec, factory)


def specs() -> list[dict]:
    return [s.to_dict() for s, _ in _REGISTRY.values()]


def create(indicator_id: str, **params) -> Engine:
    if indicator_id not in _REGISTRY:
        raise KeyError(f"unknown indicator {indicator_id!r}")
    return _REGISTRY[indicator_id][1](**params)
