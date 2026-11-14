from Feedback.processors.pipeline import Result
from Orders.processors.trendyol.pipeline import save_orders_to_db
from Testing.processors.business_agent_fixtures import seed_business_fixture
from AI.processors.tools import orders_revenue_total


def test_revenue_observation_proves_cancelled_money_is_excluded(tmp_path):
    database=str(tmp_path/'orders.sqlite3')
    seed_business_fixture(database,isolation_root=tmp_path)
    before=orders_revenue_total(db_name=database,period='all')
    result=save_orders_to_db(Result.ok(data={'order_data_list':[{
        'api_account_id':101,'orderNumber':'CANCELLED-CHECK','id':900000,
        'orderDate':1792700000000,'lastModifiedDate':1792700000000,
        'status':'Cancelled','shipmentPackageStatus':'Cancelled','currencyCode':'TRY',
        'totalPrice':99999,'packageTotalPrice':99999}], 'order_item_list':[]}),db_name=database)
    assert result.success
    after=orders_revenue_total(db_name=database,period='all')
    assert before.success and after.success
    assert after.data['total']==before.data['total']
    assert after.data['cancelled_orders']==1
    assert after.data['revenue_order_count']==6
    assert after.data['revenue_basis']=='non_cancelled_order_totals'
    assert after.data['excluded_revenue_statuses']==['Cancelled']


def test_local_order_targets_retain_local_provenance(tmp_path):
    from sqlmodel import Session
    from Account.models.models import ApiAccount
    from Core.utils.model_utils import get_engine
    from Orders.processors.agentic_repository import target_account_ids

    database=str(tmp_path/'targets.sqlite3')
    seed_business_fixture(database,isolation_root=tmp_path)
    with Session(get_engine(database)) as session:
        account=session.get(ApiAccount,101)
        account.extra_config={'data_origin':'synthetic','environment':'local'}
        session.add(account)
        session.commit()
    result=target_account_ids('order',[{'token':'PILOT-A-OLD-1','api_account_id':101}],db_name=database)
    assert result.success
    assert result.data['target_environments']==['local']


def test_product_aggregate_retains_observed_store_scope_without_explicit_filter(tmp_path):
    from AI.processors.tools import orders_item_sales_summary

    database=str(tmp_path/'products.sqlite3')
    seed_business_fixture(database,isolation_root=tmp_path)
    result=orders_item_sales_summary(db_name=database,period='all',limit=100)
    assert result.success
    assert {a['api_account_id'] for a in result.data['account_scopes']}=={101,102}
    assert result.data['amount_basis']=='line_gross_before_discounts'
    assert set(result.data['excluded_statuses'])=={'cancelled','returned','undeliveredandreturned','unsupplied'}
