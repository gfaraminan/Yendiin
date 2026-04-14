from __future__ import annotations

from pydantic import BaseModel, Field, AliasChoices, ConfigDict
from typing import Optional, Literal, Any, Dict

SaleItemKind = Literal["ticket","entrada","menu_item","combo","parking","consumicion","otro"]

class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    tenant: str = Field(min_length=1, validation_alias=AliasChoices('tenant', 'tenant_id'))
    email: str = Field(min_length=3)
    role: Literal["buyer","producer","staff"] = "buyer"
    name: Optional[str] = None

class ProducerSellerCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    tenant: str = Field(min_length=1, validation_alias=AliasChoices('tenant', 'tenant_id'))
    event_slug: str
    code: str
    name: str
    active: bool = True

class ProducerSaleItemCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    tenant: str = Field(min_length=1, validation_alias=AliasChoices('tenant', 'tenant_id'))
    event_slug: str
    kind: SaleItemKind = "otro"
    name: str
    price_cents: int = Field(default=0, ge=0)
    stock_total: Optional[int] = Field(default=None, ge=0)  # None = ilimitado (contrato)
    start_date: Optional[str] = None  # ISO string; DB expects datetime (cast)
    end_date: Optional[str] = None
    active: bool = True
    sort_order: int = 0

class OrderCreate(BaseModel):
    tenant: str
    event_slug: str
    sale_item_id: int
    qty: int = Field(ge=1, le=50)
    buyer_email: Optional[str] = None
    seller_code: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None