"""
One-time cleanup: clear PII and delete ManualVerification rows for retired users.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from lms.djangoapps.verify_student.models import ManualVerification

log = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Clears PII then deletes ManualVerification records belonging to retired users.

    Only runs when REDACT_MANUAL_VERIFICATION_HISTORICAL_PII is True.

    Example usage:
        $ ./manage.py lms cleanup_retired_manual_verifications
        $ ./manage.py lms cleanup_retired_manual_verifications --dry-run
    """

    help = 'Clear PII and delete ManualVerification rows for retired users.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Log what would be deleted without making any changes.',
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'REDACT_MANUAL_VERIFICATION_HISTORICAL_PII', False):
            self.stdout.write(
                'REDACT_MANUAL_VERIFICATION_HISTORICAL_PII is not enabled. Skipping.'
            )
            return

        dry_run = options['dry_run']

        retired_records = ManualVerification.objects.filter(
            user__userretirementrequest__isnull=False,
        )

        count = retired_records.count()
        if count == 0:
            self.stdout.write('No retired ManualVerification records found.')
            return

        log.info('Found %d ManualVerification record(s) for retired users.', count)

        if dry_run:
            self.stdout.write(f'[dry-run] Would clear PII and delete {count} record(s). No changes made.')
            return

        retired_records.update(name='')
        deleted_count, _ = retired_records.delete()
        log.info('Deleted %d ManualVerification record(s) for retired users.', deleted_count)
        self.stdout.write(self.style.SUCCESS(f'Successfully deleted {deleted_count} record(s).'))
