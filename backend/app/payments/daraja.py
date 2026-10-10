"""Real Daraja adapter (Lipa Na M-Pesa Online). Secrets come from PaymentsConfig only."""

import base64
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.payments.adapter import CollectAccepted, CollectStatus, ProviderError
from app.payments.config import PaymentsConfig

BASES = {"sandbox": "https://sandbox.safaricom.co.ke", "production": "https://api.safaricom.co.ke"}


class DarajaProvider:
    def __init__(self, cfg: PaymentsConfig, client: httpx.AsyncClient | None = None) -> None:
        self.cfg = cfg
        self.base = BASES[cfg.daraja_env]
        self.client = client or httpx.AsyncClient(timeout=20)
        self._token: tuple[str, float] | None = None

    async def _auth(self) -> str:
        if self._token and self._token[1] > time.monotonic():
            return self._token[0]
        r = await self.client.get(
            f"{self.base}/oauth/v1/generate?grant_type=client_credentials",
            auth=(self.cfg.daraja_consumer_key, self.cfg.daraja_consumer_secret),
        )
        r.raise_for_status()
        data = r.json()
        self._token = (data["access_token"], time.monotonic() + int(data["expires_in"]) - 60)
        return self._token[0]

    def _password(self) -> tuple[str, str]:
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")
        raw = f"{self.cfg.daraja_shortcode}{self.cfg.daraja_passkey}{ts}"
        return base64.b64encode(raw.encode()).decode(), ts

    async def collect(self, *, phone, amount, account_ref, callback_url) -> CollectAccepted:
        pw, ts = self._password()
        body = {
            "BusinessShortCode": self.cfg.daraja_shortcode,
            "Password": pw,
            "Timestamp": ts,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": phone,
            "PartyB": self.cfg.daraja_shortcode,
            "PhoneNumber": phone,
            "CallBackURL": callback_url,
            "AccountReference": account_ref[:12],
            "TransactionDesc": "Order payment",
        }
        r = await self.client.post(
            f"{self.base}/mpesa/stkpush/v1/processrequest",
            json=body,
            headers={"Authorization": f"Bearer {await self._auth()}"},
        )
        data = r.json()
        if r.status_code != 200 or data.get("ResponseCode") != "0":
            raise ProviderError(
                data.get("errorMessage") or data.get("ResponseDescription") or "rejected"
            )
        return CollectAccepted(data["CheckoutRequestID"], data["MerchantRequestID"])

    async def query_collection(self, checkout_request_id: str) -> CollectStatus:
        pw, ts = self._password()
        r = await self.client.post(
            f"{self.base}/mpesa/stkpushquery/v1/query",
            json={
                "BusinessShortCode": self.cfg.daraja_shortcode,
                "Password": pw,
                "Timestamp": ts,
                "CheckoutRequestID": checkout_request_id,
            },
            headers={"Authorization": f"Bearer {await self._auth()}"},
        )
        data = r.json()
        if "ResultCode" not in data:  # still processing: Daraja answers with an error body
            return CollectStatus(result_code=None, result_desc=str(data.get("errorMessage", "")))
        return CollectStatus(
            result_code=int(data["ResultCode"]), result_desc=data.get("ResultDesc", "")
        )


class DarajaB2C(DarajaProvider):
    """Payouts. Separate Daraja app and initiator from collection. Verify each call in the
    sandbox before any live use: the field names below follow Safaricom's B2C v3 docs."""

    async def _b2c_auth(self) -> str:
        r = await self.client.get(
            f"{self.base}/oauth/v1/generate?grant_type=client_credentials",
            auth=(self.cfg.daraja_b2c_consumer_key, self.cfg.daraja_b2c_consumer_secret),
        )
        r.raise_for_status()
        return r.json()["access_token"]

    async def disburse(self, *, phone, amount, originator_id, result_url, timeout_url):
        from app.payments.adapter import DisburseAccepted

        body = {
            "OriginatorConversationID": originator_id,
            "InitiatorName": self.cfg.daraja_initiator_name,
            "SecurityCredential": self.cfg.daraja_security_credential,
            "CommandID": "BusinessPayment",
            "Amount": amount,
            "PartyA": self.cfg.daraja_b2c_shortcode,
            "PartyB": phone,
            "Remarks": "Rider earnings",
            "QueueTimeOutURL": timeout_url,
            "ResultURL": result_url,
            "Occasion": "Payout",
        }
        r = await self.client.post(
            f"{self.base}/mpesa/b2c/v3/paymentrequest",
            json=body,
            headers={"Authorization": f"Bearer {await self._b2c_auth()}"},
        )
        if r.status_code >= 500:
            raise RuntimeError(f"daraja {r.status_code}")  # unknown outcome: never a clean no
        data = r.json()
        if r.status_code != 200 or data.get("ResponseCode") != "0":
            raise ProviderError(
                data.get("errorMessage") or data.get("ResponseDescription") or "rejected"
            )
        return DisburseAccepted(data.get("ConversationID", ""))

    async def pay_till(self, *, till, amount, originator_id, result_url, timeout_url):
        from app.payments.adapter import DisburseAccepted

        body = {
            "Initiator": self.cfg.daraja_initiator_name,
            "SecurityCredential": self.cfg.daraja_security_credential,
            "CommandID": "BusinessBuyGoods",
            "SenderIdentifierType": "4",
            "RecieverIdentifierType": "2",
            "Amount": amount,
            "PartyA": self.cfg.daraja_b2c_shortcode,
            "PartyB": till,
            "AccountReference": originator_id[:12],
            "Remarks": "Hotel settlement",
            "QueueTimeOutURL": timeout_url,
            "ResultURL": result_url,
            "OriginatorConversationID": originator_id,
        }
        r = await self.client.post(
            f"{self.base}/mpesa/b2b/v1/paymentrequest",
            json=body,
            headers={"Authorization": f"Bearer {await self._b2c_auth()}"},
        )
        if r.status_code >= 500:
            raise RuntimeError(f"daraja {r.status_code}")
        data = r.json()
        if r.status_code != 200 or data.get("ResponseCode") != "0":
            raise ProviderError(
                data.get("errorMessage") or data.get("ResponseDescription") or "rejected"
            )
        return DisburseAccepted(data.get("ConversationID", ""))

    def _async_urls(self, leaf: str) -> tuple[str, str]:
        base = (
            f"{self.cfg.daraja_callback_base.rstrip('/')}/api/v1/payments/daraja/"
            f"{self.cfg.daraja_callback_token}"
        )
        return f"{base}/{leaf}/result", f"{base}/{leaf}/timeout"

    async def _post_async(self, path: str, body: dict) -> None:
        r = await self.client.post(
            f"{self.base}{path}",
            json=body,
            headers={"Authorization": f"Bearer {await self._b2c_auth()}"},
        )
        data = r.json()
        if r.status_code != 200 or data.get("ResponseCode") != "0":
            raise ProviderError(
                data.get("errorMessage") or data.get("ResponseDescription") or "rejected"
            )

    async def query_disbursement(self, originator_id, *, result_url, timeout_url):
        """Transaction Status. Daraja answers on the status result URL (never here), where the
        route applies it to the payout. Returns None now: 'ask again next run'."""
        result, timeout = self._async_urls("status")
        await self._post_async(
            "/mpesa/transactionstatus/v1/query",
            {
                "Initiator": self.cfg.daraja_initiator_name,
                "SecurityCredential": self.cfg.daraja_security_credential,
                "CommandID": "TransactionStatus",
                "OriginatorConversationID": originator_id,
                "PartyA": self.cfg.daraja_b2c_shortcode,
                "IdentifierType": "4",
                "ResultURL": result,
                "QueueTimeOutURL": timeout,
                "Remarks": "Status check",
                "Occasion": originator_id[:100],
            },
        )
        return None

    async def account_balance(self) -> int:
        """Daraja answers Account Balance on a callback, which caches it (see balance.py). A
        fresh cached value is returned; otherwise a request is sent and, until it lands, the
        answer is 'unknown' so the float check fails closed."""
        from app.payments import balance

        cached = balance.fresh()
        if cached is not None:
            return cached
        result, timeout = self._async_urls("balance")
        await self._post_async(
            "/mpesa/accountbalance/v1/query",
            {
                "Initiator": self.cfg.daraja_initiator_name,
                "SecurityCredential": self.cfg.daraja_security_credential,
                "CommandID": "AccountBalance",
                "PartyA": self.cfg.daraja_b2c_shortcode,
                "IdentifierType": "4",
                "Remarks": "Float check",
                "QueueTimeOutURL": timeout,
                "ResultURL": result,
            },
        )
        raise ProviderError("balance requested, waiting for Daraja")
