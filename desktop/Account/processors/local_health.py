"""Persisted account state; this operation does not test remote connectivity."""
import unicodedata

from Marketplaces.processors.catalog import normalize_marketplace_environment
from Feedback.processors.pipeline import Result
from Account.processors.agentic_repository import list_accounts
from settings import DB_NAME


def local_account_evidence():
    return {"evidence_basis": "persisted_local_account_flags", "remote_connection_verified": False,
            "network_request_performed": False, "diagnosed_failure_cause": None,
            "interpretation_limits": ["A stored token_valid=false flag is not a current API authentication test.",
                "The flag does not establish or rank causes: invalid credentials, IP restrictions, lack of orders or token expiry.",
                "No automatic credential renewal capability is established by this read."]}


def local_account_status(account):
    """The same local status used by the manual account table and diagnostics."""
    def value(key, default=None):
        return account.get(key, default) if isinstance(account, dict) else getattr(account, key, default)
    active = bool(value("is_active", False))
    token_flag = bool(value("token_valid", True))
    return {"is_active": active, "stored_token_valid": token_flag,
            "display_status": "Aktif" if active and token_flag else "Pasif",
            "evidence_basis": "persisted_local_account_flags", "remote_connection_verified": False}


def summarize_local_account_health(*, api_account_ids=None, db_name=DB_NAME):
    result = list_accounts(pks=api_account_ids, db_name=db_name)
    if not result.success:
        return result
    rows = list(result.data.get("records") or [])
    accounts, platforms = [], {}
    for row in rows:
        status = local_account_status(row)
        platform = str(row.platform or "unknown")
        bucket = platforms.setdefault(platform, {"total": 0, "active": 0, "invalid_token": 0})
        bucket["total"] += 1
        bucket["active"] += int(status["is_active"])
        bucket["invalid_token"] += int(not status["stored_token_valid"])
        accounts.append({"api_account_id": row.pk, "account_id": row.account_id, "company": row.comp_name,
            "store_name": row.comp_name, "platform": platform,
            "environment": normalize_marketplace_environment((row.extra_config or {}).get("environment")),
            **status, "token_valid": status["stored_token_valid"]})
    attention = [row for row in accounts if row["is_active"] and not row["stored_token_valid"]]
    return Result.ok("Hesapların kayıtlı yerel durumları okundu; uzaktan bağlantı testi yapılmadı.", close_dialog=False,
        data={"accounts_total": len(accounts), "accounts_active": sum(row["is_active"] for row in accounts),
              "invalid_tokens": len(attention), "by_platform": platforms, "accounts": accounts,
              "attention_accounts": attention[:12], **local_account_evidence()})


def _search_text(value):
    text = str(value or "").casefold().translate(str.maketrans("ığüşöç", "igusoc"))
    return " ".join("".join(char for char in unicodedata.normalize("NFKD", text)
                           if not unicodedata.combining(char)).split())


def lookup_local_accounts(*, query="", limit=10, db_name=DB_NAME):
    """Resolve a store from local metadata, without exposing its credentials."""
    limit = max(1, min(50, int(limit or 10)))
    result = list_accounts(db_name=db_name)
    if not result.success:
        return result
    clean_query = _search_text(query)
    terms = [part for part in clean_query.replace("-", " ").replace("_", " ").split() if len(part) >= 2]
    scored = []
    for row in result.data.get("records") or []:
        haystack = " ".join(_search_text(getattr(row, key, ""))
                            for key in ("comp_name", "platform", "account_id", "integration_code"))
        score = (30 if clean_query in haystack else 0) + sum(4 for term in terms if term in haystack)
        if clean_query and score <= 0:
            continue
        scored.append((score, row))
    scored.sort(key=lambda pair: (pair[0], str(pair[1].comp_name or "").casefold()), reverse=True)
    accounts, scopes = [], []
    for _score, row in scored[:limit]:
        extra = row.extra_config or {}
        environment = normalize_marketplace_environment(extra.get("environment") or extra.get("api_environment") or "production")
        scope = {"api_account_id": row.pk, "account_id": str(row.account_id or ""),
                 "store_name": str(row.comp_name or ""), "platform": str(row.platform or ""),
                 "environment": environment, "environment_source": "account_configuration"}
        scopes.append(scope)
        status = local_account_status(row)
        accounts.append({**scope, "company": scope["store_name"], **status,
                         "token_valid": status["stored_token_valid"]})
    return Result.ok(f"{len(accounts)} yerel hesap kaydı bulundu; bağlantı testi yapılmadı.", close_dialog=False,
        data={"query": query, "count": len(accounts), "total_matching": len(scored),
              "truncated": len(scored) > len(accounts), "accounts": accounts, "account_scopes": scopes,
              **local_account_evidence(), "read_evidence": {"source": "local_database",
                  "status": "nonempty" if scored else "empty", "scope": "matching_accounts" if clean_query else "all_accounts"}})
