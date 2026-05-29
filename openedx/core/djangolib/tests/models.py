"""
Test-only Django models for openedx.core.djangolib.
"""

from django.db import models

from openedx.core.djangolib.model_mixins import DeletableByUserValue


class DeletableByUserValueTestModel(DeletableByUserValue, models.Model):
    """
    Test model that uses DeletableByUserValue with redaction.
    """
    email = models.CharField(max_length=255)
    username = models.CharField(max_length=255)
    user = models.CharField(max_length=255)

    class Meta:
        app_label = 'djangolib_tests'

    @classmethod
    def redact_before_delete_fields(cls):
        return {
            'email': 'redacted-before-delete@safe.com',
            'username': 'redacted-before-delete',
        }
