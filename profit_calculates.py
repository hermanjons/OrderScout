def calculate_profit(product_price: float, sell_price: float,
                     commission_ratio: float, cargo: float, product_reel_tax_ratio: float,
                     product_ofc_tax_ratio: float, general_tax_ratio: float, other_prices: float):


    commission_and_tax = sell_price * (commission_ratio / 100)

    product_reel_price = product_price + (product_price * product_reel_tax_ratio/100)
    tax_from_buy = (product_price * product_ofc_tax_ratio/100)
    tax_from_commission = (commission_and_tax / (100+general_tax_ratio)) * general_tax_ratio

    tax_from_cargo = (cargo / (100+general_tax_ratio))*general_tax_ratio
    tax_from_sell = (sell_price / (product_ofc_tax_ratio+100))*product_ofc_tax_ratio

    tax_from_other_prices = other_prices * (general_tax_ratio / 100)
    other_prices_and_tax = tax_from_other_prices + other_prices

    total_tax = tax_from_sell - (tax_from_buy + tax_from_commission
                                 + tax_from_cargo + tax_from_other_prices)


    profit = sell_price - (commission_and_tax + cargo + product_reel_price + total_tax + other_prices_and_tax)

    return profit, total_tax, commission_and_tax



