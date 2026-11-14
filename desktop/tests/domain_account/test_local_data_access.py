"""A missing marketplace transport cannot disable persisted business data."""
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session

from Account.models.models import ApiAccount
from Account.processors.access import account_access_profile,validate_remote_account_access
from Account.processors.local_health import lookup_local_accounts,summarize_local_account_health
from Account.views.actions import account_visual_status
from Core.utils.model_utils import get_engine
from Testing.processors.business_agent_fixtures import seed_business_fixture


def local_fixture(tmp_path):
    database=str(tmp_path/'local.sqlite3')
    seed_business_fixture(database,isolation_root=tmp_path)
    with Session(get_engine(database)) as session:
        for pk in (101,102):
            account=session.get(ApiAccount,pk)
            account.extra_config={'environment':'local','data_origin':'synthetic'}
            account.token_valid=False
            session.add(account)
        session.commit()
    return database


def test_local_company_is_active_and_has_no_missing_token_incident(tmp_path):
    database=local_fixture(tmp_path)
    health=summarize_local_account_health(db_name=database)
    assert health.success and health.data['local_accounts']==2
    assert health.data['invalid_tokens']==0 and not health.data['attention_accounts']
    lookup=lookup_local_accounts(db_name=database)
    assert all(a['local_database_access'] and not a['remote_access_configured'] for a in lookup.data['accounts'])
    assert all(a['stored_token_valid'] is False and a['display_status']=='Aktif' for a in lookup.data['accounts'])
    assert all(not a['marketplace_credentials_required_for_local_data'] for a in lookup.data['accounts'])


def test_configured_remote_transport_is_not_a_verified_connection():
    account=SimpleNamespace(platform='TRENDYOL',pk=1,account_id='80001',is_active=True,
                            api_key='test-key',api_secret='test-secret',extra_config={'environment':'stage'})
    with patch('Core.processors.credential_store.resolve_secret',side_effect=AssertionError('No secret lookup')):
        profile=account_access_profile(account)
    assert profile['remote_access_configured'] and not profile['remote_connection_verified']
    assert profile['local_database_access']
    assert account_visual_status(SimpleNamespace(is_active=True,token_valid=False,extra_config={}))=='Pasif'


def test_local_fetch_cannot_create_a_dead_approval_and_reads_still_work(tmp_path):
    from AI.processors.tools import orders_prepare_fetch,orders_snapshot,registered_tools
    database=local_fixture(tmp_path)
    with patch('Orders.api.trendyol.orders_api.TrendyolApi',side_effect=AssertionError('No remote client')):
        readiness=validate_remote_account_access(api_account_ids=[101],db_name=database)
        prepared=orders_prepare_fetch(api_account_ids=[101],db_name=database)
        snapshot=orders_snapshot(api_account_ids=[101],period='all',db_name=database)
    assert not readiness.success and not prepared.success
    assert prepared.data['code']=='remote_access_unavailable' and not prepared.data.get('action')
    assert not prepared.data['network_request_performed'] and not prepared.data['db_write_performed']
    assert set(prepared.data['alternative_read_operations'])<=set(registered_tools())
    assert snapshot.success and snapshot.data['total_count']==5 and snapshot.data['complete']


def test_missing_or_mixed_target_scope_is_never_partially_prepared(tmp_path):
    database=local_fixture(tmp_path)
    from AI.processors.tools import orders_prepare_fetch
    with Session(get_engine(database)) as session:
        account=session.get(ApiAccount,102)
        account.extra_config={'environment':'stage'}
        account.api_key='test-key'; account.api_secret='test-secret'
        session.add(account);session.commit()
    ready=orders_prepare_fetch(api_account_ids=[102],db_name=database)
    assert ready.success and ready.data['valid']
    for ids in ([999],[101,102],[102,999]):
        result=orders_prepare_fetch(api_account_ids=ids,db_name=database)
        assert not result.success and not result.data.get('action')
