"""Import every model so Base.metadata is complete for Alembic and tests."""

from app.models.base import Base
from app.models.catalogue import Category, Discount, Offer, Product, ProductOption
from app.models.hotels import Hotel, HotelHours
from app.models.ledger import ENTRY_TYPES, LedgerEntry, RiderPayout, Settlement, Statement
from app.models.orders import (
    Customer,
    IdempotencyKey,
    Order,
    OrderEvent,
    OrderItem,
    PromoRedemption,
    Rating,
)
from app.models.payments import (
    DeviceNonce,
    ForwarderDevice,
    ForwarderPairing,
    Payment,
    Refund,
    ReviewItem,
    SmsMessage,
)
from app.models.system import AuditLog, JobRun, Notification, Setting
from app.models.users import (
    PushSubscription,
    RefreshToken,
    RiderPing,
    RiderProfile,
    RiderStrike,
    User,
)

__all__ = [
    "ENTRY_TYPES",
    "AuditLog",
    "Base",
    "Category",
    "Customer",
    "DeviceNonce",
    "Discount",
    "ForwarderDevice",
    "ForwarderPairing",
    "Hotel",
    "HotelHours",
    "IdempotencyKey",
    "JobRun",
    "LedgerEntry",
    "Notification",
    "Offer",
    "Order",
    "OrderEvent",
    "OrderItem",
    "Payment",
    "Rating",
    "Product",
    "ProductOption",
    "PromoRedemption",
    "PushSubscription",
    "Refund",
    "RefreshToken",
    "ReviewItem",
    "RiderPayout",
    "RiderPing",
    "RiderProfile",
    "RiderStrike",
    "Setting",
    "Settlement",
    "SmsMessage",
    "Statement",
    "User",
]
