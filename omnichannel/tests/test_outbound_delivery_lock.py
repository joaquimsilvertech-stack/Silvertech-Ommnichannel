from __future__ import annotations

import inspect
from threading import Event, Thread
from uuid import UUID, uuid4
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection, connections

from omnichannel.outbound_delivery_lock import (
    OutboundDeliveryLockError,
    acquire_outbound_delivery_lock,
    derive_outbound_delivery_lock_key,
)


def test_same_message_id_derives_same_lock_key() -> None:
    message_id = uuid4()

    assert derive_outbound_delivery_lock_key(message_id) == (
        derive_outbound_delivery_lock_key(str(message_id))
    )


def test_different_message_ids_derive_different_lock_keys() -> None:
    first_id = UUID('00000000-0000-0000-0000-000000000001')
    second_id = UUID('00000000-0000-0000-0000-000000000002')

    assert derive_outbound_delivery_lock_key(first_id) != (
        derive_outbound_delivery_lock_key(second_id)
    )


@pytest.mark.parametrize(
    'message_id',
    [
        UUID(int=0),
        UUID(int=1),
        UUID('ffffffff-ffff-ffff-ffff-ffffffffffff'),
        uuid4(),
    ],
)
def test_lock_key_fits_postgresql_signed_bigint(message_id: UUID) -> None:
    lock_key = derive_outbound_delivery_lock_key(message_id)

    assert -(2**63) <= lock_key <= (2**63) - 1


@pytest.mark.django_db(transaction=True)
def test_second_database_session_cannot_acquire_held_lock_and_unlock_allows_reacquire() -> None:
    if connection.vendor != 'postgresql':
        pytest.skip('PostgreSQL advisory lock test.')

    message_id = uuid4()
    holder_ready = Event()
    release_holder = Event()
    holder_results: list[bool] = []
    holder_errors: list[BaseException] = []

    def hold_lock() -> None:
        close_old_connections()
        try:
            with acquire_outbound_delivery_lock(message_id) as delivery_lock:
                holder_results.append(delivery_lock.acquired)
                holder_ready.set()
                if not release_holder.wait(timeout=10):
                    raise AssertionError('Timed out waiting to release advisory lock.')
        except BaseException as exc:
            holder_errors.append(exc)
            holder_ready.set()
        finally:
            close_old_connections()

    holder = Thread(target=hold_lock, daemon=True)
    holder.start()
    try:
        assert holder_ready.wait(timeout=10)
        assert holder_errors == []
        assert holder_results == [True]

        with acquire_outbound_delivery_lock(message_id) as contended_lock:
            assert contended_lock.acquired is False
    finally:
        release_holder.set()
        holder.join(timeout=10)

    assert not holder.is_alive()
    assert holder_errors == []

    with acquire_outbound_delivery_lock(message_id) as reacquired_lock:
        assert reacquired_lock.acquired is True


@pytest.mark.django_db(transaction=True)
def test_lock_is_released_when_context_raises() -> None:
    if connection.vendor != 'postgresql':
        pytest.skip('PostgreSQL advisory lock test.')

    message_id = uuid4()
    with pytest.raises(RuntimeError, match='controlled failure'):
        with acquire_outbound_delivery_lock(message_id) as delivery_lock:
            assert delivery_lock.acquired is True
            raise RuntimeError('controlled failure')

    with acquire_outbound_delivery_lock(message_id) as reacquired_lock:
        assert reacquired_lock.acquired is True


def test_invalid_message_id_fails_before_opening_cursor() -> None:
    with (
        patch.object(connections['default'], 'cursor') as mock_cursor,
        pytest.raises(OutboundDeliveryLockError, match='Invalid outbound message identifier'),
    ):
        with acquire_outbound_delivery_lock('not-a-message-id'):
            pass

    mock_cursor.assert_not_called()


def test_lock_derivation_contains_no_pii_and_uses_no_table_or_migration() -> None:
    source = inspect.getsource(
        __import__(
            'omnichannel.outbound_delivery_lock',
            fromlist=['outbound_delivery_lock'],
        ),
    ).lower()

    assert 'phone' not in source
    assert 'message.body' not in source
    assert 'instance_name' not in source
    assert 'instance_token' not in source
    assert 'create table' not in source
    assert 'migration' not in source
    assert 'pg_try_advisory_lock' in source
    assert 'pg_advisory_unlock' in source

