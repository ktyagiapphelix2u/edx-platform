"""
Test the retire_user management command
"""


import csv
import os

import pytest
from django.contrib.auth.models import User  # lint-amnesty, pylint: disable=imported-auth-user
from django.core.management import CommandError, call_command
from django.db.models.signals import pre_delete
from social_django.models import UserSocialAuth

from common.djangoapps.student.tests.factories import UserFactory  # lint-amnesty, pylint: disable=wrong-import-order
from openedx.core.djangoapps.user_api.accounts.tests.retirement_helpers import (  # lint-amnesty, pylint: disable=unused-import, wrong-import-order
    setup_retirement_states,  # noqa: F401
)
from openedx.core.djangolib.testing.utils import skip_unless_lms  # lint-amnesty, pylint: disable=wrong-import-order

from ...accounts.signals import REDACTED_SOCIAL_AUTH_UID_PREFIX, REDACTED_SOCIAL_AUTH_UID_SUFFIX
from ...models import UserRetirementStatus

pytestmark = pytest.mark.django_db
user_file = 'userfile.csv'


def generate_dummy_users():
    """
    Function to generate dummy users that needs to be retired
    """
    users = []
    emails = []
    for i in range(1000):
        user = UserFactory.create(username=f"user{i}", email=f"user{i}@example.com")
        users.append(user.username)
        emails.append(user.email)
    users_list = [{'username': user, 'email': email} for user, email in zip(users, emails)]  # noqa: B905
    return users_list


def create_user_file(other_email=False):
    """
    Function to create a comma spearated file with username and password

    Args:
        other_email (bool, optional): test user with email mimatch. Defaults to False.
    """
    users_to_retire = generate_dummy_users()
    if other_email:
        users_to_retire[0]['email'] = "other@edx.org"
    with open(user_file, 'w', newline='') as file:
        write = csv.writer(file)
        for user in users_to_retire:
            write.writerow(user.values())


def remove_user_file():
    """
    Function to remove user file
    """
    if os.path.exists(user_file):
        os.remove(user_file)


@skip_unless_lms
def test_successful_retire_with_userfile(setup_retirement_states):  # lint-amnesty, pylint: disable=redefined-outer-name, unused-argument  # noqa: F811
    user = UserFactory.create(username='user0', email="user0@example.com")
    username = user.username
    user_email = user.email
    create_user_file()
    call_command('retire_user', user_file=user_file)
    user = User.objects.get(username=username)
    retired_user_status = UserRetirementStatus.objects.all()[0]
    assert retired_user_status.original_username == username
    assert retired_user_status.original_email == user_email
    # Make sure that we have changed the email address linked to the original user
    assert user.email != user_email
    remove_user_file()


@skip_unless_lms
def test_retire_user_with_usename_email_mismatch(setup_retirement_states):  # lint-amnesty, pylint: disable=redefined-outer-name, unused-argument  # noqa: F811
    create_user_file(True)
    with pytest.raises(CommandError, match=r'Could not find users with specified username and email '):
        call_command('retire_user', user_file=user_file)
    remove_user_file()


@skip_unless_lms
def test_successful_retire_with_username_email(setup_retirement_states):  # lint-amnesty, pylint: disable=redefined-outer-name, unused-argument  # noqa: F811
    user = UserFactory.create(username='user0', email="user0@example.com")
    username = user.username
    user_email = user.email
    call_command('retire_user', username=username, user_email=user_email)
    user = User.objects.get(username=username)
    retired_user_status = UserRetirementStatus.objects.all()[0]
    assert retired_user_status.original_username == username
    assert retired_user_status.original_email == user_email
    # Make sure that we have changed the email address linked to the original user
    assert user.email != user_email


@skip_unless_lms
def test_retire_with_username_email_userfile(setup_retirement_states):  # lint-amnesty, pylint: disable=redefined-outer-name, unused-argument  # noqa: F811
    user = UserFactory.create(username='user0', email="user0@example.com")
    username = user.username
    user_email = user.email
    create_user_file(True)
    with pytest.raises(CommandError, match=r'You cannot use userfile option with username and user_email'):
        call_command('retire_user', user_file=user_file, username=username, user_email=user_email)
    remove_user_file()


@skip_unless_lms
def test_retire_user_redacts_sso_pii_before_deletion(setup_retirement_states):  # lint-amnesty, pylint: disable=redefined-outer-name, unused-argument  # noqa: F811
    """
    Test that SSO PII is redacted before UserSocialAuth records are deleted during retirement.

    This test verifies the order of operations by capturing the record's state
    at the moment of deletion to ensure it was already redacted.
    """
    user = UserFactory.create(username='sso-user', email='sso-user@example.com')
    social_auth = UserSocialAuth.objects.create(
        user=user,
        provider='google-oauth2',
        uid='sso-user@example.com',
        extra_data={
            'email': 'sso-user@example.com',
            'name': 'SSO Test User',
            'id': '123456789',
        }
    )
    social_auth_id = social_auth.id

    captured_states = []

    def capture_state_before_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
        """Capture the database state seen by the pre_delete signal."""
        instance.refresh_from_db()
        captured_states.append({
            'id': instance.id,
            'uid': instance.uid,
            'extra_data': dict(instance.extra_data) if instance.extra_data else {},
        })

    pre_delete.connect(capture_state_before_delete, sender=UserSocialAuth)
    try:
        call_command('retire_user', username=user.username, user_email=user.email)
    finally:
        pre_delete.disconnect(capture_state_before_delete, sender=UserSocialAuth)

    # Verify that at the moment of deletion, the record was already redacted
    assert captured_states == [{
        'id': social_auth_id,
        'uid': f'{REDACTED_SOCIAL_AUTH_UID_PREFIX}{social_auth_id}{REDACTED_SOCIAL_AUTH_UID_SUFFIX}',
        'extra_data': {},
    }], \
        "SSO records should be redacted before deletion"

    # Verify deletion completed
    assert not UserSocialAuth.objects.filter(id=social_auth_id).exists()

    retired_user_status = UserRetirementStatus.objects.filter(original_username=user.username).first()
    assert retired_user_status is not None
    assert retired_user_status.original_email == 'sso-user@example.com'


@skip_unless_lms
def test_retire_user_redacts_each_social_auth_before_bulk_deletion(setup_retirement_states):  # lint-amnesty, pylint: disable=redefined-outer-name, unused-argument  # noqa: F811
    """
    Test that each UserSocialAuth record is redacted before bulk deletion during retirement.
    """
    user = UserFactory.create(username='multi-sso-user', email='multi-sso@example.com')
    google_auth = UserSocialAuth.objects.create(
        user=user,
        provider='google-oauth2',
        uid='google-multi@example.com',
        extra_data={'email': 'google-multi@example.com', 'name': 'Google User'}
    )
    saml_auth = UserSocialAuth.objects.create(
        user=user,
        provider='tpa-saml',
        uid='saml-multi@example.com',
        extra_data={'email': 'saml-multi@example.com', 'name': 'SAML User', 'uid': 'saml-123'}
    )
    # Save IDs before deletion (they become None after delete)
    google_auth_id = google_auth.id
    saml_auth_id = saml_auth.id

    captured_states = []

    def capture_state_before_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
        """Capture the database state seen by the pre_delete signal."""
        instance.refresh_from_db()
        extra = dict(instance.extra_data) if instance.extra_data else {}
        captured_states.append((instance.provider, instance.uid, extra))

    pre_delete.connect(capture_state_before_delete, sender=UserSocialAuth)
    try:
        call_command('retire_user', username=user.username, user_email=user.email)
    finally:
        pre_delete.disconnect(capture_state_before_delete, sender=UserSocialAuth)

    assert sorted(captured_states) == sorted([
        ('google-oauth2', f'{REDACTED_SOCIAL_AUTH_UID_PREFIX}{google_auth_id}{REDACTED_SOCIAL_AUTH_UID_SUFFIX}', {}),
        ('tpa-saml', f'{REDACTED_SOCIAL_AUTH_UID_PREFIX}{saml_auth_id}{REDACTED_SOCIAL_AUTH_UID_SUFFIX}', {}),
    ])
