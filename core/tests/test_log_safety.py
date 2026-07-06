from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from omnichannel.services import send_whatsapp_message
from workspaces.views import send_invite_email


@pytest.mark.django_db
def test_webhook_logs_only_safe_metadata(api_client: APIClient, tenant_workspace, caplog) -> None:
    caplog.set_level(logging.INFO, logger='omnichannel.views')
    sensitive_message = 'SENSITIVE_MESSAGE_CONTENT_123'
    sensitive_phone = '+5561999999999'
    payload = {
        'event': 'messages.upsert',
        'instance': 'silvertech_whatsapp',
        'data': {
            'key': {
                'remoteJid': f'{sensitive_phone}@s.whatsapp.net',
                'fromMe': False,
            },
            'message': {'conversation': sensitive_message},
        },
    }

    with patch('omnichannel.views.process_whatsapp_webhook_task.delay') as mock_delay:
        response = api_client.post(
            f'/api/omnichannel/webhooks/whatsapp/?workspace={tenant_workspace.id}',
            payload,
            format='json',
        )

    assert response.status_code == status.HTTP_200_OK
    mock_delay.assert_called_once_with(payload, str(tenant_workspace.id))
    assert sensitive_message not in caplog.text
    assert sensitive_phone not in caplog.text
    assert repr(payload) not in caplog.text

    webhook_record = next(
        record for record in caplog.records if record.message == 'Webhook recebido'
    )
    assert webhook_record.channel == 'whatsapp'
    assert webhook_record.event == 'messages.upsert'
    assert webhook_record.workspace_id == str(tenant_workspace.id)
    assert webhook_record.has_payload is True


def test_evolution_failure_logs_safe_metadata_without_response_body_or_phone(
    settings,
    caplog,
) -> None:
    caplog.set_level(logging.ERROR, logger='omnichannel.services')
    settings.EVOLUTION_API_URL = 'http://evolution.local'
    settings.EVOLUTION_API_KEY = 'test-evolution-key'
    settings.EVOLUTION_INSTANCE_NAME = 'silvertech_whatsapp'
    sensitive_response = 'SENSITIVE_EVOLUTION_RESPONSE_456'
    sensitive_phone = '+5561999999999'

    response = requests.Response()
    response.status_code = 502
    response._content = sensitive_response.encode()
    response.url = 'http://evolution.local/message/sendText/silvertech_whatsapp'
    error = requests.exceptions.HTTPError(
        sensitive_response,
        response=response,
    )

    with patch('omnichannel.services.requests.post', side_effect=error):
        with pytest.raises(requests.exceptions.HTTPError):
            send_whatsapp_message(sensitive_phone, 'Mensagem sem logar payload')

    assert sensitive_response not in caplog.text
    assert sensitive_phone not in caplog.text
    assert 'Mensagem sem logar payload' not in caplog.text

    error_record = next(
        record for record in caplog.records if record.message == 'Falha no envio pela Evolution API'
    )
    assert error_record.operation == 'send_whatsapp_message'
    assert error_record.status_code == 502
    assert error_record.exception_type == 'HTTPError'
    assert error_record.instance_name == 'silvertech_whatsapp'


def test_invite_logging_does_not_expose_token_or_stdout(caplog, capsys) -> None:
    caplog.set_level(logging.INFO, logger='workspaces.views')
    sensitive_token = 'SENSITIVE_INVITE_TOKEN_789'
    invite = SimpleNamespace(
        id='invite-id-123',
        workspace_id='workspace-id-456',
        email='sensitive.user@example.com',
        role='agent',
        token=sensitive_token,
        expires_at=timezone.now() + timedelta(days=7),
    )

    send_invite_email(invite)

    captured = capsys.readouterr()
    assert sensitive_token not in captured.out
    assert sensitive_token not in captured.err
    assert captured.out == ''
    assert captured.err == ''
    assert sensitive_token not in caplog.text
    assert 'sensitive.user@example.com' not in caplog.text

    invite_record = next(
        record for record in caplog.records if record.message == 'Convite de workspace criado'
    )
    assert invite_record.workspace_id == 'workspace-id-456'
    assert invite_record.invite_id == 'invite-id-123'
    assert invite_record.role == 'agent'
    assert invite_record.email == 's***@example.com'
