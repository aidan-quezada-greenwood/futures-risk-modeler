# Instrument constants for supported micro futures contracts.
# Add custom instruments by following the same dict structure.

INSTRUMENTS: dict = {
    "MES": {
        "name":               "Micro E-mini S&P 500",
        "tick_size":          0.25,
        "tick_value":         1.25,
        "point_value":        5.00,
        "margin_estimate":    40,
        "max_stop_ticks":     12,
        "default_commission": 0.35,
    },
    "MGC": {
        "name":               "Micro Gold",
        "tick_size":          0.10,
        "tick_value":         1.00,
        "point_value":        10.00,
        "margin_estimate":    100,
        "max_stop_ticks":     30,
        "default_commission": 0.50,
    },
    "MNQ": {
        "name":               "Micro Nasdaq",
        "tick_size":          0.25,
        "tick_value":         0.50,
        "point_value":        2.00,
        "margin_estimate":    40,
        "max_stop_ticks":     20,
        "default_commission": 0.35,
    },
    "M2K": {
        "name":               "Micro Russell 2000",
        "tick_size":          0.10,
        "tick_value":         0.50,
        "point_value":        5.00,
        "margin_estimate":    25,
        "max_stop_ticks":     20,
        "default_commission": 0.35,
    },
}
