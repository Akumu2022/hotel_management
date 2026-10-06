"""Allowed values for string-enum columns. Each is enforced by a CHECK constraint."""

USER_ROLES = ("super_admin", "hotel_admin", "cashier", "rider")
# Rider KYC: draft (filling in) -> pending (submitted) -> approved | rejected -> pending...
KYC_STATUSES = ("draft", "pending", "approved", "rejected", "suspended")
HOTEL_ROLES = ("hotel_admin", "cashier")
HOTEL_STATUSES = ("active", "paused")
PAYOUT_MODES = ("instant", "weekly")

DISCOUNT_SCOPES = ("item", "order")
DISCOUNT_KINDS = ("percent", "fixed")

ORDER_TYPES = ("delivery", "pickup", "eat_in")  # eat_in: order ahead, pay, eat there
RIDER_FEE_MODES = ("included", "cash", "none")  # included = option A, cash = option B
PAYMENT_METHODS = ("mpesa", "cash")
ORDER_STATUSES = (
    "awaiting_payment",
    "checking_payment",  # code entered, matching or review pending; expiry paused
    "paid",
    "accepted",
    "preparing",
    "ready",
    "picked_up",
    "on_the_way",
    "delivered",
    "collected",
    "expired",
    "rejected",
    "cancelled",
    "failed_delivery",
)
ACTOR_TYPES = ("customer", "staff", "rider", "admin", "system", "forwarder")

SMS_PARSE_STATUSES = ("parsed", "failed", "reversal", "ignored")
PAYMENT_SOURCES = ("forwarder", "manual", "daraja")
PAYMENT_STATUSES = ("matched", "review", "reversed")
REVIEW_TYPES = (
    "underpaid",
    "overpaid",
    "unmatched_sms",
    "no_sms",
    "reversal",
    "parse_failed",
    "late_payment",
    "fee_dispute",
    "failed_delivery",
)
REVIEW_STATUSES = ("open", "resolved")
REFUND_STATUSES = ("approved", "sent")

PARTIES = ("platform", "hotel", "rider", "customer")
LEDGER_KINDS = ("obligation", "payment")
STATEMENT_STATUSES = ("open", "paid", "overdue")
NOTIFICATION_CHANNELS = ("sms", "push")
