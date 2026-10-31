from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, computed_field


class DidanProductItem(BaseModel):
    category: str
    product: str
    amount: float
    tax: float = 0.0
    cost: float = 0.0
    profit: float = 0.0
    quantity: float
    inventory: Optional[float] = 0.0
    inventoryCost: Optional[float] = 0.0
    inventoryAmount: Optional[float] = 0.0
    barcode: Optional[str] = ""

    @computed_field
    @property
    def amount_centavos(self) -> int:
        return int(round(self.amount * 100))

    @computed_field
    @property
    def cost_centavos(self) -> int:
        return int(round(self.cost * 100))

    @computed_field
    @property
    def profit_centavos(self) -> int:
        return int(round(self.profit * 100))

    @computed_field
    @property
    def unit_price_pesos(self) -> float:
        return round(self.amount / self.quantity, 2) if self.quantity > 0 else 0.0


class DidanDailyReportSummary(BaseModel):
    total_sales_centavos: int
    total_cost_centavos: int
    total_profit_centavos: int
    total_units_sold: float
    categories_breakdown_centavos: Dict[str, int]
    top_products_by_revenue: List[Dict[str, Any]]
    top_products_by_quantity: List[Dict[str, Any]]
    items: List[DidanProductItem]

    @computed_field
    @property
    def total_sales_pesos(self) -> float:
        return round(self.total_sales_centavos / 100.0, 2)

    @computed_field
    @property
    def total_cost_pesos(self) -> float:
        return round(self.total_cost_centavos / 100.0, 2)

    @computed_field
    @property
    def total_profit_pesos(self) -> float:
        return round(self.total_profit_centavos / 100.0, 2)
