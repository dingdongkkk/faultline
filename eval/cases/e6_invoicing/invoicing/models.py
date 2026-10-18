from dataclasses import dataclass, field


@dataclass
class Line:
    sku: str
    qty: int


@dataclass
class Order:
    lines: list = field(default_factory=list)
    region: str = "US"
    currency: str = "USD"
    coupon: str | None = None
