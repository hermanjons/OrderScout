import sqlite3 as sql
from time_tasks import epoch_to_datetime
import pandas as pd
import os

database_directory_name = "databases"
if not os.path.exists(database_directory_name):
    os.makedirs(database_directory_name)


def create_order_dbase():
    dbase_path = os.path.join(database_directory_name, "orders.db")

    connection_order_save_db = sql.connect(dbase_path, check_same_thread=False)
    cursor_order_db = connection_order_save_db.cursor()
    cursor_order_db.execute("""
                CREATE TABLE IF NOT EXISTS order_datas
                (
                orderNumber INTEGER,
                id INTEGER,
                cargoTrackingNumber TEXT,
                cargoProviderName TEXT,
                customerId INTEGER,
                customerFirstName TEXT,
                customerLastName TEXT,
                shipmentAddress TEXT,
                grossAmount REAL,
                totalDiscount REAL,
                totalTyDiscount REAL,
                invoiceAddress TEXT,
                tcIdentityNumber TEXT,
                orderDate INTEGER,
                currencyCode TEXT,
                shipmentPackageStatus TEXT,
                status TEXT,
                deliveryType TEXT,
                timeSlotId,scheduledDeliveryStoreId,
                estimatedDeliveryStartDate INTEGER,
                estimatedDeliveryEndDate INTEGER,
                totalPrice INTEGER,
                deliveryAddressType,agreedDeliveryDate,fastDelivery,originShipmentDate,
                lastModifiedDate INTEGER,
                commercial,fastDeliveryType,deliveredByService,agreedDeliveryDateExtendible,
                extendedAgreedDeliveryDate,agreedDeliveryExtensionEndDate,agreedDeliveryExtensionStartDate,
                warehouseId,groupDeal,
                encodedCtNumber,
                totalProfit,
                
                
                UNIQUE(orderNumber,lastModifiedDate)
                 )
            """)
    cursor_order_db.execute("""
                CREATE TABLE IF NOT EXISTS order_items
                (
                quantity İNTEGER,
                productSize,merchantSku,salesCampaignId,productName,
                productCode INTEGER,
                merchantId INTEGER,
                amount REAL,
                tyDiscount REAL,
                currencyCode TEXT,
                discount INTEGER,
                id INTEGER,
                vatBaseAmount REAL,
                sku,barcode,
                orderLineItemStatusName TEXT,
                price INTEGER,
                orderNumber INTEGER,
                taskDate INTEGER,
                

                UNIQUE(orderNumber,productCode,id,orderLineItemStatusName)
            
                
                )
                """)
    cursor_order_db.execute(
        """
                CREATE TABLE IF NOT EXISTS scrap_datas
                (
                scrap_date INTEGER
                )
                """
    )

    connection_order_save_db.commit()
    cursor_order_db.close()
    connection_order_save_db.close()


def create_comp_info_db():
    dbase_path = os.path.join(database_directory_name, "comp_info.db")

    connection_comp_info_db = sql.connect(dbase_path)
    cursor_comp_info_db = connection_comp_info_db.cursor()
    cursor_comp_info_db.execute(

        """CREATE TABLE IF NOT EXISTS comp_accounts
                    (
                    seller_id INTEGER,
                    api_key TEXT,
                    api_secret TEXT,
                    comp_name TEXT,
                    
                    UNIQUE(seller_id)
                    )
        """
    )

    connection_comp_info_db.commit()
    cursor_comp_info_db.close()
    connection_comp_info_db.close()


def create_label_datas_dbase():
    dbase_path = os.path.join(database_directory_name, "label_datas.db")

    connection_label_datas_db = sql.connect(dbase_path)
    cursor_label_datas_db = connection_label_datas_db.cursor()
    cursor_label_datas_db.execute(

        """CREATE TABLE IF NOT EXISTS label_datas_eight_format
                    (
                    orderNumber,
                    cargoTrackingNumber TEXT,
                    cargoProviderName TEXT,
                    
                    customerName TEXT,
                    customerSurname TEXT,
                    
                    leftFirstProd TEXT,
                    leftFirstQuantity INTEGER,
                    
                    leftSecondProd TEXT,
                    leftSecondQuantity INTEGER,
                    
                    leftThirdProd TEXT,
                    leftThirdQuantity INTEGER,
                    
                    leftFourthProd TEXT,
                    leftFourthQuantity INTEGER,
                    
                    rightFirstProd TEXT,
                    rightFirstQuantity INTEGER,
                    
                    rightSecondProd TEXT,
                    rightSecondQuantity INTEGER,
                    
                    rightThirdProd TEXT,
                    rightThirdQuantity INTEGER,
                    
                    rightFourthProd TEXT,
                    rightFourthQuantity INTEGER,
                    
                    paperNumber TEXT,
                    cargoTrackingNumberNumeric TEXT,
                    
                    fullAddress TEXT,
                    isPrinted TEXT,
                    
                    lastModifiedDate TEXT,
                    
                    currentPackageStatus TEXT,
                    
                    status TEXT,
                    
                    UNIQUE(orderNumber,paperNumber,lastModifiedDate)
                
                    
                    )
        """
    )

    connection_label_datas_db.commit()
    cursor_label_datas_db.close()
    connection_label_datas_db.close()


def create_stock_datas_db():
    dbase_path = os.path.join(database_directory_name, "stock_datas.db")

    connection_stock_datas_db = sql.connect(dbase_path)
    cursor_stock_datas_db = connection_stock_datas_db.cursor()
    cursor_stock_datas_db.execute(

        """CREATE TABLE IF NOT EXISTS stock_datas
                    (
                    product_name TEXT,
                    product_price INTEGER,
                    purchase_place TEXT,
                    purchase_date TEXT,
                    quantity INTEGER,
                    stock_code TEXT,
                    is_have_package_cost TEXT
                    )
        """
    )
    cursor_stock_datas_db.execute(

        """CREATE TABLE IF NOT EXISTS match_datas
                    (
                    product_stock_code TEXT,
                    package_quantity INTEGER,
                    advert_barcode TEXT
                    )
        """
    )
    connection_stock_datas_db.commit()
    cursor_stock_datas_db.close()
    connection_stock_datas_db.close()


def create_license_info_db():
    dbase_path = os.path.join(database_directory_name, "license_info.db")

    connection_license_info_db = sql.connect(dbase_path)
    cursor_license_info_db = connection_license_info_db.cursor()
    cursor_license_info_db.execute(

        """CREATE TABLE IF NOT EXISTS  license_key
                    (
                    license_key,api_token
                    )
        """
    )

    connection_license_info_db.commit()
    cursor_license_info_db.close()
    connection_license_info_db.close()


def push_orders_to_dbase(datas):
    dbase_path = os.path.join(database_directory_name, "orders.db")
    connection_order_save_db = sql.connect(dbase_path, check_same_thread=False)
    cursor_order_db = connection_order_save_db.cursor()
    cursor_order_db.executemany("""
                INSERT OR IGNORE INTO order_datas 
                (shipmentAddress,orderNumber,grossAmount,totalDiscount,
                totalTyDiscount,invoiceAddress,customerFirstName,
                customerId,customerLastName,id,cargoTrackingNumber,cargoProviderName,orderDate,
                tcIdentityNumber,currencyCode,shipmentPackageStatus,status,deliveryType,timeSlotId,
                estimatedDeliveryStartDate,estimatedDeliveryEndDate,totalPrice,
                deliveryAddressType,agreedDeliveryDate,fastDelivery,originShipmentDate,lastModifiedDate,commercial,
                fastDeliveryType,deliveredByService,agreedDeliveryDateExtendible,extendedAgreedDeliveryDate,
                agreedDeliveryExtensionEndDate,agreedDeliveryExtensionStartDate,warehouseId,groupDeal,encodedCtNumber
                
                )

                VALUES

               (?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?,?,
                ?,?,?,?,?,?
                )        

                """, datas)

    connection_order_save_db.commit()
    cursor_order_db.close()
    connection_order_save_db.close()


def push_order_items_to_dbase(datas):
    dbase_path = os.path.join(database_directory_name, "orders.db")
    connection_order_save_db = sql.connect(dbase_path, check_same_thread=False)
    cursor_order_db = connection_order_save_db.cursor()
    cursor_order_db.executemany("""
                    INSERT OR IGNORE INTO order_items
                    (quantity,
                    salesCampaignId,productSize,
                    merchantSku,productCode,amount,
                    productName,merchantId,discount,
                    tyDiscount,currencyCode,id,
                    sku,vatBaseAmount,
                    barcode,
                    orderLineItemStatusName,   
                    price,orderNumber,
                    taskDate
        
                    )

                    VALUES

                   (?,?,?,?,
                   ?,?,?,?,?,
                   ?,?,?,?,?,?,
                   ?,?,?,?
                   
                    )        

                    """, datas)

    connection_order_save_db.commit()
    cursor_order_db.close()
    connection_order_save_db.close()


def push_scrap_datas_to_dbase(scrap_date):
    dbase_path = os.path.join(database_directory_name, "orders.db")
    connection_order_save_db = sql.connect(dbase_path, check_same_thread=False)
    cursor_order_db = connection_order_save_db.cursor()
    cursor_order_db.execute("""
                   INSERT INTO scrap_datas
                   (scrap_date)
                   VALUES
                   ({}) 
                    """.format(scrap_date))
    connection_order_save_db.commit()
    cursor_order_db.close()
    connection_order_save_db.close()


def push_company_infos_to_dbase(seller_id: int, api_key: str, api_secret: str, comp_name: str):
    dbase_path = os.path.join(database_directory_name, "comp_info.db")
    connection_comp_info_db = sql.connect(dbase_path)
    cursor_comp_info_db = connection_comp_info_db.cursor()

    comp_account_tuple = (seller_id, api_key, api_secret, comp_name)
    cursor_comp_info_db.execute("""
                        INSERT OR IGNORE INTO comp_accounts
                            (
                            seller_id,api_key,api_secret,comp_name
                            )
                            VALUES 
                            (?,?,?,?)
                        """, comp_account_tuple)

    connection_comp_info_db.commit()
    cursor_comp_info_db.close()
    connection_comp_info_db.close()


def push_label_datas_to_dbase(label_datas):
    dbase_path = os.path.join(database_directory_name, "label_datas.db")
    connection_rts_datas_db = sql.connect(dbase_path)
    cursor_rts_datas_db = connection_rts_datas_db.cursor()

    cursor_rts_datas_db.executemany("""
                                INSERT OR IGNORE INTO label_datas_eight_format
                                (
                                ORDERNUMBER, CARGOTRACKINGNUMBER, CARGOPROVIDERNAME,
                                CUSTOMERNAME,CUSTOMERSURNAME,cargoTrackingNumberNumeric,
                                LEFTFIRSTPROD,LEFTFIRSTQUANTITY,
                                LEFTSECONDPROD, LEFTSECONDQUANTITY, LEFTTHIRDPROD,
                                LEFTTHIRDQUANTITY,LEFTFOURTHPROD, LEFTFOURTHQUANTITY, RIGHTFIRSTPROD,
                                RIGHTFIRSTQUANTITY, RIGHTSECONDPROD,RIGHTSECONDQUANTITY, RIGHTTHIRDPROD,
                                RIGHTTHIRDQUANTITY,RIGHTFOURTHPROD, RIGHTFOURTHQUANTITY,PAPERNUMBER, FULLADDRESS,
                                ISPRINTED,LASTMODIFIEDDATE,CURRENTPACKAGESTATUS,STATUS
                                
                                     
                                )
                                VALUES 
                                (?,?,?,?,
                                ?,?,?,?,
                                ?,?,?,?,
                                ?,?,?,?,
                                ?,?,?,?,
                                ?,?,?,?,
                                ?,?,?,?)
                                """, label_datas)

    connection_rts_datas_db.commit()
    cursor_rts_datas_db.close()
    connection_rts_datas_db.close()



def push_stock_datas_to_dbase(stock_datas):
    dbase_path = os.path.join(database_directory_name, "stock_datas.db")
    connection_stock_datas_db = sql.connect(dbase_path)
    cursor_stock_datas_db = connection_stock_datas_db.cursor()

    cursor_stock_datas_db.executemany("""
                                INSERT OR IGNORE INTO stock_datas
                                (
                                product_name,
                                product_price,
                                purchase_place,
                                purchase_date,
                                quantity,
                                stock_code,
                                is_have_package_cost
                                )
                                VALUES 
                                (?,?,
                                ?,?,
                                ?,?,
                                ?
                                )
                                """, stock_datas)

    connection_stock_datas_db.commit()
    connection_stock_datas_db.close()


def push_match_datas_to_dbase(match_datas):
    dbase_path = os.path.join(database_directory_name, "stock_datas.db")
    connection_stock_datas_db = sql.connect(dbase_path)
    cursor_stock_datas_db = connection_stock_datas_db.cursor()

    cursor_stock_datas_db.executemany("""
                                    INSERT OR IGNORE INTO match_datas
                                    (
                                    product_stock_code,
                                    package_quantity,
                                    advert_barcode
                                    )
                                    VALUES 
                                    (?,?,
                                    ?
                                    )
                                    """, match_datas)

    connection_stock_datas_db.commit()
    connection_stock_datas_db.close()


def push_license_datas_to_dbase(license_key):
    dbase_path = os.path.join(database_directory_name, "license_info.db")
    connection_license_info_db = sql.connect(dbase_path)
    cursor_license_info_db = connection_license_info_db.cursor()

    cursor_license_info_db.executemany("""
                                    INSERT OR IGNORE INTO license_key
                                    (
                                    license_key,api_token
                                    )
                                    VALUES 
                                    (?,?
                                    )
                                    """, license_key)

    connection_license_info_db.commit()
    connection_license_info_db.close()


def get_order_numbers_from_dbase(order_number):
    dbase_path = os.path.join(database_directory_name, "orders.db")
    connection_order_save_db = sql.connect(dbase_path, check_same_thread=False)
    cursor_order_db = connection_order_save_db.cursor()

    order_numbers = cursor_order_db.execute("""
            SELECT orderNumber from order_datas where orderNumber = '{}'
            """.format(order_number))
    order_numbers = order_numbers.fetchall()
    cursor_order_db.close()
    connection_order_save_db.close()
    return order_numbers


def get_last_scrap_date():
    dbase_path = os.path.join(database_directory_name, "orders.db")
    connection_order_save_db = sql.connect(dbase_path, check_same_thread=False)
    cursor_order_db = connection_order_save_db.cursor()
    create_order_dbase()
    last_scrap_date = cursor_order_db.execute("""
            SELECT MAX(scrap_date) from scrap_datas 
            """)
    last_scrap_date = last_scrap_date.fetchmany(0)

    cursor_order_db.close()
    connection_order_save_db.close()

    return last_scrap_date


def get_seller_id_from_dbase(seller_id):
    dbase_path = os.path.join(database_directory_name, "comp_info.db")
    connection_comp_info_db = sql.connect(dbase_path)
    cursor_comp_info_db = connection_comp_info_db.cursor()

    seller_id_tuple = (seller_id,)
    seller_id = cursor_comp_info_db.execute("""
                                        SELECT seller_id from comp_accounts WHERE seller_id = ?
                                
                                    """, seller_id_tuple)
    seller_id = seller_id.fetchall()
    cursor_comp_info_db.close()
    connection_comp_info_db.close()
    return seller_id


def get_comp_datas_from_dbase():
    dbase_path = os.path.join(database_directory_name, "comp_info.db")
    connection_comp_info_db = sql.connect(dbase_path)
    cursor_comp_info_db = connection_comp_info_db.cursor()

    comp_datas = cursor_comp_info_db.execute("""
                                             SELECT * FROM main.comp_accounts           
                                            """)
    comp_datas = comp_datas.fetchall()

    cursor_comp_info_db.close()
    connection_comp_info_db.close()
    return comp_datas


def get_selected_comps_datas_from_dbase(comp_name):
    dbase_path = os.path.join(database_directory_name, "comp_info.db")
    connection_comp_info_db = sql.connect(dbase_path)
    cursor_comp_info_db = connection_comp_info_db.cursor()
    comp_name_tuple = (comp_name,)
    selected_comp_datas = cursor_comp_info_db.execute("""
                        SELECT * FROM main.comp_accounts WHERE comp_name = ?
                        
                            """, comp_name_tuple)
    return selected_comp_datas.fetchall()



def get_ready_order_labels():
    dbase_path = os.path.join(database_directory_name, "label_datas.db")
    connection_latest_rts_db = sql.connect(dbase_path, check_same_thread=False)

    latest_labels = """
    SELECT * 
    FROM label_datas_eight_format AS main 
    WHERE status = 'Created' 
      AND isPrinted = 'False'
      AND (orderNumber, lastModifiedDate) IN (
          SELECT orderNumber, MAX(lastModifiedDate) 
          FROM label_datas_eight_format 
          GROUP BY orderNumber
      )
    """
    latest_labels_df = pd.read_sql_query(latest_labels, connection_latest_rts_db)

    return latest_labels_df



def get_printed_order_labels():
    dbase_path = os.path.join(database_directory_name, "label_datas.db")
    connection_latest_rts_db = sql.connect(dbase_path, check_same_thread=False)

    printed_labels = """
    SELECT * 
    FROM label_datas_eight_format AS main 
    WHERE isPrinted = 'True'
      AND (orderNumber, lastModifiedDate) IN (
          SELECT orderNumber, MAX(lastModifiedDate) 
          FROM label_datas_eight_format 
          GROUP BY orderNumber
      )
    """
    printed_labels_df = pd.read_sql_query(printed_labels, connection_latest_rts_db)

    return printed_labels_df




def get_product_name_from_dbase(text):
    dbase_path = os.path.join(database_directory_name, "stock_datas.db")
    try:

        connection_stock_data_db = sql.connect(dbase_path, check_same_thread=False)
        cursor_stock_data_db = connection_stock_data_db.cursor()

        product_datas_query = "SELECT * FROM stock_datas WHERE product_name LIKE ? || '%'"
        product_datas = cursor_stock_data_db.execute(product_datas_query, (text,))

    except Exception as e:
        print(e)

    return product_datas


def get_purchase_place_from_dbase(text):
    try:

        dbase_path = os.path.join(database_directory_name, "stock_datas.db")
        connection_stock_data_db = sql.connect(dbase_path, check_same_thread=False)
        cursor_stock_data_db = connection_stock_data_db.cursor()

        product_datas_query = "SELECT * FROM stock_datas WHERE purchase_place LIKE ? || '%'"
        product_datas = cursor_stock_data_db.execute(product_datas_query, (text,))

    except Exception as e:
        print(e)

    return product_datas


def get_product_sc_from_dbase(barcode):
    try:
        dbase_path = os.path.join(database_directory_name, "stock_datas.db")
        connection_stock_data_db = sql.connect(dbase_path, check_same_thread=False)
        cursor_stock_data_db = connection_stock_data_db.cursor()

        advert_datas_query = "SELECT * FROM match_datas WHERE advert_barcode = ?"
        advert_datas = cursor_stock_data_db.execute(advert_datas_query, (barcode,))

    except Exception as e:
        print(e)
    else:
        return advert_datas


def get_product_price_from_dbase(prod_stock_code):
    try:
        dbase_path = os.path.join(database_directory_name, "stock_datas.db")
        connection_stock_data_db = sql.connect(dbase_path, check_same_thread=False)
        cursor_stock_data_db = connection_stock_data_db.cursor()

        stock_datas_query = "SELECT * FROM stock_datas WHERE stock_code = ?"
        stock_datas = cursor_stock_data_db.execute(stock_datas_query, (prod_stock_code,))

    except Exception as e:
        print(e)
    else:
        return stock_datas


def get_license_status_from_dbase():
    try:
        dbase_path = os.path.join(database_directory_name, "license_info.db")
        connection_license_info_db = sql.connect(dbase_path, check_same_thread=False)
        cursor_license_info_db = connection_license_info_db.cursor()

        license_info_query = "SELECT * FROM license_key"
        license_info = cursor_license_info_db.execute(license_info_query)

    except Exception as e:
        print(e)
    else:
        return license_info



def get_waiting_order_items():
    try:
        dbase_path = os.path.join(database_directory_name, "orders.db")
        connection_order_items_db = sql.connect(dbase_path, check_same_thread=False)

        query = """
        WITH MaxTaskDates AS (
            SELECT orderNumber, MAX(taskDate) AS maxTaskDate
            FROM order_items
            GROUP BY orderNumber
        )
        SELECT 
            oi.barcode, 
            SUM(oi.quantity) AS total_quantity, 
            oi.productSize, 
            oi.merchantSku, 
            oi.productName, 
            oi.productCode
        FROM order_items AS oi
        JOIN MaxTaskDates AS mtd
        ON oi.orderNumber = mtd.orderNumber AND oi.taskDate = mtd.maxTaskDate
        WHERE oi.orderLineItemStatusName = 'ReadyToShip'
        GROUP BY oi.barcode, oi.productSize, oi.merchantSku, oi.productName, oi.productCode
        ORDER BY oi.productName;
        """

        df = pd.read_sql_query(query, connection_order_items_db)

    except Exception as e:
        print(e)
        df = pd.DataFrame()  # Hata durumunda boş bir DataFrame döndür

    finally:
        connection_order_items_db.close()

    return df

def update_label_printing_status(order_number, new_value):
    try:
        # Veritabanı bağlantısını oluştur
        dbase_path = os.path.join(database_directory_name, "label_datas.db")
        connection_rts_datas_db = sql.connect(dbase_path, check_same_thread=False)
        cursor_rts_datas_db = connection_rts_datas_db.cursor()

        # Güncelleme sorgusunu hazırla
        update_query = "UPDATE label_datas_eight_format SET isPrinted = ? WHERE orderNumber = ?"
        cursor_rts_datas_db.execute(update_query, (new_value, order_number))

        # Değişiklikleri kaydet
        connection_rts_datas_db.commit()

    except Exception as e:
        print(e)
    finally:
        # Bağlantıyı kapat
        connection_rts_datas_db.close()


def drop_license_info_db():
    dbase_path = os.path.join(database_directory_name, "license_info.db")
    connection_license_info_db = sql.connect(dbase_path)
    cursor_license_info_db = connection_license_info_db.cursor()

    # Tabloyu sil
    cursor_license_info_db.execute("DROP TABLE IF EXISTS license_key")

    connection_license_info_db.commit()
    cursor_license_info_db.close()
    connection_license_info_db.close()
