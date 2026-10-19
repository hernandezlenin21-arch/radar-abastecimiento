"""Conversión de unidades con factores exactos.

Cada regla devuelve (factor, unidad_normalizada); valor_norm = valor × factor.
Los bushels NO son intercambiables entre granos: el peso estándar difiere.
"""
LB_KG = 0.45359237
SHORT_TON_KG = 2000 * LB_KG          # 907.18474 kg
GAL_L = 3.785411784                  # galón EE.UU.

RULES: dict[str, tuple[float, str]] = {
    "short_ton_to_t":     (1000 / SHORT_TON_KG, "USD/t"),
    "bu_corn_to_t":       (1000 / (56 * LB_KG), "USD/t"),   # maíz/sorgo 56 lb
    "bu_soy_to_t":        (1000 / (60 * LB_KG), "USD/t"),   # soya 60 lb
    "bu_wheat_to_t":      (1000 / (60 * LB_KG), "USD/t"),   # trigo 60 lb
    "cents_bu_corn_to_t": (1000 / (56 * LB_KG) / 100, "USD/t"),
    "cents_bu_soy_to_t":  (1000 / (60 * LB_KG) / 100, "USD/t"),
    "cents_lb_to_t":      (1000 / LB_KG / 100, "USD/t"),
    "lb_to_t":            (1000 / LB_KG, "USD/t"),
    "gal_to_l":           (1 / GAL_L, "USD/L"),
    "cwt_to_kg":          (1 / (100 * LB_KG), "USD/kg"),
    "troy_oz_to_g":       (1 / 31.1034768, "USD/g"),
}


def rule(name: str | None, original_unit: str) -> tuple[float, str]:
    if not name:
        return 1.0, original_unit
    if name not in RULES:
        raise ValueError(f"Regla de normalización desconocida: {name}")
    return RULES[name]


def apply(value: float, name: str | None, original_unit: str) -> float:
    factor, _ = rule(name, original_unit)
    return value * factor
