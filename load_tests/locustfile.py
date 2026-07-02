from __future__ import annotations

from locust import HttpUser, constant, task


class WebhookUser(HttpUser):
    """Carga agressiva no webhook WhatsApp para validar throttling."""

    wait_time = constant(0)

    @task
    def post_whatsapp_webhook(self) -> None:
        payload = {
            'event': 'messages.upsert',
            'instance': 'silvertech_whatsapp',
            'data': {},
        }

        with self.client.post(
            '/api/omnichannel/webhooks/whatsapp/',
            json=payload,
            name='POST /api/omnichannel/webhooks/whatsapp/',
            catch_response=True,
        ) as response:
            if response.status_code in {200, 429}:
                response.success()
                return

            response.failure(
                f'Unexpected status code {response.status_code}: {response.text[:200]}',
            )
