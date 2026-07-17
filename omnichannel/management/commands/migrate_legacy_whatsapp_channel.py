from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from omnichannel.legacy_channel_migration import (
    DEFAULT_LEGACY_CHANNEL_NAME,
    LegacyChannelMigrationError,
    LegacyChannelMigrationResult,
    migrate_legacy_channel,
)


class Command(BaseCommand):
    help = 'Migra explicitamente a instancia WhatsApp legada para um Workspace.'

    def add_arguments(self, parser: ArgumentParser | CommandParser) -> None:
        parser.add_argument(
            '--workspace-id',
            required=True,
            help='UUID do Workspace proprietario da instancia legada.',
        )
        parser.add_argument(
            '--instance-name',
            default=None,
            help='Instancia legada; usa EVOLUTION_INSTANCE_NAME quando omitida.',
        )
        parser.add_argument(
            '--channel-name',
            default=DEFAULT_LEGACY_CHANNEL_NAME,
            help='Nome local do canal legado.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra o plano sem persistir alteracoes.',
        )
        parser.add_argument(
            '--rollback',
            action='store_true',
            help='Remove somente as associacoes de conversas com o canal legado.',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        instance_name = self._resolve_instance_name(options.get('instance_name'))

        try:
            result = migrate_legacy_channel(
                workspace_id=options['workspace_id'],
                instance_name=instance_name,
                channel_name=options['channel_name'],
                dry_run=options['dry_run'],
                rollback=options['rollback'],
            )
        except LegacyChannelMigrationError as exc:
            raise CommandError(str(exc)) from exc

        self._write_result(result)

    @staticmethod
    def _resolve_instance_name(option_value: str | None) -> str:
        raw_value = (
            option_value
            if option_value is not None
            else getattr(settings, 'EVOLUTION_INSTANCE_NAME', '')
        )
        instance_name = str(raw_value or '').strip()
        if not instance_name:
            raise CommandError(
                'Informe --instance-name ou configure EVOLUTION_INSTANCE_NAME.',
            )
        return instance_name

    def _write_result(self, result: LegacyChannelMigrationResult) -> None:
        channel_labels = {
            'created': 'criado',
            'reused': 'reutilizado',
            'would_create': 'seria criado',
            'located': 'localizado',
        }
        self.stdout.write(f'Workspace: {result.workspace_id}')
        self.stdout.write(f'Instancia legada: {result.instance_name}')
        self.stdout.write(
            f'Canal: {channel_labels.get(result.channel_state, result.channel_state)}',
        )
        if result.channel_id is not None:
            self.stdout.write(f'Canal ID: {result.channel_id}')

        if result.rollback:
            self.stdout.write(
                f'Conversas associadas ao canal: {result.eligible_count}',
            )
            self.stdout.write(f'Conversas desvinculadas: {result.updated_count}')
            self.stdout.write('Canal preservado: sim')
        else:
            self.stdout.write(f'Conversas elegiveis: {result.eligible_count}')
            self.stdout.write(f'Conversas associadas: {result.updated_count}')

        self.stdout.write(f'Conversas ignoradas: {result.ignored_count}')
        self.stdout.write(f'Dry-run: {"sim" if result.dry_run else "nao"}')
        self.stdout.write(f'Rollback: {"sim" if result.rollback else "nao"}')
