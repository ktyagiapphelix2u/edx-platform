"""
Django Signal related functionality for user_api accounts
"""

import logging

from django.db.models.signals import pre_delete
from django.dispatch import Signal, receiver
from social_django.models import UserSocialAuth

logger = logging.getLogger(__name__)

# Signal to retire a user from LMS-initiated mailings (course mailings, etc)
# providing_args=["user"]
USER_RETIRE_MAILINGS = Signal()

# Signal to retire LMS critical information
# providing_args=["user", "retired_username", "retired_email"]
USER_RETIRE_LMS_CRITICAL = Signal()

# Signal to retire LMS misc information
# providing_args=["user"]
USER_RETIRE_LMS_MISC = Signal()


@receiver(pre_delete, sender=UserSocialAuth)
def redact_social_auth_pii_before_deletion(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """
    Signal handler to redact PII from UserSocialAuth records before deletion.

    This ensures that when SSO records are deleted (either via user retirement, manual unlinking,
    or any other method), PII is redacted first. This prevents downstream systems that maintain
    soft-deleted records from retaining sensitive user information.

    The redacted state is saved before the actual deletion happens. This is intentional -
    downstream systems will capture the redacted state before marking the record as deleted.

    If redaction fails, the exception is re-raised to prevent deletion from proceeding,
    ensuring GDPR compliance and preventing PII leaks to downstream systems.
    """
    if not instance or not instance.pk:
        return

    try:
        update_fields = {}
        redacted_uid = f'redacted_{instance.pk}@retired.invalid'

        if instance.uid != redacted_uid:
            update_fields['uid'] = redacted_uid
        if instance.extra_data:
            update_fields['extra_data'] = {}

        if not update_fields:
            return

        UserSocialAuth.objects.filter(pk=instance.pk).update(**update_fields)
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "Failed to redact PII for UserSocialAuth before deletion: user_id=%s, provider=%s",
            instance.user_id,
            instance.provider,
        )
        # Re-raise to prevent deletion from proceeding without redaction
        raise
