"""
Test the retire_user management command
"""


import csv
import os
from unittest import mock

import pytest
from django.contrib.auth.models import User  # lint-amnesty, pylint: disable=imported-auth-user
from django.core.management import CommandError, call_command
from social_django.models import UserSocialAuth

from common.djangoapps.student.tests.factories import UserFactory  # lint-amnesty, pylint: disable=wrong-import-order
from openedx.core.djangoapps.user_api.accounts.tests.retirement_helpers import (  # lint-amnesty, pylint: disable=unused-import, wrong-import-order
    setup_retirement_states,  # noqa: F401
)
from openedx.core.djangolib.testing.utils import skip_unless_lms  # lint-amnesty, pylint: disable=wrong-import-order

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

    # Capture the state at the moment of deletion to verify redaction happened first
    captured_state = {}
    original_delete = UserSocialAuth.delete

    def capture_state_and_delete(self):
        """Wrapper to capture state before deletion."""
        # Refresh from database to get the actual current state
        self.refresh_from_db()
        captured_state['uid'] = self.uid
        captured_state['extra_data'] = dict(self.extra_data) if self.extra_data else {}
        # Call original delete
        return original_delete(self)

    with mock.patch.object(UserSocialAuth, 'delete', capture_state_and_delete):
        call_command('retire_user', username=user.username, user_email=user.email)

    # Verify that at the moment of deletion, the record was already redacted
    assert captured_state['uid'] == f'redacted_{social_auth_id}@retired.invalid', \
        "UID should be redacted before deletion"
    assert captured_state['extra_data'] == {}, \
        "extra_data should be empty before deletion"

    # Verify deletion completed
    assert not UserSocialAuth.objects.filter(id=social_auth_id).exists()
    
    retired_user_status = UserRetirementStatus.objects.filter(original_username=user.username).first()
    assert retired_user_status is not None
    assert retired_user_status.original_email == 'sso-user@example.com'


@skip_unless_lms
def test_retire_user_calls_redaction_for_each_social_auth(setup_retirement_states):  # lint-amnesty, pylint: disable=redefined-outer-name, unused-argument  # noqa: F811
    """
    Test that redact_user_social_auth_pii is called for each UserSocialAuth record during retirement.
    """
    user = UserFactory.create(username='multi-sso-user', email='multi-sso@example.com')
    UserSocialAuth.objects.create(
        user=user,
        provider='google-oauth2',
        uid='google-multi@example.com',
        extra_data={'email': 'google-multi@example.com', 'name': 'Google User'}
    )
    UserSocialAuth.objects.create(
        user=user,
        provider='tpa-saml',
        uid='saml-multi@example.com',
        extra_data={'email': 'saml-multi@example.com', 'name': 'SAML User', 'uid': 'saml-123'}
    )

    with mock.patch(
        'openedx.core.djangoapps.user_api.management.commands.retire_user.redact_user_social_auth_pii'
    ) as mock_redact:
        call_command('retire_user', username=user.username, user_email=user.email)

    assert mock_redact.call_count == 2
