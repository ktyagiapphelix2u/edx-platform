"""
Tests for model_mixins.py.
"""

from unittest import TestCase, mock

import ddt

from openedx.core.djangolib.model_mixins import DeletableByUserValue


@ddt.ddt
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
            return {
                'email': 'redacted-before-delete@safe.com',
                'username': 'redacted-before-delete',
            }

    def _make_queryset(self, exists):
        """
        Return a mock queryset with ``exists`` and ``values_list`` pre-configured.
        """
        queryset = mock.Mock()
        queryset.exists.return_value = exists
        queryset.values_list.return_value = [11, 12]
        return queryset

    def test_redact_before_delete_fields_defaults_to_empty_dict(self):
        """
        Verify the default redaction hook does not request any field updates.
        """
        assert not self.NonRedactingModel.redact_before_delete_fields()

    @mock.patch.object(NonRedactingModel, 'objects', create=True)
    def test_delete_by_user_value_returns_false_when_no_matches(self, mock_objects):
        """
        Verify no updates or deletes occur when no rows match the filter.
        """
        queryset = self._make_queryset(exists=False)
        mock_objects.filter.return_value = queryset

        was_deleted = self.NonRedactingModel.delete_by_user_value(value='missing@example.com', field='email')

        assert not was_deleted
        mock_objects.filter.assert_called_once_with(email='missing@example.com')
        queryset.update.assert_not_called()
        queryset.delete.assert_not_called()

    _REDACT_FIELDS = {
        'email': 'redacted-before-delete@safe.com',
        'username': 'redacted-before-delete',
    }

    @ddt.data(
        # No redaction: delete directly on the original queryset.
        ('NonRedactingModel', 'email', None, False),
        # Filter field IS in redact_fields: must use ID-based path so the DELETE
        # still targets the same rows after the UPDATE changes the filter field.
        ('RedactingModel', 'email', _REDACT_FIELDS, True),
        # Filter field is NOT in redact_fields: simple update+delete on the
        # original queryset works fine (filter field is unchanged by the UPDATE).
        ('RedactingModel', 'user', _REDACT_FIELDS, False),
    )
    @ddt.unpack
    def test_delete_by_user_value(self, model_name, field, expected_redact_fields, uses_id_based_lookup):
        """
        Verify delete behavior with and without redaction configured.

        When no redaction hook is set, rows are deleted directly.
        When the filter field is also being redacted, IDs are captured first so
        the DELETE targets the same rows after the UPDATE changes the filter value.
        When redaction fields do not include the filter field, the original
        queryset is used for both update and delete.
        """
        model_cls = getattr(self, model_name)
        queryset = self._make_queryset(exists=True)
        with mock.patch.object(model_cls, 'objects', create=True) as mock_objects:
            mock_objects.filter.return_value = queryset

            was_deleted = model_cls.delete_by_user_value(value='learner@example.com', field=field)

        assert was_deleted
        if uses_id_based_lookup:
            assert mock_objects.filter.call_args_list == [
                mock.call(**{field: 'learner@example.com'}),
                mock.call(id__in=[11, 12]),
            ]
            queryset.update.assert_called_once_with(**expected_redact_fields)
        elif expected_redact_fields:
            mock_objects.filter.assert_called_once_with(**{field: 'learner@example.com'})
            queryset.update.assert_called_once_with(**expected_redact_fields)
        else:
            mock_objects.filter.assert_called_once_with(**{field: 'learner@example.com'})
            queryset.update.assert_not_called()
        queryset.delete.assert_called_once_with()
