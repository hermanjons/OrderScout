"""Independent SQLite checks for the rich fixture, separate from its builders."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sqlite3


def validate_rich_fixture(db_name: str, *, expected_orders: int = 720) -> dict:
    checks = {}
    with sqlite3.connect(Path(db_name).resolve().as_uri()+'?mode=ro',uri=True) as con:
        con.row_factory=sqlite3.Row
        tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts={t:con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        checks['sqlite_integrity']=con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        fk=[tuple(r) for r in con.execute('PRAGMA foreign_key_check')]
        checks['foreign_keys']=not fk
        checks['exact_orders']=counts['trendyol_order_header']==expected_orders
        checks['all_products']=counts['stock_item']==18 and counts['trendyol_listing_product']==54
        checks['all_domains_populated']=all(counts.get(t,0)>0 for t in (
            'trendyol_return_claim','stock_tx','warehouse','brand','company','cost_item',
            'cost_item_marketplace_link','finance_manual_transaction','finance_invoice_document',
            'trendyol_finance_transaction','trendyol_finance_cargo_invoice_item',
            'logistics_cargo_provider','cargo_tariff','trendyol_listing_product_history',
            'stock_item_snapshot','cost_item_snapshot'))
        checks['ai_settings_empty']=counts['ai_provider_account']==counts['ai_model_artifact']==0
        checks['no_old_orders']=con.execute("SELECT count(*) FROM trendyol_order_header WHERE orderNumber NOT LIKE 'DEMO-%'").fetchone()[0]==0
        checks['all_names_suffixed']=all(con.execute(f'SELECT count(*) FROM "{t}" WHERE "{c}" IS NULL OR "{c}" NOT LIKE ?',('%-demo',)).fetchone()[0]==0
            for t,c in (('stock_item','name'),('trendyol_listing_product','title'),('brand','name'),('company','name'),('warehouse','name'),('apiaccount','comp_name')))
        checks['no_remote_credentials']=all(not a['api_key'] and not a['api_secret'] and not a['token']
            and json.loads(a['extra_config'])['auto_sync_mode']=='local' for a in con.execute('SELECT * FROM apiaccount'))
        latest=list(con.execute('''SELECT d.* FROM trendyol_order_data d WHERE NOT EXISTS
            (SELECT 1 FROM trendyol_order_data n WHERE n.order_header_id=d.order_header_id AND
             (n.lastModifiedDate>d.lastModifiedDate OR (n.lastModifiedDate=d.lastModifiedDate AND n.pk>d.pk)))'''))
        monetary_errors=[]
        states=defaultdict(int)
        for order in latest:
            states[order['status']]+=1
            lines=list(con.execute('SELECT * FROM trendyol_order_item WHERE order_data_pk=?',(order['pk'],)))
            if not lines or abs(sum(l['amount'] for l in lines)-order['totalPrice'])>0.021:
                monetary_errors.append(order['orderNumber'])
            for line in lines:
                if (abs(line['quantity']*line['price']-line['lineGrossAmount'])>0.021
                    or abs(line['lineGrossAmount']-line['lineTotalDiscount']-line['amount'])>0.021):
                    monetary_errors.append(f"line:{line['pk']}")
        checks['latest_snapshot_coverage']=len(latest)==expected_orders
        checks['order_money_consistent']=not monetary_errors
        checks['snapshots_linked']=con.execute('''SELECT count(*) FROM trendyol_order_item i LEFT JOIN trendyol_order_data d ON d.pk=i.order_data_pk
            WHERE d.pk IS NULL OR i.order_header_id IS NULL OR i.order_header_id<>d.order_header_id OR i.order_data_id<>d.id
              OR i.snapshotLastModifiedDate<>d.lastModifiedDate''').fetchone()[0]==0
        checks['returns_linked']=con.execute('''SELECT count(*) FROM trendyol_return_claim r LEFT JOIN trendyol_order_header h ON h.pk=r.order_header_id
            WHERE h.pk IS NULL OR h.orderNumber<>r.orderNumber OR h.api_account_id<>r.api_account_id''').fetchone()[0]==0
        balances=defaultdict(float)
        negative=[]
        missing_valuation=[]
        for tx in con.execute('SELECT * FROM stock_tx ORDER BY occurred_at,created_at,pk'):
            key=tx['item_id'],tx['warehouse_id']
            balances[key]+=tx['qty'] if tx['direction'] in ('IN','IN_') else -tx['qty']
            if balances[key]<-1e-6: negative.append(tx['pk'])
            if tx['unit_cost'] is None or tx['valuation_qty_after'] is None: missing_valuation.append(tx['pk'])
        checks['stock_never_negative']=not negative
        checks['stock_valued']=not missing_valuation
        main_id=con.execute("SELECT pk FROM warehouse WHERE code='DP-01'").fetchone()[0]
        account_count=counts['apiaccount']
        checks['listing_quantity_reconciles']=all(int(l['quantity'])==int(balances[l['stock_item_id'],main_id]//account_count)
            for l in con.execute('SELECT stock_item_id,quantity FROM trendyol_listing_product'))
        checks['finance_money_consistent']=con.execute('''SELECT count(*) FROM trendyol_finance_transaction
            WHERE ABS(COALESCE(credit,0)-COALESCE(debt,0)-COALESCE(netAmount,0))>0.021''').fetchone()[0]==0
        image_paths=[r[0] for r in con.execute('SELECT image_path FROM stock_item')]
        checks['product_images_exist']=all(p and Path(p).is_file() and Path(p).stat().st_size>1000 for p in image_paths)
        documents=[r[0] for r in con.execute('SELECT filePath FROM finance_invoice_document')]
        checks['invoice_pdfs_exist']=bool(documents) and all(p and Path(p).is_file() and Path(p).read_bytes().startswith(b'%PDF-') for p in documents)
        coverage={}
        for table in tables:
            if counts[table]:
                columns=[r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
                coverage[table]={'rows':counts[table], 'entirely_null_columns':[c for c in columns
                    if con.execute(f'SELECT 1 FROM "{table}" WHERE "{c}" IS NOT NULL LIMIT 1').fetchone() is None]}
        for table in ('license_state','license_action_log','sync_change_log','sync_outbox','sync_state'):
            if table in counts: checks[f'{table}_empty']=counts[table]==0
    return {'passed':all(checks.values()),'checks':checks,'counts':counts,'order_states':dict(states),
            'latest_non_cancelled_gross_try':round(sum(r['totalPrice'] for r in latest if r['status']!='Cancelled'),2),
            'foreign_key_errors':fk,'money_errors':monetary_errors[:20],
            'stock_errors':negative[:20],'stock_valuation_missing':missing_valuation[:20],
            'column_coverage':coverage}
