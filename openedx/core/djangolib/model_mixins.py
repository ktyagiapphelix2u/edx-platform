"""
Custom Django Model mixins.
"""


class DeprecatedModelMixin:
    """
    Used to make a class unusable in practice, but leave database tables intact.
    """
    def __init__(self, *args, **kwargs):  # pylint: disable=unused-argument
        """
        Override to kill usage of this model.
        """
        raise TypeError("This model has been deprecated and should not be used.")


class DeletableByUserValue:
    """
    This mixin allows inheriting models to delete instances of the model
    associated with some specified user.
    """

    @classmethod
    def redact_before_delete_fields(cls):
        """
        Returns dict of PII fields and their redacted values.

        Always returns an empty dict unless overridden by the inheriting model.
        Results are used by ``delete_by_user_value`` to redact PII before delete.
        """
        return {}

    @classmethod
    def delete_by_user_value(cls, value, field):
        """
        Redacts and deletes instances of this model where ``field`` equals ``value``.

        e.g.
            ``delete_by_user_value(value='learner@example.com', field='email')``

        If ``redact_before_delete_fields`` returns a non-empty dict, matching
        records are bulk-updated with those redacted values before delete.

        Returns True if any instances were deleted.
        Returns False otherwise.
        """
        filter_kwargs = {field: value}
        record_ids = list(cls.objects.filter(**filter_kwargs).values_list('id', flat=True))
        if not record_ids:
            return False

        queryset_to_delete = cls.objects.filter(id__in=record_ids)
        redact_fields = cls.redact_before_delete_fields()
        if redact_fields:
            queryset_to_delete.update(**redact_fields)
        queryset_to_delete.delete()
        return True
