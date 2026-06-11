def pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"
