""" Unit tests for custom UserProfile properties. """


import ddt
from completion import models
from completion.test_utils import CompletionWaffleTestMixin
from django.test import TestCase
from django.test.utils import override_settings
from social_django.models import UserSocialAuth

from common.djangoapps.student.models import CourseEnrollment
from common.djangoapps.student.tests.factories import UserFactory
from openedx.core.djangoapps.user_api.accounts.signals import get_redacted_social_auth_uid
from openedx.core.djangoapps.user_api.accounts.utils import (
    retrieve_last_sitewide_block_completed,
)
from openedx.core.djangolib.testing.utils import skip_unless_lms
from xmodule.modulestore.tests.django_utils import (
    SharedModuleStoreTestCase,  # lint-amnesty, pylint: disable=wrong-import-order
)
from xmodule.modulestore.tests.factories import (  # lint-amnesty, pylint: disable=wrong-import-order
    BlockFactory,
    CourseFactory,
)

from ..utils import format_social_link, validate_social_link


@ddt.ddt
class UserAccountSettingsTest(TestCase):
    """Unit tests for setting Social Media Links."""

    def setUp(self):  # lint-amnesty, pylint: disable=useless-super-delegation
        super().setUp()

    def validate_social_link(self, social_platform, link):
        """
        Helper method that returns True if the social link is valid, False if
        the input link fails validation and will throw an error.
        """
        try:
            validate_social_link(social_platform, link)
        except ValueError:
            return False
        return True

    @ddt.data(
        ('facebook', 'www.facebook.com/edX', 'https://www.facebook.com/edX', True),
        ('facebook', 'facebook.com/edX/', 'https://www.facebook.com/edX', True),
        ('facebook', 'HTTP://facebook.com/edX/', 'https://www.facebook.com/edX', True),
        ('facebook', 'www.evilwebsite.com/123', None, False),
        ('x', 'https://www.x.com/edX/', 'https://www.x.com/edX', True),
        ('x', 'https://www.x.com/edX/123s', None, False),
        ('x', 'x.com/edX', 'https://www.x.com/edX', True),
        ('x', 'x.com/edX?foo=bar', 'https://www.x.com/edX?foo=bar', True),
        ('x', 'x.com/test.user', 'https://www.x.com/test.user', True),
        ('linkedin', 'www.linkedin.com/harryrein', None, False),
        ('linkedin', 'www.linkedin.com/in/harryrein-1234', 'https://www.linkedin.com/in/harryrein-1234', True),
        ('linkedin', 'www.evilwebsite.com/123?www.linkedin.com/edX', None, False),
        ('linkedin', '', '', True),
        ('linkedin', None, None, False),
    )
    @ddt.unpack
    @skip_unless_lms
    def test_social_link_input(self, platform_name, link_input, formatted_link_expected, is_valid_expected):
        """
        Verify that social links are correctly validated and formatted.
        """
        assert is_valid_expected == self.validate_social_link(platform_name, link_input)

        assert formatted_link_expected == format_social_link(platform_name, link_input)


@ddt.ddt
class CompletionUtilsTestCase(SharedModuleStoreTestCase, CompletionWaffleTestMixin, TestCase):
    """
    Test completion utility functions
    """
    def setUp(self):
        """
        Creates a test course that can be used for non-destructive tests
        """
        super().setUp()
        self.override_waffle_switch(True)
        self.engaged_user = UserFactory.create()
        self.cruft_user = UserFactory.create()
        self.course = self.create_test_course()
        self.submit_faux_completions()

    def create_test_course(self):
        """
        Create, populate test course.
        """
        course = CourseFactory.create()
        with self.store.bulk_operations(course.id):
            self.chapter = BlockFactory.create(category='chapter', parent=course)
            self.sequential = BlockFactory.create(category='sequential', parent=self.chapter)
            self.vertical1 = BlockFactory.create(category='vertical', parent=self.sequential)
            self.vertical2 = BlockFactory.create(category='vertical', parent=self.sequential)

        if hasattr(self, 'user_one'):
            CourseEnrollment.enroll(self.engaged_user, course.id)
        if hasattr(self, 'user_two'):
            CourseEnrollment.enroll(self.cruft_user, course.id)
        return course

    def submit_faux_completions(self):
        """
        Submit completions (only for user_one)
        """
        for block in self.sequential.get_children():
            models.BlockCompletion.objects.submit_completion(
                user=self.engaged_user,
                block_key=block.location,
                completion=1.0
            )

    @override_settings(LMS_ROOT_URL='test_url:9999')
    def test_retrieve_last_sitewide_block_completed(self):
        """
        Test that the method returns a URL for the "last completed" block
        when sending a user object
        """
        block_url = retrieve_last_sitewide_block_completed(
            self.engaged_user
        )
        empty_block_url = retrieve_last_sitewide_block_completed(
            self.cruft_user
        )
        assert block_url ==\
               'test_url:9999/courses/course-v1:{org}+{course}+{run}/jump_to/'\
               'block-v1:{org}+{course}+{run}+type@vertical+block@{vertical_id}'.format(  # noqa: UP032
                   org=self.course.location.course_key.org,
                   course=self.course.location.course_key.course,
                   run=self.course.location.course_key.run,
                   vertical_id=self.vertical2.location.block_id
               )

        assert empty_block_url is None


@skip_unless_lms
class RedactUserSocialAuthPIITest(TestCase):
    """
    Tests for SSO PII redaction before deletion.
    """

    def setUp(self):
        super().setUp()
        self.user = UserFactory.create(username='testuser', email='testuser@example.com')

    def create_social_auth(self, provider='google-oauth2', uid='user@example.com', extra_data=None):
        """
        Helper method to create UserSocialAuth instances for testing.
        """
        if extra_data is None:
            extra_data = {
                'email': 'user@example.com',
                'name': 'Test User',
                'id': '123456789',
            }
        return UserSocialAuth.objects.create(
            user=self.user,
            provider=provider,
            uid=uid,
            extra_data=extra_data,
        )

    def test_get_redacted_social_auth_uid_format(self):
        """
        Test that get_redacted_social_auth_uid returns the expected string format.

        This is the single source of truth for the redacted uid format.
        If this test breaks, the bulk retirement Concat/Cast in utils.py and
        retire_user.py must also be updated to match.
        """
        assert get_redacted_social_auth_uid(42) == 'redacted-before-delete-42@safe.com'
        assert get_redacted_social_auth_uid(1) == 'redacted-before-delete-1@safe.com'

    def test_delete_redacts_user_social_auth_pii(self):
        """
        Test that deleting social auth redacts uid and extra_data before removal.
        """
        social_auth = self.create_social_auth()
        social_auth_id = social_auth.id

        captured_states = []

        def capture_state_before_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
            instance.refresh_from_db()
            captured_states.append({
                'id': instance.id,
                'uid': instance.uid,
                'extra_data': dict(instance.extra_data) if instance.extra_data else {},
            })

        from django.db.models.signals import pre_delete

        pre_delete.connect(capture_state_before_delete, sender=UserSocialAuth)
        try:
            social_auth.delete()
        finally:
            pre_delete.disconnect(capture_state_before_delete, sender=UserSocialAuth)

        assert captured_states == [{
            'id': social_auth_id,
            'uid': get_redacted_social_auth_uid(social_auth_id),
            'extra_data': {},
        }]
        assert not UserSocialAuth.objects.filter(id=social_auth_id).exists()

    def test_delete_already_redacted_user_social_auth_is_idempotent(self):
        """
        Test that deleting an already redacted social auth keeps the redacted state.
        """
        social_auth = self.create_social_auth()
        social_auth.uid = get_redacted_social_auth_uid(social_auth.pk)
        social_auth.extra_data = {}
        social_auth.save(update_fields=['uid', 'extra_data'])
        social_auth_id = social_auth.id

        captured_states = []

        def capture_state_before_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
            instance.refresh_from_db()
            captured_states.append((instance.uid, instance.extra_data))

        from django.db.models.signals import pre_delete

        pre_delete.connect(capture_state_before_delete, sender=UserSocialAuth)
        try:
            social_auth.delete()
        finally:
            pre_delete.disconnect(capture_state_before_delete, sender=UserSocialAuth)

        assert captured_states == [
            (get_redacted_social_auth_uid(social_auth_id), {}),
        ]
        assert not UserSocialAuth.objects.filter(id=social_auth_id).exists()

    def test_delete_redacts_multiple_sso_providers(self):
        """
        Test that deletion redacts multiple SSO providers before removal.
        """
        auths = [
            self.create_social_auth(
                provider='google-oauth2',
                uid='google@example.com',
                extra_data={'email': 'google@example.com', 'name': 'Google User'}
            ),
            self.create_social_auth(
                provider='tpa-saml',
                uid='saml@example.com',
                extra_data={'email': 'saml@example.com', 'name': 'SAML User', 'uid': 'saml-uid'}
            ),
        ]
        # Save IDs before deletion (they become None after delete)
        auth_ids = [auth.pk for auth in auths]

        captured_states = []

        def capture_state_before_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
            instance.refresh_from_db()
            captured_states.append((instance.provider, instance.uid, instance.extra_data))

        from django.db.models.signals import pre_delete

        pre_delete.connect(capture_state_before_delete, sender=UserSocialAuth)
        try:
            for auth in auths:
                auth.delete()
        finally:
            pre_delete.disconnect(capture_state_before_delete, sender=UserSocialAuth)

        assert sorted(captured_states) == sorted([
            ('google-oauth2', get_redacted_social_auth_uid(auth_ids[0]), {}),
            ('tpa-saml', get_redacted_social_auth_uid(auth_ids[1]), {}),
        ])
