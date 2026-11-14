import sqlite3

import pytest

from Testing.processors.rich_business_fixture import money, seed_rich_business_fixture


def test_refuses_existing_business_data_before_bootstrap_or_any_seed_write(tmp_path):
    database=tmp_path/'protected.sqlite3'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE apiaccount(pk INTEGER PRIMARY KEY, api_key TEXT)')
        connection.execute("INSERT INTO apiaccount VALUES(7,'keep-existing-reference')")
    with pytest.raises(ValueError,match='empty database'):
        seed_rich_business_fixture(str(database),assets_root=tmp_path/'assets',images={})
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT * FROM apiaccount').fetchall()==[(7,'keep-existing-reference')]
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()==[('apiaccount',)]


@pytest.mark.parametrize('amount,expected',[(1.005,1.01),(10.225,10.23),(99.999,100.0)])
def test_currency_rounding_is_decimal_half_up(amount,expected):
    assert money(amount)==expected
