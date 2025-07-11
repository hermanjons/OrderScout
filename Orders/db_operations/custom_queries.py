get_waiting_order_items_query = """
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


product_datas_query = "SELECT * FROM stock_datas WHERE purchase_place LIKE ? || '%'"




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


last_scrap_date = cursor_order_db.execute("""
            SELECT MAX(scrap_date) from scrap_datas 
            """)