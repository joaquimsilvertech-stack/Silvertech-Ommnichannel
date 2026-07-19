from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry

from omnichannel.ai.exceptions import AIProviderAuthenticationError, AIProviderTimeoutError
from omnichannel.ai.types import AIProviderResult
from omnichannel.evolution import EvolutionTimeoutError
from omnichannel.factories import (
    ConversationFactory,
    MessageFactory,
    WhatsAppChannelFactory,
)
from omnichannel.models import AIObservabilityEvent, AIProcessingRun, Message, WhatsAppChannel
from omnichannel.tasks import process_ai_response, send_outbound_whatsapp_message
from workspaces.factories import WorkspaceAIProviderConfigFactory
from workspaces.models import AIProvider


def _adapter(result_text: str = 'Resposta observavel.'):
    adapter = MagicMock()
    adapter.generate_response.return_value = AIProviderResult(
        text=result_text,
        provider=AIProvider.OPENAI,
        model_name='gpt-4o-mini',
        external_id='provider-observability-id',
    )
    return adapter


def _run_on_commit_immediately(callback, using=None, robust=False):
    callback()


def _delivery_message(*, send_attempt_count: int = 0) -> Message:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone='5511999999999',
    )
    return MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        body='Texto outbound sensivel.',
        send_attempt_count=send_attempt_count,
    )


@pytest.mark.django_db
def test_process_ai_response_success_creates_attempt_and_success_events() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-observability-key')
    inbound = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Mensagem que nao deve ir para observabilidade.',
    )

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=_adapter()),
        patch('omnichannel.tasks.send_outbound_whatsapp_message.delay'),
        patch('omnichannel.tasks.transaction.on_commit', side_effect=_run_on_commit_immediately),
    ):
        message_id = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(inbound.id),
        )

    events = AIObservabilityEvent.objects.filter(workspace=conversation.workspace)
    assert events.filter(event_type=AIObservabilityEvent.EventType.AI_PROVIDER_ATTEMPT).exists()
    success = events.get(event_type=AIObservabilityEvent.EventType.AI_PROVIDER_SUCCESS)
    assert str(success.output_message_id) == message_id
    assert success.latency_ms is not None
    assert 'Mensagem que nao deve ir para observabilidade.' not in str(success.metadata)
    assert 'Resposta observavel.' not in str(success.metadata)
    assert 'sk-observability-key' not in str(success.metadata)


@pytest.mark.django_db
def test_process_ai_response_retryable_error_creates_retrying_event() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-retry-observability-key')
    inbound = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)
    adapter = _adapter()
    adapter.generate_response.side_effect = AIProviderTimeoutError('timeout detail')

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter),
        patch.object(process_ai_response, 'retry', side_effect=Retry('retry')),
    ):
        with pytest.raises(Retry):
            process_ai_response.run(str(conversation.id), source_message_id=str(inbound.id))

    retry_event = AIObservabilityEvent.objects.get(
        workspace=conversation.workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_RETRYING,
    )
    assert retry_event.status == AIObservabilityEvent.Status.RETRYING
    assert retry_event.error_code == 'AI_PROVIDER_TIMEOUT'
    assert retry_event.metadata['retry_countdown'] == 60
    assert retry_event.metadata['is_retryable'] is True


@pytest.mark.django_db
def test_process_ai_response_final_failure_creates_failed_event() -> None:
    conversation = ConversationFactory()
    provider_config = WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-final-failure-observability-key',
    )
    inbound = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)
    run = AIProcessingRun.objects.create(
        workspace=conversation.workspace,
        conversation=conversation,
        source_message=inbound,
        provider_config=provider_config,
        status=AIProcessingRun.Status.RETRYING,
        attempt_count=2,
    )
    adapter = _adapter()
    adapter.generate_response.side_effect = AIProviderAuthenticationError('auth raw detail')

    with patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter):
        result = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(inbound.id),
            ai_processing_run_id=str(run.id),
        )

    assert result is None
    failed_event = AIObservabilityEvent.objects.get(
        workspace=conversation.workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_FAILED,
    )
    assert failed_event.error_code == 'AI_PROVIDER_AUTHENTICATION'
    assert failed_event.attempt_count == 3


@pytest.mark.django_db
def test_delivery_success_creates_attempt_and_success_events() -> None:
    message = _delivery_message()

    with patch(
        'omnichannel.services.send_whatsapp_message',
        return_value={'key': {'id': 'evolution-id'}},
    ):
        result = send_outbound_whatsapp_message.run(str(message.id))

    assert result == str(message.id)
    events = AIObservabilityEvent.objects.filter(output_message=message)
    assert events.filter(event_type=AIObservabilityEvent.EventType.OUTBOUND_DELIVERY_ATTEMPT).exists()
    assert events.filter(event_type=AIObservabilityEvent.EventType.OUTBOUND_DELIVERY_SUCCESS).exists()
    assert 'Texto outbound sensivel.' not in str(list(events.values('metadata')))


@pytest.mark.django_db
def test_delivery_retryable_error_creates_retrying_event() -> None:
    message = _delivery_message()

    with (
        patch('omnichannel.services.send_whatsapp_message', side_effect=EvolutionTimeoutError()),
        patch.object(send_outbound_whatsapp_message, 'retry', side_effect=Retry('retry')),
    ):
        with pytest.raises(Retry):
            send_outbound_whatsapp_message.run(str(message.id))

    event = AIObservabilityEvent.objects.get(
        output_message=message,
        event_type=AIObservabilityEvent.EventType.OUTBOUND_DELIVERY_RETRYING,
    )
    assert event.error_code == 'EVOLUTION_TIMEOUT'
    assert event.metadata['retry_countdown'] == 60


@pytest.mark.django_db
def test_delivery_final_failure_creates_failed_event() -> None:
    message = _delivery_message(send_attempt_count=2)

    with patch(
        'omnichannel.services.send_whatsapp_message',
        side_effect=EvolutionTimeoutError(),
    ):
        result = send_outbound_whatsapp_message.run(str(message.id))

    assert result == str(message.id)
    event = AIObservabilityEvent.objects.get(
        output_message=message,
        event_type=AIObservabilityEvent.EventType.OUTBOUND_DELIVERY_FAILED,
    )
    assert event.error_code == 'EVOLUTION_TIMEOUT'
    assert event.attempt_count == 3
