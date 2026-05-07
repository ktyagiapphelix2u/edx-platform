"""
Django Signal related functionality for user_api accounts
"""

import logging

from django.db.models.signals import pre_delete
from django.dispatch import Signal, receiver
from social_django.models import UserSocialAuth

logger = logging.getLogger(__name__)

# Prefix and suffix used to build a per-record redacted uid for UserSocialAuth.
# Both the signal handler and bulk retirement code use these to stay in sync.
REDACTED_SOCIAL_AUTH_UID_PREFIX = 'redacted-before-delete-'
REDACTED_SOCIAL_AUTH_UID_SUFFIX = '@safe.com'

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
    Redacts PII fields (uid, extra_data) before UserSocialAuth deletion.

    Replaces uid with REDACTED_SOCIAL_AUTH_UID_PREFIX + pk + REDACTED_SOCIAL_AUTH_UID_SUFFIX
    and clears extra_data.
    Blocks deletion if redaction fails to prevent PII leaks to downstream systems.
    """
    if not instance or not instance.pk:
        return

    try:
        update_fields = {}
        redacted_uid = f'{REDACTED_SOCIAL_AUTH_UID_PREFIX}{instance.pk}{REDACTED_SOCIAL_AUTH_UID_SUFFIX}'

        # These fields may have already been redacted as part of a bulk retirement,
        # so we skip the update if it is already done to reduce query count.
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
