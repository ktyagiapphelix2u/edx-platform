"""
Tests for model_mixins.py.
"""

import ddt
from django.test import TestCase

from openedx.core.djangolib.model_mixins import DeletableByUserValue
from openedx.core.djangolib.tests.models import DeletableByUserValueTestModel


@ddt.ddt
class TestDeletableByUserValue(TestCase):
    """
    Unit tests for DeletableByUserValue.
    """

    def test_redact_before_delete_fields_defaults_to_empty_dict(self):
        """
        Verify the base mixin returns an empty dict by default.
        """
        assert not DeletableByUserValue.redact_before_delete_fields()

    def test_delete_by_user_value_returns_false_when_no_matches(self):
        """
        Verify no deletes occur when no rows match the filter.
        """
        was_deleted = DeletableByUserValueTestModel.delete_by_user_value(value='missing@example.com', field='email')

        assert not was_deleted
        assert DeletableByUserValueTestModel.objects.count() == 0

    @ddt.data(
        ('email', 'learner@example.com'),
        ('user', 'learner_user'),
    )
    @ddt.unpack
    def test_delete_by_user_value(self, field, filter_value):
        """
        Verify matching rows are redacted and deleted; unrelated rows remain.
        """
        DeletableByUserValueTestModel.objects.create(
            email='learner@example.com', username='learner', user='learner_user'
        )
        DeletableByUserValueTestModel.objects.create(
            email='learner@example.com', username='learner2', user='learner_user'
        )
        DeletableByUserValueTestModel.objects.create(
            email='other@example.com', username='other', user='other_user'
        )

        was_deleted = DeletableByUserValueTestModel.delete_by_user_value(value=filter_value, field=field)

        assert was_deleted
        assert DeletableByUserValueTestModel.objects.count() == 1
        remaining = DeletableByUserValueTestModel.objects.first()
        assert remaining.email == 'other@example.com'
        assert remaining.username == 'other'
