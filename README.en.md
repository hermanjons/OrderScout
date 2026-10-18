<p align="center"><img src="desktop/images/orderscout-logo.png" alt="OrderScout" width="112"></p>
<h1 align="center">OrderScout</h1>
<p align="center"><strong>Your orders, inventory and margins in one desktop workspace.</strong></p>
<p align="center">Windows · Python · PyQt6 · SQLite · Open source</p>
<p align="center"><a href="README.md">Türkçe</a> · <a href="https://github.com/hermanjons/OrderScout-releases/releases">Download</a> · <a href="CONTRIBUTING.md">Contribute</a></p>

OrderScout is a Windows desktop application for managing Trendyol orders,
returns, inventory, product costs and shipping labels. Business data is stored
locally in SQLite. Connect your own marketplace account to synchronize orders
and listings.

**No activation key or OrderScout subscription is required.** Donations are
optional and never unlock features. External marketplace and AI service terms
and charges still apply.

## What is included?

- Order and return workspaces.
- Listings, inventory cards, warehouses and stock movements.
- Product costs, commissions, cargo tariffs and profitability views.
- Shipping label templates and document export.
- Multiple company and marketplace accounts.
- An experimental AI workspace with local and external provider options.

Trendyol is the active integration focus. Configuration for another marketplace
does not imply a finished integration. See [project status](docs/project-status.md)
for the current limits.

## Run from source

Use **Windows with Python 3.11**:

```powershell
git clone https://github.com/hermanjons/OrderScout.git
cd OrderScout
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
cd desktop
..\.venv\Scripts\python.exe main.py
```

For the packaged application, use the separate
[download repository](https://github.com/hermanjons/OrderScout-releases/releases).

## Privacy and security

Application data lives under `%LOCALAPPDATA%\OrderScout`. Windows DPAPI is used
by the credential store at `%USERPROFILE%\.orderscout`; legacy account fields
may still contain plaintext credentials. Do not share your database, credential
store, exports, logs or customer data. Marketplace synchronization contacts the
marketplace. External AI features may send relevant business data to your chosen
provider.

[Setup](docs/setup.md) · [Architecture](docs/architecture.md) ·
[Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md)

## License

Original OrderScout source code is licensed under **GPL-3.0-or-later**.
Copyright © 2026 OrderScout contributors. See [LICENSE](LICENSE) and
[third-party notices](THIRD_PARTY_NOTICES.md).
