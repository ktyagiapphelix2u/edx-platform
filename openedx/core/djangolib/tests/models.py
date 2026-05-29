"""
Test-only Django models for openedx.core.djangolib.
"""

from django.db import models

from openedx.core.djangolib.model_mixins import DeletableByUserValue


class NonRedactingModel(DeletableByUserValue, models.Model):
    """
    Model that uses default (empty) redaction behavior.
    """
    user_id = models.IntegerField()

    class Meta:
        app_label = 'djangolib_tests'

    def __str__(self):
        return str(self.user_id)


class RedactingModel(DeletableByUserValue, models.Model):
    """
    Model that overrides redaction fields.
    """
    email = models.CharField(max_length=255)
    username = models.CharField(max_length=255)
    user = models.CharField(max_length=255)

    class Meta:
        app_label = 'djangolib_tests'

    def __str__(self):
        return self.email

    @classmethod
    def redact_before_delete_fields(cls):
        return {
            'email': 'redacted-before-delete@safe.com',
            'username': 'redacted-before-delete',
        }
