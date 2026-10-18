# Domain Test Yapısı

Bu klasör, mevcut mimariyi bozmadan domain bazlı testleri ayırmak için oluşturuldu.

## Klasörler
- `tests/domain_account`
- `tests/domain_orders`
- `tests/domain_listing`
- `tests/domain_labels`
- `tests/domain_testing`
- `tests/domain_main`
- `tests/domain_core`
- `tests/domain_update`

## Çalıştırma
```bash
py -3 -m unittest discover -s tests -p "test_*.py" -v
```

## Notlar
- `tests/support/db_case.py` her test için izole SQLite DB oluşturur.
- Integration benzeri testlerde DB yolu explicit parametre ile verilir.
- UI ve network'e doğrudan bağımlı akışlarda unit/mocking tercih edilir.
- `domain_testing` Test Lab backend'inin listing-tabanlı sipariş simülasyonu,
  domain healthcheck ve local unittest runner akışını doğrular.
