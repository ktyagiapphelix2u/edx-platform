"""
Tests for model_mixins.py.
"""

import ddt
from django.test import TestCase

from openedx.core.djangolib.tests.models import NonRedactingModel, RedactingModel


@ddt.ddt
class TestDeletableByUserValue(TestCase):
    """
    Unit tests for DeletableByUserValue.
    """

    def test_redact_before_delete_fields_defaults_to_empty_dict(self):
        """
        Verify the default redaction hook returns an empty dict.
        """
        assert not NonRedactingModel.redact_before_delete_fields()

    def test_delete_by_user_value_returns_false_when_no_matches(self):
        """
        Verify no deletes occur when no rows match the filter.
        """
        was_deleted = NonRedactingModel.delete_by_user_value(value=999, field='user_id')

        assert not was_deleted
        assert NonRedactingModel.objects.count() == 0

    def test_delete_by_user_value_non_redacting(self):
        """
        Verify delete works without redaction — rows are simply deleted.
        """
        NonRedactingModel.objects.create(user_id=1)
        NonRedactingModel.objects.create(user_id=1)
        NonRedactingModel.objects.create(user_id=2)

        was_deleted = NonRedactingModel.delete_by_user_value(value=1, field='user_id')

        assert was_deleted
        assert NonRedactingModel.objects.count() == 1
        assert NonRedactingModel.objects.first().user_id == 2

    @ddt.data(
        ('email', 'learner@example.com'),
        ('user', 'learner_user'),
    )
    @ddt.unpack
    def test_delete_by_user_value_redacting(self, field, filter_value):
        """
        Verify matching rows are redacted and deleted; unrelated rows remain.
        """
        RedactingModel.objects.create(email='learner@example.com', username='learner', user='learner_user')
        RedactingModel.objects.create(email='learner@example.com', username='learner2', user='learner_user')
        RedactingModel.objects.create(email='other@example.com', username='other', user='other_user')

        was_deleted = RedactingModel.delete_by_user_value(value=filter_value, field=field)

        assert was_deleted
        assert RedactingModel.objects.count() == 1
        remaining = RedactingModel.objects.first()
        assert remaining.email == 'other@example.com'
        assert remaining.username == 'other'

