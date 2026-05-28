"""
SQL assertion helpers for tests.
"""


def assert_update_before_delete(
    sql_list,
    table,
    expected_redacted_value,
    num_redact_delete_pairs=1,
):
    """
    Assert that UPDATE and DELETE queries for ``table`` occur in consecutive pairs,
    and that each UPDATE contains the expected redacted value.
    """
    table_key = table.upper()
    expected_sql_list = [
        sql for sql in sql_list
        if table_key in sql.upper() and ('UPDATE' in sql.upper() or 'DELETE' in sql.upper())
    ]

    assert len(expected_sql_list) == num_redact_delete_pairs * 2, (
        f'Expected {num_redact_delete_pairs * 2} UPDATE/DELETE queries on {table}, '
        f'got {len(expected_sql_list)}'
    )

    for index in range(0, len(expected_sql_list), 2):
        update_sql = expected_sql_list[index]
        delete_sql = expected_sql_list[index + 1]
        assert 'UPDATE' in update_sql.upper(), f'Expected UPDATE at position {index} for {table}'
        assert 'DELETE' in delete_sql.upper(), f'Expected DELETE at position {index + 1} for {table}'
        assert expected_redacted_value.upper() in update_sql.upper(), (
            f'Expected UPDATE to set redacted value {expected_redacted_value} for {table}'
        )
