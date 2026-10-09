import asyncio, requests
from .config import settings

def _fetch_otp_url() -> str:
    r = requests.post(
        f"{settings.deriv_rest_url}/trading/v1/options/accounts/"
        f"{settings.deriv_account_id}/otp",
        headers={"Deriv-App-ID": settings.deriv_app_id,
                 "Authorization": f"Bearer {settings.deriv_api_token}"},
        timeout=10)
    r.raise_for_status()
    return r.json()["data"]["url"]

async def get_ws_url() -> str:
    if settings.deriv_api_token and settings.deriv_account_id:
        return await asyncio.to_thread(_fetch_otp_url)   # fresh OTP every time
    return f"{settings.deriv_ws_base}/public"