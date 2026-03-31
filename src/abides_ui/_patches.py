"""Runtime patches for known upstream library bugs.

Each patch targets a specific issue and should be removed once the
corresponding library fix is released.
"""

from __future__ import annotations

_applied = False


def apply_patches() -> None:
    """Apply all runtime patches (idempotent)."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    _applied = True
    _patch_amm_none_mid()


def _patch_amm_none_mid() -> None:
    """Guard AdaptiveMarketMakerAgent.place_orders against *mid=None*.

    In subscribe mode the agent's ``receive_message`` can call
    ``place_orders(mid)`` when no bid/ask is available yet, leaving
    *mid* as ``None``.  The non-subscribe code path already has a
    ``mid is not None`` guard; this patch adds the same guard to
    ``place_orders`` itself so the agent silently skips the cycle
    instead of raising ``TypeError: int() … NoneType``.

    Upstream fix: add ``and mid is not None`` to the subscribe-mode
    condition in ``AdaptiveMarketMakerAgent.receive_message``.
    """
    from abides_markets.agents.market_makers.adaptive_market_maker_agent import (
        AdaptiveMarketMakerAgent,
    )

    _original = AdaptiveMarketMakerAgent.place_orders

    def _guarded_place_orders(self, mid):  # type: ignore[override]
        if mid is None:
            return
        _original(self, mid)

    AdaptiveMarketMakerAgent.place_orders = _guarded_place_orders  # type: ignore[assignment]
