
from profit_calculates import calculate_profit
import pandas as pd
from encode_tasks import encode_code_128



order_data_list = []  # ham datalar listesi
order_item_list = []  # ham datalar listesi
label_data_list = []  # ham datalar listesi

order_datas_list = []  # sipariş verilerinin veritabanına kayıt edilmeye hazır hali
order_items_list = []  # sipariş verilerinin veritabanına kayıt edilmeye hazır hali

label_datas_list = []  # sipariş etiketlerinin veritabanına kayıt edilmeye hazır hali

stock_datas_list = []  # xlsx dosyasından gelen stok verilerinin tutulduğu tuple verilerin tutulduğu liste





def get_label_datas_from_list(order_data):
    data_list = []

    for r_order in order_data:
        order_number = r_order.get("orderNumber", "")
        cargo_tracking_number = str(r_order.get("cargoTrackingNumber", ""))
        ctn_encoded = encode_code_128(cargo_tracking_number)
        cargo_provider_name = r_order.get("cargoProviderName", "")
        name = r_order.get("customerFirstName", "")
        surname = r_order.get("customerLastName", "")
        order_id = r_order.get("id", "")
        order_items_cell = ""
        current_package_status = r_order.get("shipmentPackageStatus")
        status = r_order.get("status")
        address = r_order.get("shipmentAddress", {}).get("fullAddress", "")
        last_modified_date = r_order.get("lastModifiedDate", "")

        for order_item in order_item_list:
            if order_item.get("orderNumber") == order_number and order_item.get("id") == order_id:
                order_items_cell += str(order_item.get("quantity", "")) + "," + order_item.get("merchantSku", "") + ";"

        label_data_tuple = (
            order_number, ctn_encoded, cargo_provider_name, name, surname, cargo_tracking_number,
            order_items_cell.rstrip(";"),
            address,
            last_modified_date, current_package_status, status)

        data_list.append(label_data_tuple)

    return data_list


def create_error_tuple(message, length):
    return tuple([message] * length)


def get_nested_value(data, field):
    """Verilen veri sözlüğünden iç içe geçmiş değeri getirir."""
    keys = field.split('.')
    for key in keys:
        data = data.get(key, None)
        if data is None:
            break
    return data


def push_orders_to_tuple(scrap_time, comp_api_account_list: list):
    """
    sipariş verilerinin tümünü bir tuple içerisine atıp daha sonra tuple veriyi bir listeye kaydeden fonksiyon
    :param comp_api_account_list: veri çekilmesi istenen hesapların api bilgilerini içeren bir liste
    :param scrap_time: bu parametre auto ya da manuel şeklinde iki değer alabilir.
    :return: Listeye 'created' parametresiyle getirilen verileri ekleyecektir.
    """
    # Listeleri temizle
    order_data_list.clear()
    order_datas_list.clear()
    order_item_list.clear()
    order_items_list.clear()

    # order_item_list için alanlar
    order_item_fields = [
        "quantity", "salesCampaignId", "productSize", "merchantSku", "productCode", "amount", "productName",
        "merchantId", "discount", "tyDiscount", "currencyCode", "id", "sku", "vatBaseAmount", "barcode",
        "orderLineItemStatusName", "price", "orderNumber", "taskDate"
    ]

    # order_data_list için alanlar
    order_data_fields = [
        "shipmentAddress.fullAddress", "orderNumber", "grossAmount", "totalDiscount", "totalTyDiscount",
        "invoiceAddress.fullAddress", "customerFirstName", "customerId", "customerLastName", "id",
        "cargoTrackingNumber",
        "cargoProviderName", "orderDate", "tcIdentityNumber", "currencyCode", "shipmentPackageStatus", "status",
        "deliveryType", "timeSlotId", "estimatedDeliveryStartDate", "estimatedDeliveryEndDate", "totalPrice",
        "deliveryAddressType", "agreedDeliveryDate", "fastDelivery", "originShipmentDate", "lastModifiedDate",
        "commercial", "fastDeliveryType", "deliveredByService", "agreedDeliveryDateExtendible",
        "extendedAgreedDeliveryDate",
        "agreedDeliveryExtensionEndDate", "agreedDeliveryExtensionStartDate", "warehouseId", "groupDeal",
        "cargoTrackingNumber"
    ]

    # Scrap time'a göre siparişleri getir
    if scrap_time == "auto":
        optimal_ftime_for_scrap = get_last_scrap_date()[0][0] - time_stamp_calculator(0.01)
        for mode in status_list:
            find_orders_to_list(mode, optimal_ftime_for_scrap, time_for_now(), comp_api_account_list, 0)
    else:
        for mode in status_list:
            find_orders_to_list(mode, scrap_time, time_for_now(), comp_api_account_list, 0)

    # order_data_list'i işle ve tuple olarak kaydet
    for order_data in order_data_list:
        try:
            order_data_tuple = tuple(get_nested_value(order_data, field) for field in order_data_fields)
            order_datas_list.append(order_data_tuple)
        except KeyError as e:
            error_tuple = create_error_tuple(f"Missing key: {e}", len(order_data_fields))
            order_datas_list.append(error_tuple)
        except Exception as e:
            error_tuple = create_error_tuple(f"Error: {e}", len(order_data_fields))
            order_datas_list.append(error_tuple)

    # order_item_list'i işle ve tuple olarak kaydet
    for order_item in order_item_list:
        try:
            order_item_tuple = tuple(order_item[field] for field in order_item_fields)
            order_items_list.append(order_item_tuple)
        except KeyError as e:
            error_tuple = create_error_tuple(f"Missing key: {e}", len(order_item_fields))
            order_items_list.append(error_tuple)
        except Exception as e:
            error_tuple = create_error_tuple(f"Error: {e}", len(order_item_fields))
            order_items_list.append(error_tuple)


def push_labels_to_tuple():
    label_data_list.clear()
    label_datas_list.clear()

    label_datas = get_label_datas_from_list(order_data_list)
    for label_data in label_datas:
        # print("ham veri : ", label_data)
        order_items = label_data[6].split(";")

        divisible_amount = len(order_items) // 8
        remaining_amount = len(order_items) % 8
        correction_list = [" , " for _ in range(8 - remaining_amount)]

        if len(order_items) <= 8:
            # print("düzeltme listesi : ", correction_list)
            # print("önceki hali :",order_items)
            order_items.extend(correction_list)
            # print("son hal : ", order_items)
            label_data_tuple = (
                label_data[0], label_data[1], label_data[2], label_data[3], label_data[4], label_data[5], order_items,
                1, label_data[7], label_data[8], label_data[9], label_data[10])
            label_data_list.append(label_data_tuple)

        else:

            section_start = 0

            for section_stop in range(1, divisible_amount + 1):
                label_data_tuple = (label_data[0], label_data[1], label_data[2], label_data[3], label_data[4],
                                    label_data[5], order_items[section_start:section_stop * 8],
                                    "{0}/{1}".format(section_stop, divisible_amount + 1), label_data[7],
                                    label_data[8], label_data[9], label_data[10])
                label_data_list.append(label_data_tuple)
                section_start = section_stop * 8

            patched_order_items = order_items[-remaining_amount:]
            patched_order_items.extend(correction_list)
            label_data_tuple = (
                label_data[0], label_data[1], label_data[2], label_data[3], label_data[4], label_data[5],
                patched_order_items, "{0}/{1}".format(divisible_amount + 1,
                                                      divisible_amount + 1), label_data[7], label_data[8],
                label_data[9], label_data[10])

            label_data_list.append(label_data_tuple)

    for rts_data in label_data_list:
        label_datas_tuple = (
            rts_data[0], rts_data[1], rts_data[2], rts_data[3],
            rts_data[4], rts_data[5], rts_data[6][0].split(",")[1],
            rts_data[6][0].split(",")[0],
            rts_data[6][1].split(",")[1],
            rts_data[6][1].split(",")[0],
            rts_data[6][2].split(",")[1],
            rts_data[6][2].split(",")[0],
            rts_data[6][3].split(",")[1],
            rts_data[6][3].split(",")[0],
            rts_data[6][4].split(",")[1],
            rts_data[6][4].split(",")[0],
            rts_data[6][5].split(",")[1],
            rts_data[6][5].split(",")[0],
            rts_data[6][6].split(",")[1],
            rts_data[6][6].split(",")[0],
            rts_data[6][7].split(",")[1],
            rts_data[6][7].split(",")[0],
            rts_data[7], rts_data[8], "False", rts_data[9],
            rts_data[10], rts_data[11]
        )

        label_datas_list.append(label_datas_tuple)


def push_stock_datas_to_tuple_from_xlsx(excel_file_path):
    data = pd.read_excel(excel_file_path, engine="openpyxl")
    for data in data.iterrows():
        data = data[1]

        stok_datas_tuple = (data[0], data[1], data[2], str(data[3]), data[4], data[5], data[6])
        stock_datas_list.append(stok_datas_tuple)


def calculate_profit_with_excel(excel_file_path, other_prices, progress_callback: None):
    empty_barcodes = []
    total_profit = 0
    total_delivered_product_price = 0
    total_comission = 0
    total_tax = 0
    total_cargo = 0
    total_otp = 0
    total_sell_price = 0

    profit_dict = {
        "sipariş no": [],
        "sipariş karı": [],
        "top_ort_ürün_fiyat": []
    }
    try:
        data = pd.read_excel(excel_file_path, engine='openpyxl')
        data_frames = data.groupby("Sipariş Numarası")
        working_order_turn = 1

        for order_number, order_frame in data_frames:
            item_cnt = 1
            total_order_profit = 0
            total_product_price = 0

            for order_item in order_frame.iterrows():
                barcode = order_item[1][0]
                advert_datas = get_product_sc_from_dbase(barcode).fetchall()
                if len(advert_datas) == 0:
                    empty_barcodes.append(barcode)
                else:

                    for advert_data in advert_datas:
                        stock_datas = get_product_price_from_dbase(advert_data[0]).fetchall()
                        total_prod_price = 0
                        total_prod_quantity = 0
                        for stock_data in stock_datas:
                            prod_price = float(stock_data[1])
                            prod_quantity = int(stock_data[4])
                            total_prod_quantity += prod_quantity
                            total_prod_price += (prod_price * prod_quantity)

                    cargo = order_item[1][28]

                    if item_cnt > 1:
                        cargo = 0
                        otp = 0
                    else:
                        if type(cargo) == str and cargo == "Henüz fatura kesilmemiştir":
                            cargo = 15.49
                        elif type(cargo) == float:
                            cargo = cargo
                        otp = other_prices
                    print("kargo", cargo)
                    print("item sıra", item_cnt)
                    total_otp = total_otp + otp
                    total_cargo = total_cargo + cargo
                    avg_price = (total_prod_price / total_prod_quantity) * int(advert_data[1])
                    avg_price = avg_price * order_item[1][18]
                    comission_ratio = float(order_item[1][15])
                    sell_price = float(order_item[1][23])
                    total_delivered_product_price = total_delivered_product_price + avg_price
                    item_profit = calculate_profit(avg_price, sell_price,
                                                   comission_ratio, cargo, 10, 20, 20, otp)
                    comission = float(item_profit[2])
                    tax = item_profit[1]
                    total_tax = total_tax + tax

                    print("komisyon ", comission)
                    print(type(comission))
                    print(type(total_comission))
                    total_profit = total_profit + item_profit[0]
                    total_order_profit = total_order_profit + item_profit[0]
                    total_product_price = total_product_price + avg_price
                    item_cnt = item_cnt + 1
                    total_comission = total_comission + comission
                    total_sell_price = total_sell_price + sell_price

            profit_dict["sipariş no"].append(order_number)
            profit_dict["sipariş karı"].append(total_order_profit)
            profit_dict["top_ort_ürün_fiyat"].append(total_product_price)
            working_order_turn = working_order_turn + 1
            progress_callback.emit(working_order_turn * (100 / len(data_frames)))

        print(len(empty_barcodes))
        unique_set = set(empty_barcodes)
        empty_barcodes = list(unique_set)
        profit_df = pd.DataFrame(profit_dict)
        profit_df.to_excel("profit_report.xlsx")
        print(empty_barcodes)
    except Exception as e:
        print("Excel dosyası okuma hatası:", str(e))



    else:
        return round(total_profit), profit_df, total_delivered_product_price, \
               total_comission, total_tax, total_cargo, total_otp, total_sell_price
