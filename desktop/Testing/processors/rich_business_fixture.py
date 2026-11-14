"""Coherent, local-only business dataset built through shared domain operations.

This module never resets a database. It refuses nonempty business databases;
replacing a user's database is an explicit, separately backed-up operation.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import random
import shutil
import sqlite3
from urllib.request import Request, urlopen


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def _require(result, operation):
    if not result.success:
        raise RuntimeError(f'{operation}: {result.message}; {getattr(result, "error", None)}')
    return result


def prepare_product_assets(assets_root: Path, *, generated_image: Path, listing_cache: Path):
    """Cache matching product photographs, including the generated slicer image."""
    from Testing.processors.rich_seed_catalog import PRODUCTS
    from PIL import Image

    assets_root.mkdir(parents=True, exist_ok=True)
    listing_cache.mkdir(parents=True, exist_ok=True)

    def prepare(product):
        remote = product['product_image_url']
        destination = assets_root / (product['sku'] + ('.webp' if remote else '.png'))
        if not destination.exists():
            if remote:
                request = Request(remote, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'image/*'})
                with urlopen(request, timeout=45) as response:
                    content = response.read(8_000_001)
                if len(content) > 8_000_000:
                    raise ValueError('Product image exceeds fixture size limit')
                temporary = destination.with_suffix(destination.suffix + '.tmp')
                temporary.write_bytes(content)
                with Image.open(temporary) as image:
                    image.verify()
                temporary.replace(destination)
            else:
                shutil.copy2(generated_image, destination)
        with Image.open(destination) as image:
            width, height = image.size
            image.verify()
        # The local generated asset has a truthful file URI, never a fictitious HTTP URL.
        url = remote or destination.resolve().as_uri()
        extension = Path(url.split('?')[0]).suffix or '.jpg'
        cache = listing_cache / (hashlib.blake2b(url.encode(), digest_size=16).hexdigest() + extension)
        shutil.copy2(destination, cache)
        return product['sku'], {'path': str(destination.resolve()), 'url': url,
                                'width': width, 'height': height,
                                'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}

    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(pool.map(prepare, PRODUCTS))


def seed_rich_business_fixture(db_name: str, *, assets_root: str | Path,
                               images: dict, now: datetime | None = None,
                               order_count: int = 720):
    from sqlmodel import Session, select
    from Core.db.bootstrap import init_database
    from Core.utils.model_utils import get_engine
    from Account.models.models import ApiAccount
    from Marketplaces.models.models import Marketplace
    from Finance.models.trendyol.models import Company, Brand
    from Stock.models.models import StockItem, Warehouse
    from Stock.processors import pipeline as stock
    from Stock.constants.domain_constants import StockTxDirection as Direction, StockTxReason as Reason, StockReferenceType as Reference
    from Listing.models.models import ListingProduct
    from Listing.processors.pipeline import save_listings_to_db, set_listing_stock_items
    from Orders.models.trendyol.models import OrderHeader
    from Orders.processors.trendyol.pipeline import save_orders_to_db, save_return_claims_to_db
    from Feedback.processors.pipeline import Result
    from Testing.processors.rich_seed_catalog import PRODUCTS

    database = Path(db_name).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        with sqlite3.connect(database) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in tables - {'applied_migrations', 'sqlite_sequence'}:
                quoted=table.replace('"','""')
                if connection.execute(f'SELECT 1 FROM "{quoted}" LIMIT 1').fetchone():
                    raise ValueError('Rich fixture requires an empty database; existing records are never cleared.')
    init_database(str(database))
    engine = get_engine(str(database))
    current = now or datetime.now(timezone(timedelta(hours=3)))
    if current.tzinfo is None:
        raise ValueError('Fixture clock must include timezone')
    current = current.replace(microsecond=0)
    origin = current - timedelta(days=370)
    rng = random.Random(20261023)
    ms = lambda date: int(date.timestamp() * 1000)

    with Session(engine) as session:
        marketplace = session.exec(select(Marketplace).where(Marketplace.code == 'TRENDYOL')).first()
        if marketplace is None:
            marketplace = Marketplace(code='TRENDYOL', label='Trendyol', description='E-ticaret pazaryeri', isActive=True)
            session.add(marketplace)
            session.flush()
        accounts = []
        for index, name in enumerate(('Ardıç Ev-demo', 'Lale Yaşam-demo', 'Mavi Çarşı-demo'), 1):
            account = ApiAccount(account_id=str(850000 + index), comp_name=name,
                                 platform_id=marketplace.pk, platform='TRENDYOL',
                                 integration_code=f'LOCAL-{index}', api_key='', api_secret='',
                                 token='', token_valid=False, encrypted=False, is_active=True,
                                 last_used_at=current.replace(tzinfo=None),
                                 extra_config={'data_origin': 'synthetic', 'environment': 'local', 'auto_sync_mode': 'local'})
            session.add(account)
            session.flush()
            accounts.append({'pk': account.pk, 'account_id': account.account_id, 'comp_name': name})
        session.commit()

    with stock.database_scope(str(database)):
        for index, name in enumerate(sorted({p['brand'] for p in PRODUCTS}), 1):
            _require(stock.create_brand(name, code=f'MRK-{index:03}', country='Türkiye',
                         website=f'https://marka{index}.example.invalid', contact_email=f'iletisim@marka{index}.invalid',
                         address='Sanayi Mahallesi, Üretim Sokak No:12, İstanbul',
                         note='Yerel katalog markası; dış hizmet bağlantısı yok.'), 'brand')
        for index, (name, city) in enumerate((('Ardıç Tedarik-demo', 'İstanbul'), ('Lale Ambalaj-demo', 'Bursa'),
                                             ('Mavi Lojistik-demo', 'Ankara'), ('Pera Hizmet-demo', 'İzmir')), 1):
            _require(stock.create_company(name, email=f'tedarik{index}@example.invalid',
                         address=f'Organize Sanayi Bölgesi, {index}. Cadde No:8, {city}',
                         note='Sentetik tedarikçi kaydı; vergi kimliği uygulanmaz.'), 'company')
        for index, (name, city) in enumerate((('Merkez Depo-demo', 'İstanbul'), ('Ege Depo-demo', 'İzmir'),
                                             ('İade Kontrol Deposu-demo', 'Ankara')), 1):
            _require(stock.create_warehouse(name, code=f'DP-{index:02}', manager_name=f'Depo Sorumlusu {index}-demo',
                         email=f'depo{index}@example.invalid', address=f'Lojistik Mahallesi, Raf Sokak No:{index}, {city}',
                         city=city, country='Türkiye', capacity_m3=500 if index == 1 else 200,
                         layout_json=json.dumps({'zones': ['A', 'B', 'C'], 'aisles': 6, 'shelves_per_aisle': 12}),
                         note='Raf ve kalite kontrol alanları tanımlıdır.'), 'warehouse')
        for index, p in enumerate(PRODUCTS, 1):
            _require(stock.create_item(p['sku'], p['title'], barcode=p['barcode'], brand=p['brand'],
                         category=p['category'], sub_category=p['sub_category'], model_code=f'OS-{index:03}',
                         manufacturer=p['brand'], custom_label='Hızlı dönen' if index < 7 else 'Standart',
                         location_code=f'A-{(index-1)//6+1:02}-{(index-1)%6+1:02}', image_path=images[p['sku']]['path'],
                         description=p['description'], note='Tedarik süresi ve stok eşiği tanımlı yerel ürün kartı.',
                         min_stock=p['min_stock'], max_stock=p['max_stock'], safety_stock=max(3,p['min_stock']//2),
                         reorder_point=p['min_stock']+10, reorder_qty=60, lead_time_days=3+index%6,
                         shelf_life_days=730 if index >= 15 else None, lot_tracking=index>=15,
                         vat_rate=p['vat_rate'], weight_kg=p['weight_kg'], length_cm=p['length_cm'],
                         width_cm=p['width_cm'], height_cm=p['height_cm']), 'item')
    with Session(engine) as session:
        products = [dict(p, stock_item_id=session.exec(select(StockItem.pk).where(StockItem.sku==p['sku'])).one()) for p in PRODUCTS]
        companies = [{'pk': c.pk, 'name': c.name} for c in session.exec(select(Company)).all()]
        warehouses = list(session.exec(select(Warehouse).order_by(Warehouse.pk)).all())
    listing_payload = []
    for a in accounts:
        for index, p in enumerate(products, 1):
            listing_payload.append({
                'api_account_id': a['pk'], 'product_id': str(a['pk']*100000+index),
                'productCode': str(900000+index), 'batchRequestId': f'LOCAL-CATALOG-{a["pk"]}',
                'supplierId': int(a['account_id']), 'createDateTime': ms(origin), 'lastUpdateDate': ms(current),
                'gender': 'Unisex', 'categoryName': p['category'], 'productMainId': f'OS-{index:03}',
                'description': p['description'], 'stockUnitType': 'adet', 'title': p['title'], 'barcode': p['barcode'],
                'stockCode': p['sku'], 'brand': p['brand'], 'quantity': 50, 'approved': True, 'archived': False,
                'onSale': True, 'listPrice': p['list_price'], 'salePrice': p['sale_price'], 'vatRate': p['vat_rate'],
                'dimensionalWeight': money(p['length_cm']*p['width_cm']*p['height_cm']/3000),
                'locationBasedDelivery': False, 'specialConsumptionTax': 0,
                'deliveryOption': {'deliveryDuration': 2, 'fastDeliveryType': 'SAME_DAY_SHIPPING'},
                'images': [{'url': images[p['sku']]['url']}],
                'attributes': [{'attributeName': 'Renk', 'attributeValue': p['color']},
                               {'attributeName': 'Materyal', 'attributeValue': p['material']},
                               {'attributeName': 'Boyut', 'attributeValue': p['size']}],
                'platformListingId': str(900000+index), 'stockId': p['sku'], 'hasActiveCampaign': index%4==0,
                'locked': False, 'productContentId': 900000+index, 'pimCategoryId': 500+index,
                'brandId': index//7+1, 'version': 1, 'color': p['color'], 'size': p['size'],
                'currencyCode': 'TRY', 'data_origin': 'synthetic'})
    _require(save_listings_to_db(listing_payload, db_name=str(database)), 'listings')
    for a in accounts:
        for index,p in enumerate(products,1):
            _require(set_listing_stock_items(api_account_id=a['pk'],product_id=str(900000+index),
                         stock_items=[{'stock_item_id':p['stock_item_id'],'qty':1}],db_name=str(database)), 'stock binding')

    orders, snapshots, item_rows, claims = [], [], [], []
    cities = [('İstanbul', 'Kadıköy', '34710'), ('Ankara', 'Çankaya', '06550'), ('İzmir', 'Karşıyaka', '35550'),
              ('Bursa', 'Nilüfer', '16140'), ('Antalya', 'Muratpaşa', '07100'), ('Eskişehir', 'Tepebaşı', '26130')]
    firsts = ('Deniz','Ece','Mert','Selin','Arda','Duru','Can','Elif','Ozan','İpek','Bora','Ada')
    lasts = ('Yıldız','Aydın','Kaya','Demir','Çelik','Aksoy','Yalçın','Şen')
    latest_states = ('Picking','ReadyToShip','Invoiced','Shipped','Delivered','Cancelled','UnDelivered','AtCollectionPoint')
    for index in range(order_count):
        a = accounts[index % len(accounts)]
        age = (index % 24 + rng.random()) if index < 180 else (25 + ((index-180)*337/(max(1,order_count-180))) + rng.random())
        date = current-timedelta(days=age)
        status = latest_states[index%len(latest_states)] if age < 7 else ('Cancelled' if index%17==0 else 'UnDeliveredAndReturned' if index%31==0 else 'Delivered')
        # A recent successful delivery is possible only after a plausible transit period.
        if status=='Delivered' and age<2: status='Shipped'
        package = 710000000+index
        number = f'DEMO-{date:%Y%m}-{index+1:06}'
        first,last = firsts[index%12],lasts[(index//12)%8]+'-demo'
        city,district,postal = cities[index%len(cities)]
        address = {'id': 800000+index, 'firstName': first, 'lastName': last,
                   'fullAddress': f'Örnek Mahallesi, Çiçek Sokak No:{index%80+1} Daire:{index%12+1}',
                   'address1': f'Örnek Mahallesi, Çiçek Sokak No:{index%80+1}', 'address2': f'Daire:{index%12+1}',
                   'city': city, 'district': district, 'postalCode': postal, 'countryCode': 'TR',
                   'neighborhood': 'Örnek Mahallesi', 'phone': None, 'company': None}
        lines=[]
        for offset in range(1+(index%4==0)+(index%11==0)):
            p=products[(index*7+offset*5)%len(products)]
            qty=1+(index+offset)%3 if index%5==0 else 1
            price=money(p['sale_price']*(0.94 if age>180 else 1.0))
            gross=money(price*qty)
            discount=money(gross*.05) if index%9==0 else 0
            lines.append({'id':package*10+offset+1, 'barcode':p['barcode'], 'quantity':qty, 'price':price,
                          'lineGrossAmount':gross,'lineTotalDiscount':discount,'lineNetAmount':money(gross-discount),
                          'vatRate':p['vat_rate'],'product':p})
        gross=money(sum(l['lineGrossAmount'] for l in lines)); discount=money(sum(l['lineTotalDiscount'] for l in lines))
        total=money(gross-discount)
        delivered=date+timedelta(days=2+index%3) if status=='Delivered' else None
        if delivered and delivered>current: delivered=current-timedelta(hours=2)
        modified = delivered or min(current-timedelta(minutes=1),date+timedelta(hours=3 if status in ('Picking','Cancelled') else 20))
        history=[{'createdDate':ms(date),'status':'Created'}]
        if status not in ('Picking','Cancelled'): history.append({'createdDate':ms(date+timedelta(hours=5)),'status':'Picking'})
        if status in ('Shipped','Delivered','UnDelivered','UnDeliveredAndReturned','AtCollectionPoint'):
            history.append({'createdDate':ms(min(modified,date+timedelta(hours=18))),'status':'Shipped'})
        history.append({'createdDate':ms(modified),'status':status})
        row={'api_account_id':a['pk'],'orderNumber':number,'id':package,'shipmentPackageId':package,'status':status,
             'shipmentPackageStatus':status,'orderDate':ms(date),'lastModifiedDate':ms(modified),'currencyCode':'TRY',
             'customerId':500000+index,'customerFirstName':first,'customerLastName':last,
             'customerEmail':f'alici{index+1}@example.invalid','shipmentAddress':address,'invoiceAddress':address,
             'packageHistories':history,'grossAmount':gross,'totalDiscount':discount,'totalTyDiscount':0,'totalPrice':total,
             'packageGrossAmount':gross,'packageSellerDiscount':discount,'packageTyDiscount':0,'packageTotalDiscount':discount,
             'packageTotalPrice':total,'discountDisplays':[{'displayName':'Mağaza indirimi','amount':discount}] if discount else [],
             'cargoProviderName':'ARASMP' if index%2==0 else 'YKMP','cargoSenderNumber':f'LOCAL-{a["pk"]}',
             'cargoTrackingNumber':f'DEMOTRK{package}' if status not in ('Picking','Cancelled','ReadyToShip') else None,
             'cargoTrackingLink':None, 'deliveryType':'normal','timeSlotId':0,
             'estimatedDeliveryStartDate':ms(date+timedelta(days=2)), 'estimatedDeliveryEndDate':ms(date+timedelta(days=4)),
             'deliveryAddressType':'Shipment','agreedDeliveryDate':ms(date+timedelta(days=3)),
             'fastDelivery':False,'commercial':False,'deliveredByService':False,
             'originShipmentDate':ms(date+timedelta(hours=18)) if status in ('Shipped','Delivered','UnDelivered','UnDeliveredAndReturned','AtCollectionPoint') else None,
             'warehouseId':warehouses[0].pk,'supplierId':int(a['account_id']),'whoPays':'Seller',
             'micro':False,'giftBoxRequested':index%37==0,'byTrendyol3':False,'containsDangerousProduct':False,
             'cargoDeci':max(1,money(sum(l['product']['weight_kg']*l['quantity'] for l in lines))),
             'isCod':False,'createdBy':'local-synthetic-fixture','originPackageIds':[], 'shipmentNumber':f'OS-{package}'}
        stages=[row]
        if index%4==0 and ms(modified)>ms(date):
            stages=[dict(row,status='Created',shipmentPackageStatus='Created',lastModifiedDate=ms(date),
                         packageHistories=history[:1],cargoTrackingNumber=None,originShipmentDate=None),row]
        for stage in stages:
            snapshots.append(stage)
            for line in lines:
                p=line['product']
                item_rows.append({'api_account_id':a['pk'],'orderNumber':number,'order_data_id':package,
                    'snapshotLastModifiedDate':stage['lastModifiedDate'],'id':line['id'],'lineId':line['id'],
                    'quantity':line['quantity'],'productSize':p['size'],'merchantSku':p['sku'],'stockCode':p['sku'],
                    'contentId':900000+products.index(p)+1,'productName':p['title'],'productCode':900000+products.index(p)+1,
                    'productOrigin':'TR','merchantId':int(a['account_id']),'sellerId':int(a['account_id']),
                    'amount':line['lineNetAmount'],'lineGrossAmount':line['lineGrossAmount'],
                    'lineTotalDiscount':line['lineTotalDiscount'],'lineSellerDiscount':line['lineTotalDiscount'],
                    'tyDiscount':0,'lineTyDiscount':0,'vatBaseAmount':money(line['lineNetAmount']/(1+p['vat_rate']/100)),
                    'price':line['price'],'lineUnitPrice':line['price'],'discount':line['lineTotalDiscount'],
                    'commission':15,'currencyCode':'TRY','sku':p['sku'],'barcode':p['barcode'],
                    'orderLineItemStatusName':stage['status'],'taskDate':stage['lastModifiedDate'],
                    'productColor':p['color'],'vatRate':p['vat_rate'],'fastDeliveryOptions':[],
                    'productCategoryId':500+products.index(p)+1,'businessUnit':p['category'],'laborCost':0,
                    'cancelledBy':'Customer' if stage['status']=='Cancelled' else None,
                    'cancelReason':'Müşteri talebi' if stage['status']=='Cancelled' else None,
                    'cancelReasonCode':'CUSTOMER_REQUEST' if stage['status']=='Cancelled' else None,
                    'discountDetails':[{'discount':line['lineTotalDiscount'],'type':'Seller'}] if line['lineTotalDiscount'] else []})
        order={'account_id':a['pk'],'orderNumber':number,'package_id':package,'orderDate':ms(date),
               'delivered_at':ms(delivered) if delivered else None,'status':status,'totalPrice':total,
               'lines':lines,'return':None}
        if status=='Delivered' and age>7 and index%7==0:
            return_status=('Accepted','WaitingInAction','Rejected')[index%3] if age<30 else ('Accepted' if index%3 else 'Rejected')
            return_date=min(current-timedelta(hours=3),delivered+timedelta(days=3))
            line=lines[0]; lineid=str(line['id']); reason=('Beden/ölçü uygun değil','Ürünü beğenmedim','Yanlış ürün seçimi')[index%3]
            claim={'api_account_id':a['pk'],'claimId':f'CLM-{package}','claimNumber':f'IA-{index+1:06}',
                   'orderNumber':number,'orderShipmentPackageId':package,'orderOutboundPackageId':package,
                   'customerFirstName':first,'customerLastName':last,'cargoTrackingNumber':f'IADE{package}',
                   'cargoProviderName':row['cargoProviderName'],'cargoSenderNumber':row['cargoSenderNumber'],
                   'claimDate':ms(return_date),'orderDate':ms(date),'lastModifiedDate':ms(return_date),
                   'claimItemStatus':return_status,'claimReason':reason,'totalPrice':line['lineNetAmount'],
                   'currencyCode':'TRY','itemCount':line['quantity'],'claimLineItemIds':[lineid],
                   'waitingClaimLineItemIds':[lineid] if return_status=='WaitingInAction' else [],
                   'claimItemStatuses':[return_status],'claimReasons':[reason],
                   'itemsJson':[{'orderLine':{'id':line['id'],'barcode':line['barcode'],'productName':line['product']['title'],
                                            'quantity':line['quantity'],'price':line['price']},
                                 'claimItems':[{'id':f'CI-{lineid}','claimItemStatus':{'name':return_status},
                                                'customerClaimItemReason':{'name':reason}}]}],
                   'rawData':{'data_origin':'synthetic','claimId':f'CLM-{package}'}}
            claims.append(claim)
            order['return']={'status':return_status,'totalPrice':line['lineNetAmount'],'date':ms(return_date)}
        orders.append(order)
    _require(save_orders_to_db(Result.ok(data={'order_data_list':snapshots,'order_item_list':item_rows}),db_name=str(database)), 'orders')
    if claims: _require(save_return_claims_to_db(Result.ok(data={'return_claim_list':claims}),db_name=str(database)), 'returns')
    with Session(engine) as session:
        headers={(h.api_account_id,h.orderNumber):h for h in session.exec(select(OrderHeader)).all()}
        for order in orders:
            header=headers[order['account_id'],order['orderNumber']]
            order['header_pk']=header.pk
            processed=order['status'] not in ('Created','Picking','Cancelled','ReadyToShip')
            header.is_printed=processed; header.is_extracted=processed
            if processed:
                header.printed_at=order['orderDate']+8*3600000
                header.extracted_at=header.printed_at
            session.add(header)
        listing_ids={(l.api_account_id,l.barcode):l.pk for l in session.exec(select(ListingProduct)).all()}
        session.commit()

    shipped={'Shipped','Delivered','UnDelivered','UnDeliveredAndReturned','AtCollectionPoint'}
    demand=Counter(); returns=Counter()
    events=[]
    for order in orders:
        if order['status'] in shipped:
            for line in order['lines']:
                sku=line['product']['sku']; demand[sku]+=line['quantity']
                events.append((order['orderDate']+18*3600000,'out',order,line))
                if order['status']=='UnDeliveredAndReturned':
                    returns[sku]+=line['quantity']; events.append((order['orderDate']+6*86400000,'in',order,line))
            if order['return'] and order['return']['status']=='Accepted':
                line=order['lines'][0]; returns[line['product']['sku']]+=line['quantity']
                events.append((order['return']['date'],'in',order,line))
    targets={p['sku']:(0 if i==0 else 3 if i==1 else max(8,p['min_stock']-4) if i in (2,3) else 45+i*9) for i,p in enumerate(products)}
    with stock.database_scope(str(database)):
        for p in products:
            # Opening inventory covers every chronological withdrawal; saleable returns
            # are transferred to the return warehouse rather than inflating main stock.
            opening=demand[p['sku']]+targets[p['sku']]
            _require(stock.create_tx(p['stock_item_id'],warehouses[0].pk,Direction.IN_,opening,Reason.manual_in,
                         occurred_at=origin.replace(tzinfo=None),unit_cost=p['unit_cost'],unit_cost_input_mode='gross',
                         unit_cost_vat_rate=p['vat_rate'],counterparty=companies[0]['name'],
                         reference_type=Reference.purchase,reference_id=f'PUR-OPEN-{p["sku"]}',
                         note='Dönem başı tedarik alımı',created_by='local-fixture'), 'opening stock')
            # Regional inventory is independent of the main fulfillment warehouse.
            index=products.index(p)
            if index>3:
                _require(stock.create_tx(p['stock_item_id'],warehouses[1].pk,Direction.IN_,12+index%5,
                             Reason.manual_in,occurred_at=origin.replace(tzinfo=None),unit_cost=p['unit_cost'],
                             unit_cost_input_mode='gross',unit_cost_vat_rate=p['vat_rate'],counterparty=companies[0]['name'],
                             reference_type=Reference.purchase,reference_id=f'PUR-EGE-{p["sku"]}',
                             note='Bölge deposu açılış bakiyesi',created_by='local-fixture'), 'regional stock')
        for stamp,direction,order,line in sorted(events,key=lambda e:e[0]):
            p=line['product']; inbound=direction=='in'
            _require(stock.create_tx(p['stock_item_id'],warehouses[2].pk if inbound else warehouses[0].pk,
                         Direction.IN_ if inbound else Direction.OUT,line['quantity'],Reason.return_in if inbound else Reason.order_out,
                         occurred_at=datetime.fromtimestamp(stamp/1000,timezone.utc).replace(tzinfo=None),
                         unit_cost=p['unit_cost'] if inbound else None,unit_cost_input_mode='gross' if inbound else None,
                         unit_cost_vat_rate=p['vat_rate'] if inbound else None,
                         reference_type=Reference.purchase if inbound else Reference.order,
                         reference_id=f'RET-{line["id"]}' if inbound else stock._build_order_ref_id(
                             api_account_id=order['account_id'],order_number=order['orderNumber'],
                             product_code=str(900000+products.index(p)+1),barcode=p['barcode'],stock_code=p['sku']),
                         order_header_id=order['header_pk'],order_ref=order['orderNumber'],
                         listing_id=listing_ids[order['account_id'],line['barcode']],map_qty=1,
                         note='Kalite kontrol deposuna iade girişi' if inbound else 'Sipariş sevkiyatı',
                         created_by='local-fixture'), 'stock movement')
    # Stock returned for inspection is excluded from saleable channel quantities.
    for payload in listing_payload:
        p=next(p for p in products if p['barcode']==payload['barcode'])
        payload.update(quantity=targets[p['sku']]//len(accounts),version=2,onSale=targets[p['sku']]>0)
    _require(save_listings_to_db(listing_payload,db_name=str(database)), 'listing quantities/history')
    from Testing.processors.rich_finance_fixture import seed_finance_fixture
    finance=seed_finance_fixture(str(database),accounts=accounts,products=products,orders=orders,
                                 companies=companies,assets_root=Path(assets_root),now=current)
    summary={'kind':'rich_local_business_v1','as_of':current.isoformat(),'accounts':accounts,
             'products':len(products),'orders':len(orders),'snapshots':len(snapshots),'order_lines':len(item_rows),
             'returns':len(claims),'states':dict(Counter(o['status'] for o in orders)),
             'gross_excluding_cancelled_try':money(sum(o['totalPrice'] for o in orders if o['status']!='Cancelled')),
             'main_warehouse_balances':targets,'finance':finance,'images':images,
             'notes':['All customers and businesses are synthetic; no remote marketplace credentials.',
                      'Unavailable export, tax identity and nonexistent event fields remain null.',
                      'AI configuration and license records intentionally remain empty.']}
    return summary
