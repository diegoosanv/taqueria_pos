import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


class WhatsAppClient:
    BASE_URL = "https://graph.facebook.com/v19.0"

    @classmethod
    async def send_text_message(cls, recipient_phone: str, text: str) -> bool:
        if not settings.META_ACCESS_TOKEN or not settings.META_PHONE_NUMBER_ID:
            logger.info(f"Simulacion WhatsApp ({recipient_phone}): {text}")
            print(f"\n[WhatsApp -> {recipient_phone}]: {text}\n")
            return True

        url = f"{cls.BASE_URL}/{settings.META_PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text}
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Error enviando mensaje: {e}")
            return False
