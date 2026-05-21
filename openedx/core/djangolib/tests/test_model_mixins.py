"""
Tests for model_mixins.py.
"""

from unittest import TestCase, mock

from openedx.core.djangolib.model_mixins import DeletableByUserValue


class TestDeletableByUserValue(TestCase):
    """
    Unit tests for DeletableByUserValue.
    """

    class NonRedactingModel(DeletableByUserValue):
        """
        Dummy model that uses default redaction behavior.
        """

    class RedactingModel(DeletableByUserValue):
        """
        Dummy model that overrides redaction fields.
        """

        @classmethod
        def redact_before_delete_fields(cls):
            return {'email': 'redacted@retired.invalid'}

    def _mock_queryset_for(self, model_cls, exists):
        """
        Attach a mocked queryset to ``model_cls`` and return it.
        """
        queryset = mock.Mock()
        queryset.exists.return_value = exists
        queryset.values_list.return_value = [11, 12]
        model_cls.objects = mock.Mock()
        model_cls.objects.filter.return_value = queryset
        return queryset

    def test_redact_before_delete_fields_defaults_to_empty_dict(self):
        """
        Verify the default redaction hook does not request any field updates.
        """
        assert not self.NonRedactingModel.redact_before_delete_fields()

    def test_delete_by_user_value_returns_false_when_no_matches(self):
        """
        Verify no updates or deletes occur when no rows match the filter.
        """
        queryset = self._mock_queryset_for(self.NonRedactingModel, exists=False)

        was_deleted = self.NonRedactingModel.delete_by_user_value(value='missing@example.com', field='email')

        assert not was_deleted
        self.NonRedactingModel.objects.filter.assert_called_once_with(email='missing@example.com')
        queryset.update.assert_not_called()
        queryset.delete.assert_not_called()

    def test_delete_by_user_value_deletes_without_redaction_by_default(self):
        """
        Verify matching rows are deleted directly when no redaction is configured.
        """
        queryset = self._mock_queryset_for(self.NonRedactingModel, exists=True)

        was_deleted = self.NonRedactingModel.delete_by_user_value(value='learner@example.com', field='email')

        assert was_deleted
        assert self.NonRedactingModel.objects.filter.call_args_list == [
            mock.call(email='learner@example.com'),
            mock.call(id__in=[11, 12]),
        ]
        queryset.update.assert_not_called()
        queryset.delete.assert_called_once_with()

    def test_delete_by_user_value_redacts_before_delete_when_overridden(self):
        """
        Verify redaction updates are applied before delete when configured.
        """
        queryset = self._mock_queryset_for(self.RedactingModel, exists=True)

        was_deleted = self.RedactingModel.delete_by_user_value(value='learner@example.com', field='email')

        assert was_deleted
        assert self.RedactingModel.objects.filter.call_args_list == [
            mock.call(email='learner@example.com'),
            mock.call(id__in=[11, 12]),
            mock.call(id__in=[11, 12]),
        ]
        queryset.update.assert_called_once_with(email='redacted@retired.invalid')
        queryset.delete.assert_called_once_with()
