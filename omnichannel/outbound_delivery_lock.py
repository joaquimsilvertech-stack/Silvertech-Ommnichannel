"""PostgreSQL advisory lock for outbound delivery concurrency control."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS, connections


class OutboundDeliveryLockError(ValueError):
    """Raised when an outbound delivery lock cannot be safely requested."""


@dataclass(frozen=True)
class OutboundDeliveryLock:
    acquired: bool
    key: int


def derive_outbound_delivery_lock_key(message_id: UUID | str) -> int:
    """Derive a deterministic signed 64-bit key from a technical Message UUID."""
    try:
        normalized_message_id = (
            message_id if isinstance(message_id, UUID) else UUID(str(message_id))
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise OutboundDeliveryLockError('Invalid outbound message identifier.') from exc

    digest = hashlib.sha256(
        b'silvertech:outbound-delivery:' + normalized_message_id.bytes,
    ).digest()
    return int.from_bytes(digest[:8], byteorder='big', signed=True)


@contextmanager
def acquire_outbound_delivery_lock(
    message_id: UUID | str,
    *,
    using: str = DEFAULT_DB_ALIAS,
) -> Iterator[OutboundDeliveryLock]:
    """Try to hold a session-level advisory lock until the context exits."""
    lock_key = derive_outbound_delivery_lock_key(message_id)
    database_connection = connections[using]
    if database_connection.vendor != 'postgresql':
        raise OutboundDeliveryLockError(
            'Outbound delivery advisory locks require PostgreSQL.',
        )

    acquired = False
    with database_connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [lock_key])
        row = cursor.fetchone()
        acquired = bool(row and row[0])

    try:
        yield OutboundDeliveryLock(acquired=acquired, key=lock_key)
    finally:
        if acquired:
            with database_connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [lock_key])

