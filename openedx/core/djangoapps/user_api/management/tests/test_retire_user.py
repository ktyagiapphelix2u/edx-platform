"""
Test the retire_user management command
"""


import csv
import os
from contextlib import contextmanager

import pytest
from django.contrib.auth.models import User  # lint-amnesty, pylint: disable=imported-auth-user
from django.core.management import CommandError, call_command
from django.db import connection
from django.db.models.signals import pre_delete
from django.test.utils import CaptureQueriesContext
from social_django.models import UserSocialAuth

from common.djangoapps.student.tests.factories import UserFactory  # lint-amnesty, pylint: disable=wrong-import-order
from openedx.core.djangoapps.user_api.accounts.signals import (  # lint-amnesty, pylint: disable=wrong-import-order
    redact_social_auth_pii_before_deletion,
)
from openedx.core.djangoapps.user_api.accounts.tests.retirement_helpers import (  # lint-amnesty, pylint: disable=unused-import, wrong-import-order
    setup_retirement_states,  # noqa: F401
)
from openedx.core.djangolib.testing.utils import skip_unless_lms  # lint-amnesty, pylint: disable=wrong-import-order

from ...models import UserRetirementStatus

pytestmark = pytest.mark.django_db
user_file = 'userfile.csv'


@contextmanager
def disconnected_social_auth_redaction_signal():
    """
    Temporarily disconnect the fallback signal so these tests exercise the command path.
    """
    pre_delete.disconnect(redact_social_auth_pii_before_deletion, sender=UserSocialAuth)
    try:
        yield
    finally:
        pre_delete.connect(redact_social_auth_pii_before_deletion, sender=UserSocialAuth)


def assert_update_before_delete(sql_list, table='social_auth_usersocialauth'):
    """
    Assert that at least one social auth UPDATE occurs before a DELETE.
    """
    table_key = table.upper()
    update_indices = [i for i, sql in enumerate(sql_list) if 'UPDATE' in sql.upper() and table_key in sql.upper()]
    delete_indices = [i for i, sql in enumerate(sql_list) if 'DELETE' in sql.upper() and table_key in sql.upper()]
    assert update_indices, f'Expected at least one UPDATE on {table}'
    assert delete_indices, f'Expected at least one DELETE on {table}'
    assert any(update_idx < delete_idx for update_idx in update_indices for delete_idx in delete_indices), (
        'Expected at least one UPDATE to precede at least one DELETE'
    )


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

    The safety-net pre_delete signal handler is disconnected for this test so that
    we verify the redaction comes from retire_user itself, not the fallback signal.
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

    with disconnected_social_auth_redaction_signal(), CaptureQueriesContext(connection) as ctx:
        call_command('retire_user', username=user.username, user_email=user.email)

    assert_update_before_delete([query['sql'] for query in ctx])

    assert not UserSocialAuth.objects.filter(id=social_auth_id).exists()

    retired_user_status = UserRetirementStatus.objects.filter(original_username=user.username).first()
    assert retired_user_status is not None
    assert retired_user_status.original_email == 'sso-user@example.com'


@skip_unless_lms
def test_retire_user_redacts_each_social_auth_before_bulk_deletion(setup_retirement_states):  # lint-amnesty, pylint: disable=redefined-outer-name, unused-argument  # noqa: F811
    """
    Test that all UserSocialAuth records are redacted before bulk deletion during retirement.

    The safety-net pre_delete signal handler is disconnected for this test so that
    we verify the redaction comes from retire_user itself, not the fallback signal.
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
    google_auth_id = google_auth.id
    saml_auth_id = saml_auth.id

    with disconnected_social_auth_redaction_signal(), CaptureQueriesContext(connection) as ctx:
        call_command('retire_user', username=user.username, user_email=user.email)

    assert_update_before_delete([query['sql'] for query in ctx])

    assert not UserSocialAuth.objects.filter(id=google_auth_id).exists()
    assert not UserSocialAuth.objects.filter(id=saml_auth_id).exists()
