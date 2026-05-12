from __future__ import annotations

from decimal import Decimal

LBS_TO_KG = Decimal("0.453592")


def normalize_weight(weight: float, unit: str) -> Decimal:
    """Convert weight to kg. Returns Decimal. Raises ValueError for unknown units.

    Zero weight is valid (bodyweight exercises like Pull-Up).
    Accepted units: kg, kilogram, kilograms, lb, lbs, pound, pounds (case-insensitive).
    """
    u = unit.strip().lower()
    w = Decimal(str(weight))
    if u in ("kg", "kilogram", "kilograms"):
        return round(w, 2)
    if u in ("lb", "lbs", "pound", "pounds"):
        return round(w * LBS_TO_KG, 2)
    raise ValueError(f"Unknown weight unit: {unit!r}. Use 'kg' or 'lb'.")
