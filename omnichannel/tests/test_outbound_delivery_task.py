from __future__ import annotations

import logging
from threading import Event, Thread
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.db import close_old_connections, connection
from django.test import override_settings

from omnichannel.evolution import (
    EvolutionAPIError,
    EvolutionAuthenticationError,
    EvolutionConfigurationError,
    EvolutionConflictError,
    EvolutionConnectionError,
    EvolutionInvalidRequestError,
    EvolutionInvalidResponseError,
    EvolutionNotFoundError,
    EvolutionRateLimitError,
    EvolutionTimeoutError,
    EvolutionUnavailableError,
)
from omnichannel.factories import (
    ConversationFactory,
    MessageFactory,
    WhatsAppChannelFactory,
)
from omnichannel.models import AIProcessingRun, Message, WhatsAppChannel
from omnichannel.outbound_routing import (
    OUTBOUND_CHANNEL_DELETING,
    OUTBOUND_CHANNEL_DISCONNECTED,
    OUTBOUND_CHANNEL_ERROR,
    OUTBOUND_CHANNEL_NOT_READY,
    OUTBOUND_CHANNEL_ROUTE_MISMATCH,
    OUTBOUND_CONVERSATION_CHANNEL_MISSING,
)
from omnichannel.tasks import send_outbound_whatsapp_message
from workspaces.factories import WorkspaceFactory


def _outbound_message(
    *,
    channel: WhatsAppChannel | None = None,
    phone: str = '5511999999999',
    body: str = 'Resposta para enviar.',
    status: str = Message.Status.PENDING,
    send_attempt_count: int = 0,
) -> Message:
    channel = channel or WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone=phone,
    )
    return MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        status=status,
        body=body,
        send_attempt_count=send_attempt_count,
    )


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_sends_pending_message_and_marks_sent() -> None:
    message = _outbound_message(
        body='Resposta para enviar.',
    )
    message.send_error_code = 'EVOLUTION_TIMEOUT'
    message.save(update_fields=['send_error_code', 'updated_at'])

    with patch(
        'omnichannel.services.send_whatsapp_message',
        return_value={'key': {'id': 'evolution-message-id'}},
    ) as mock_send:
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == Message.Status.SENT
    assert message.external_id == 'evolution-message-id'
    assert message.send_error_code == ''
    assert message.next_send_retry_at is None
    assert message.send_attempt_count == 1
    assert message.last_send_attempt_at is not None
    mock_send.assert_called_once_with(
        channel=message.conversation.whatsapp_channel,
        phone='5511999999999',
        text='Resposta para enviar.',
    )


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_already_sent_is_idempotent() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.SENT,
    )

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        result = send_outbound_whatsapp_message.run(str(message.id))

    assert result == str(message.id)
    mock_send.assert_not_called()


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_ignores_inbound_message() -> None:
    message = MessageFactory(
        direction=Message.Direction.INBOUND,
        status=Message.Status.DELIVERED,
    )

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        result = send_outbound_whatsapp_message.run(str(message.id))

    assert result is None
    mock_send.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('exception', 'expected_error_code'),
    [
        (EvolutionTimeoutError(), 'EVOLUTION_TIMEOUT'),
        (EvolutionConnectionError(), 'EVOLUTION_CONNECTION_ERROR'),
        (EvolutionRateLimitError(), 'EVOLUTION_RATE_LIMIT'),
        (EvolutionUnavailableError(), 'EVOLUTION_UNAVAILABLE'),
        (EvolutionAPIError(retryable=True), 'EVOLUTION_REQUEST_ERROR'),
    ],
)
def test_send_outbound_whatsapp_message_retryable_error_schedules_retry(
    exception: Exception,
    expected_error_code: str,
    caplog,
) -> None:
    message = _outbound_message(
        body='Texto que nao deve vazar.',
    )
    caplog.set_level(logging.WARNING)

    with (
        patch('omnichannel.services.send_whatsapp_message', side_effect=exception) as mock_send,
        patch.object(send_outbound_whatsapp_message, 'retry', side_effect=Retry('retry')) as mock_retry,
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_adapter,
    ):
        with pytest.raises(Retry):
            send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert message.status == Message.Status.PENDING
    assert message.send_attempt_count == 1
    assert message.send_error_code == expected_error_code
    assert message.next_send_retry_at is not None
    assert mock_retry.call_args.kwargs['countdown'] == 60
    assert mock_retry.call_args.kwargs['args'] == (
        str(message.id),
        str(message.conversation.whatsapp_channel_id),
    )
    mock_send.assert_called_once()
    mock_adapter.assert_not_called()
    assert 'Texto que nao deve vazar.' not in caplog.text
    assert 'api_key' not in caplog.text
    assert 'payload' not in caplog.text


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_exhausted_retries_marks_failed_without_new_message() -> None:
    message = _outbound_message(send_attempt_count=2)

    with (
        patch('omnichannel.services.send_whatsapp_message', side_effect=EvolutionTimeoutError()),
        patch.object(send_outbound_whatsapp_message, 'retry') as mock_retry,
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_adapter,
    ):
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == Message.Status.FAILED
    assert message.send_attempt_count == 3
    assert message.send_error_code == 'EVOLUTION_TIMEOUT'
    assert Message.objects.filter(conversation=message.conversation).count() == 1
    mock_retry.assert_not_called()
    mock_adapter.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('exception', 'expected_error_code'),
    [
        (EvolutionAuthenticationError(), 'EVOLUTION_AUTHENTICATION_ERROR'),
        (EvolutionConfigurationError(), 'EVOLUTION_CONFIGURATION_ERROR'),
        (EvolutionInvalidRequestError(), 'EVOLUTION_INVALID_REQUEST'),
        (EvolutionNotFoundError(), 'EVOLUTION_NOT_FOUND'),
        (EvolutionConflictError(), 'EVOLUTION_CONFLICT'),
        (EvolutionInvalidResponseError(), 'EVOLUTION_INVALID_RESPONSE'),
        (RuntimeError('unknown'), 'EVOLUTION_UNKNOWN_ERROR'),
    ],
)
def test_send_outbound_whatsapp_message_permanent_error_marks_failed(
    exception: Exception,
    expected_error_code: str,
) -> None:
    message = _outbound_message()

    with (
        patch('omnichannel.services.send_whatsapp_message', side_effect=exception),
        patch.object(send_outbound_whatsapp_message, 'retry') as mock_retry,
    ):
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == Message.Status.FAILED
    assert message.send_attempt_count == 1
    assert message.send_error_code == expected_error_code
    mock_retry.assert_not_called()


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_failed_status_is_not_retried() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.FAILED,
        send_error_code='EVOLUTION_TIMEOUT',
    )

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result is None
    assert message.status == Message.Status.FAILED
    assert Message.objects.filter(conversation=message.conversation).count() == 1
    mock_send.assert_not_called()


@pytest.mark.django_db
@override_settings(EVOLUTION_INSTANCE_NAME='legacy-global-must-not-be-used')
def test_legacy_task_call_derives_channel_without_global_fallback() -> None:
    channel = WhatsAppChannelFactory(
        status=WhatsAppChannel.Status.CONNECTED,
        instance_name='persisted-channel-instance',
    )
    message = _outbound_message(channel=channel)

    with patch(
        'omnichannel.services.send_whatsapp_message',
        return_value={'key': {'id': 'legacy-task-result'}},
    ) as mock_send:
        result = send_outbound_whatsapp_message.run(str(message.id))

    assert result == str(message.id)
    assert mock_send.call_args.kwargs['channel'].id == channel.id
    assert 'legacy-global-must-not-be-used' not in str(mock_send.call_args)


@pytest.mark.django_db
def test_new_task_call_validates_expected_channel_without_redirecting() -> None:
    message = _outbound_message()
    manipulated_channel = WhatsAppChannelFactory(
        workspace=message.conversation.workspace,
        status=WhatsAppChannel.Status.CONNECTED,
    )

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        result = send_outbound_whatsapp_message.run(
            str(message.id),
            str(manipulated_channel.id),
        )

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == Message.Status.FAILED
    assert message.send_error_code == OUTBOUND_CHANNEL_ROUTE_MISMATCH
    assert message.send_attempt_count == 1
    mock_send.assert_not_called()


@pytest.mark.django_db
def test_channels_in_same_workspace_use_their_own_instances() -> None:
    workspace = WorkspaceFactory()
    first_channel = WhatsAppChannelFactory(
        workspace=workspace,
        status=WhatsAppChannel.Status.CONNECTED,
        instance_name='workspace-channel-a',
    )
    second_channel = WhatsAppChannelFactory(
        workspace=workspace,
        status=WhatsAppChannel.Status.CONNECTED,
        instance_name='workspace-channel-b',
    )
    first_message = _outbound_message(channel=first_channel)
    second_message = _outbound_message(channel=second_channel)

    with patch(
        'omnichannel.services.send_whatsapp_message',
        return_value={'key': {'id': 'provider-id'}},
    ) as mock_send:
        send_outbound_whatsapp_message.run(str(first_message.id), str(first_channel.id))
        send_outbound_whatsapp_message.run(str(second_message.id), str(second_channel.id))

    called_channels = [call.kwargs['channel'] for call in mock_send.call_args_list]
    assert [channel.id for channel in called_channels] == [first_channel.id, second_channel.id]
    assert [channel.instance_name for channel in called_channels] == [
        'workspace-channel-a',
        'workspace-channel-b',
    ]


@pytest.mark.django_db
def test_channels_from_different_workspaces_remain_isolated() -> None:
    first_message = _outbound_message(
        channel=WhatsAppChannelFactory(
            status=WhatsAppChannel.Status.CONNECTED,
            instance_name='tenant-a-instance',
        ),
    )
    second_message = _outbound_message(
        channel=WhatsAppChannelFactory(
            status=WhatsAppChannel.Status.CONNECTED,
            instance_name='tenant-b-instance',
        ),
    )

    with patch(
        'omnichannel.services.send_whatsapp_message',
        return_value={},
    ) as mock_send:
        send_outbound_whatsapp_message.run(str(first_message.id))
        send_outbound_whatsapp_message.run(str(second_message.id))

    calls = mock_send.call_args_list
    assert calls[0].kwargs['channel'].workspace_id == first_message.conversation.workspace_id
    assert calls[1].kwargs['channel'].workspace_id == second_message.conversation.workspace_id
    assert calls[0].kwargs['channel'].workspace_id != calls[1].kwargs['channel'].workspace_id


@pytest.mark.django_db
@override_settings(EVOLUTION_INSTANCE_NAME='legacy-global-must-not-be-used')
def test_conversation_without_channel_fails_without_global_fallback() -> None:
    conversation = ConversationFactory(whatsapp_channel=None)
    message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
    )

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == Message.Status.FAILED
    assert message.send_error_code == OUTBOUND_CONVERSATION_CHANNEL_MISSING
    mock_send.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('channel_status', 'error_code'),
    [
        (WhatsAppChannel.Status.DISCONNECTED, OUTBOUND_CHANNEL_DISCONNECTED),
        (WhatsAppChannel.Status.ERROR, OUTBOUND_CHANNEL_ERROR),
        (WhatsAppChannel.Status.DELETING, OUTBOUND_CHANNEL_DELETING),
    ],
)
def test_permanent_channel_status_marks_failed_without_evolution(
    channel_status: str,
    error_code: str,
) -> None:
    channel = WhatsAppChannelFactory(status=channel_status)
    message = _outbound_message(channel=channel)

    with (
        patch('omnichannel.services.send_whatsapp_message') as mock_send,
        patch.object(send_outbound_whatsapp_message, 'retry') as mock_retry,
    ):
        result = send_outbound_whatsapp_message.run(str(message.id), str(channel.id))

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == Message.Status.FAILED
    assert message.send_error_code == error_code
    mock_send.assert_not_called()
    mock_retry.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    'channel_status',
    [
        WhatsAppChannel.Status.PROVISIONING,
        WhatsAppChannel.Status.WAITING_QR,
        WhatsAppChannel.Status.CONNECTING,
        WhatsAppChannel.Status.RECONNECTING,
    ],
)
def test_transient_channel_status_retries_same_message_and_channel(
    channel_status: str,
) -> None:
    channel = WhatsAppChannelFactory(status=channel_status)
    message = _outbound_message(channel=channel)

    with (
        patch('omnichannel.services.send_whatsapp_message') as mock_send,
        patch.object(
            send_outbound_whatsapp_message,
            'retry',
            side_effect=Retry('retry'),
        ) as mock_retry,
    ):
        with pytest.raises(Retry):
            send_outbound_whatsapp_message.run(str(message.id), str(channel.id))

    message.refresh_from_db()
    assert message.status == Message.Status.PENDING
    assert message.send_error_code == OUTBOUND_CHANNEL_NOT_READY
    assert message.send_attempt_count == 1
    assert message.next_send_retry_at is not None
    assert mock_retry.call_args.kwargs['args'] == (str(message.id), str(channel.id))
    mock_send.assert_not_called()


@pytest.mark.django_db
def test_channel_change_before_retry_fails_route_mismatch() -> None:
    workspace = WorkspaceFactory()
    original_channel = WhatsAppChannelFactory(
        workspace=workspace,
        status=WhatsAppChannel.Status.CONNECTED,
    )
    replacement_channel = WhatsAppChannelFactory(
        workspace=workspace,
        status=WhatsAppChannel.Status.CONNECTED,
    )
    message = _outbound_message(channel=original_channel)

    with (
        patch(
            'omnichannel.services.send_whatsapp_message',
            side_effect=EvolutionTimeoutError(),
        ),
        patch.object(
            send_outbound_whatsapp_message,
            'retry',
            side_effect=Retry('retry'),
        ),
    ):
        with pytest.raises(Retry):
            send_outbound_whatsapp_message.run(str(message.id), str(original_channel.id))

    message.conversation.whatsapp_channel = replacement_channel
    message.conversation.save(update_fields=['whatsapp_channel', 'updated_at'])

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        result = send_outbound_whatsapp_message.run(
            str(message.id),
            str(original_channel.id),
        )

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == Message.Status.FAILED
    assert message.send_error_code == OUTBOUND_CHANNEL_ROUTE_MISMATCH
    assert message.send_attempt_count == 2
    mock_send.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    'terminal_status',
    [
        Message.Status.DELIVERED,
        Message.Status.READ,
        Message.Status.FAILED,
    ],
)
def test_terminal_message_status_never_resends(terminal_status: str) -> None:
    message = _outbound_message(status=terminal_status)

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert message.status == terminal_status
    assert message.send_attempt_count == 0
    mock_send.assert_not_called()


@pytest.mark.django_db
def test_retry_does_not_create_message_or_ai_run() -> None:
    message = _outbound_message()
    initial_message_count = Message.objects.count()
    initial_run_count = AIProcessingRun.objects.count()

    with (
        patch(
            'omnichannel.services.send_whatsapp_message',
            side_effect=EvolutionTimeoutError(),
        ),
        patch.object(
            send_outbound_whatsapp_message,
            'retry',
            side_effect=Retry('retry'),
        ),
        patch('omnichannel.ai.registry.get_provider_adapter') as provider_adapter,
    ):
        with pytest.raises(Retry):
            send_outbound_whatsapp_message.run(str(message.id))

    assert Message.objects.count() == initial_message_count
    assert AIProcessingRun.objects.count() == initial_run_count
    provider_adapter.assert_not_called()


@pytest.mark.django_db
def test_delivery_logs_exclude_phone_body_instance_and_credentials(caplog) -> None:
    channel = WhatsAppChannelFactory(
        status=WhatsAppChannel.Status.CONNECTED,
        instance_name='private-instance-name',
        instance_token='private-instance-token',
    )
    message = _outbound_message(
        channel=channel,
        phone='5511888877777',
        body='Private outbound body',
        send_attempt_count=2,
    )
    caplog.set_level(logging.INFO, logger='omnichannel.tasks')

    with patch(
        'omnichannel.services.send_whatsapp_message',
        side_effect=EvolutionAuthenticationError(),
    ):
        send_outbound_whatsapp_message.run(str(message.id), str(channel.id))

    rendered = ' '.join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    assert '5511888877777' not in rendered
    assert 'Private outbound body' not in rendered
    assert 'private-instance-name' not in rendered
    assert 'private-instance-token' not in rendered


@pytest.mark.django_db(transaction=True)
def test_concurrent_tasks_send_once_and_only_winner_counts_attempt() -> None:
    if connection.vendor != 'postgresql':
        pytest.skip('PostgreSQL advisory lock test.')

    message = _outbound_message(body='Concurrent outbound body')
    channel_id = str(message.conversation.whatsapp_channel_id)
    send_started = Event()
    release_send = Event()
    first_finished = Event()
    second_finished = Event()
    thread_errors: list[BaseException] = []
    thread_results: dict[str, str | None] = {}

    def blocking_send(**kwargs):
        send_started.set()
        if not release_send.wait(timeout=10):
            raise AssertionError('Timed out waiting to release outbound HTTP mock.')
        return {'key': {'id': 'single-provider-id'}}

    def run_task(name: str, finished: Event) -> None:
        close_old_connections()
        try:
            thread_results[name] = send_outbound_whatsapp_message.run(
                str(message.id),
                channel_id,
            )
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            close_old_connections()
            finished.set()

    with (
        patch(
            'omnichannel.services.send_whatsapp_message',
            side_effect=blocking_send,
        ) as mock_send,
        patch.object(send_outbound_whatsapp_message, 'apply_async') as mock_apply_async,
    ):
        first = Thread(target=run_task, args=('first', first_finished), daemon=True)
        second = Thread(target=run_task, args=('second', second_finished), daemon=True)
        first.start()
        try:
            assert send_started.wait(timeout=10)
            second.start()
            assert second_finished.wait(timeout=10)

            message.refresh_from_db()
            assert message.status == Message.Status.PENDING
            assert message.send_attempt_count == 1
            assert message.send_error_code == ''
            assert mock_send.call_count == 1
            mock_apply_async.assert_called_once_with(
                args=(str(message.id), channel_id),
                countdown=10,
            )
        finally:
            release_send.set()
            first.join(timeout=10)
            if second.ident is not None:
                second.join(timeout=10)

        assert not first.is_alive()
        assert not second.is_alive()
        assert first_finished.is_set()
        assert thread_errors == []

        message.refresh_from_db()
        assert thread_results['first'] == str(message.id)
        assert thread_results['second'] is None
        assert message.status == Message.Status.SENT
        assert message.external_id == 'single-provider-id'
        assert message.send_attempt_count == 1
        assert Message.objects.filter(conversation=message.conversation).count() == 1

        later_result = send_outbound_whatsapp_message.run(
            str(message.id),
            channel_id,
        )

    message.refresh_from_db()
    assert later_result == str(message.id)
    assert message.status == Message.Status.SENT
    assert message.send_attempt_count == 1
    assert mock_send.call_count == 1


@pytest.mark.django_db
@pytest.mark.parametrize('advanced_status', [Message.Status.DELIVERED, Message.Status.READ])
def test_late_delivery_failure_does_not_downgrade_advanced_status(
    advanced_status: str,
) -> None:
    message = _outbound_message()

    def advance_then_fail(**kwargs):
        Message.objects.filter(id=message.id).update(
            status=advanced_status,
            external_id='status-webhook-provider-id',
        )
        raise EvolutionAuthenticationError()

    with patch(
        'omnichannel.services.send_whatsapp_message',
        side_effect=advance_then_fail,
    ):
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == advanced_status
    assert message.external_id == 'status-webhook-provider-id'
    assert message.send_attempt_count == 1


@pytest.mark.django_db
@pytest.mark.parametrize('advanced_status', [Message.Status.DELIVERED, Message.Status.READ])
def test_late_delivery_success_does_not_downgrade_advanced_status(
    advanced_status: str,
) -> None:
    message = _outbound_message()

    def advance_then_succeed(**kwargs):
        Message.objects.filter(id=message.id).update(
            status=advanced_status,
            external_id='status-webhook-provider-id',
        )
        return {'key': {'id': 'late-task-provider-id'}}

    with patch(
        'omnichannel.services.send_whatsapp_message',
        side_effect=advance_then_succeed,
    ):
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == advanced_status
    assert message.external_id == 'status-webhook-provider-id'
    assert message.send_attempt_count == 1
