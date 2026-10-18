from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from Core.processors.operation_contracts import OperationMetadata


_DESKTOP_ROOT = Path(__file__).resolve().parents[2]

_ACTION_FILES = {
    "ai": _DESKTOP_ROOT / "AI" / "views" / "actions.py",
    "account": _DESKTOP_ROOT / "Account" / "views" / "actions.py",
    "finance": _DESKTOP_ROOT / "Finance" / "views" / "actions.py",
    "labels": _DESKTOP_ROOT / "Labels" / "views" / "actions.py",
    "listing": _DESKTOP_ROOT / "Listing" / "views" / "actions.py",
    "logistics": _DESKTOP_ROOT / "Logistics" / "views" / "actions.py",
    "marketplaces": _DESKTOP_ROOT / "Marketplaces" / "views" / "actions.py",
    "orders": _DESKTOP_ROOT / "Orders" / "views" / "actions.py",
    "stock": _DESKTOP_ROOT / "Stock" / "views" / "actions.py",
    "testing": _DESKTOP_ROOT / "Testing" / "views" / "actions.py",
    "update": _DESKTOP_ROOT / "Update" / "views" / "actions.py",
}

_READ_PREFIXES = (
    "action_get_",
    "action_list_",
    "action_load_",
    "get_",
    "list_",
    "fetch_",
    "export_",
    "action_validate_",
    "action_verify_",
    "action_run_local_unittest_suite",
    "action_run_domain_healthcheck",
    "load_",
)
_WRITE_PREFIXES = (
    "action_create_",
    "action_update_",
    "action_delete_",
    "action_activate_",
    "action_deactivate_",
    "action_set_",
    "action_sync_",
    "action_simulate_",
    "action_build_",
    "action_publish_",
    "action_configure_",
    "action_auto_",
    "action_adjust_",
    "action_manual_",
    "action_export_",
    "action_download_",
    "action_save_",
    "save_",
    "delete_",
    "accept_",
    "set_",
    "approve_",
    "update_",
    "create_",
    "change_",
    "mark_",
    "restore_",
)
_DESTRUCTIVE_TOKENS = ("delete", "deactivate", "publish", "approve", "cancel", "reject")
_EXTERNAL_TOKENS = ("fetch", "sync", "download", "publish", "activate", "approve", "api", "release")
MANUAL_EXECUTE_ADAPTERS = {
    "account.delete_company_and_refresh": "Account.processors.pipeline.delete_company_from_db",
    "finance.action_sync_finance_for_accounts": "Finance.views.actions.action_sync_finance_for_accounts",
    "finance.action_sync_finance_for_selected_companies": "finance.action_sync_finance_for_company_pks",
    "labels.action_create_labels_from_selected_orders": "Labels.processors.pipeline.create_order_label_from_orders",
    "labels.mark_orders_extracted_from_label_result": "Labels.views.actions.mark_orders_extracted_from_label_result",
    "listing.action_fetch_listings": "Listing.views.actions.action_fetch_listings+Listing.processors.pipeline.save_listings_to_db",
    "listing.action_update_approved_content_for_account": "Listing.views.actions.action_update_approved_content_for_account",
    "orders.get_orders_from_companies": "Orders.processors.trendyol.pipeline.fetch_orders_all+save_orders_to_db",
    "orders.save_return_claims_to_db": "Orders.processors.trendyol.pipeline.save_return_claims_to_db",
    "orders.mark_return_claims_stale": "Orders.processors.trendyol.pipeline.mark_return_claims_stale",
    "orders.restore_return_claims_from_stale": "Orders.processors.trendyol.pipeline.restore_return_claims_from_stale",
    "orders.update_last_used_at_for_accounts": "Orders.processors.trendyol.pipeline.update_last_used_at_for_accounts",
    "orders.change_order_cargo_provider": "Orders.views.actions.change_order_cargo_provider",
    "orders.change_orders_cargo_provider_bulk": "Orders.views.actions.change_orders_cargo_provider_bulk",
}
_MODE_OVERRIDES = {
    "listing.action_fetch_listings": "write",
    "orders.get_orders_from_companies": "write",
    "orders.mark_return_claims_stale": "write",
    "orders.restore_return_claims_from_stale": "write",
}
_EXTERNAL_WRITE_OVERRIDES = {
    "listing.action_fetch_listings",
    "listing.action_update_approved_content_for_account",
    "listing.action_update_price_inventory_for_account",
    "orders.get_orders_from_companies",
    "orders.change_order_cargo_provider",
    "orders.change_orders_cargo_provider_bulk",
}
_READ_BLOCKER_OVERRIDES = {
    "orders.fetch_orders_all": "raw marketplace fetch helper; use orders.get_orders_from_companies approval flow",
}
_REQUIRED_PARAMETER_OVERRIDES = {
    "account.delete_company_and_refresh": ["pk"],
    "finance.action_sync_finance_for_selected_companies": ["selected_company_pks"],
    "labels.action_create_labels_from_selected_orders": ["order_numbers"],
    "labels.mark_orders_extracted_from_label_result": ["order_numbers"],
    "orders.get_orders_from_companies": ["accounts"],
    "orders.save_return_claims_to_db": ["return_claim_list"],
    "orders.mark_return_claims_stale": ["claim_ids"],
    "orders.restore_return_claims_from_stale": ["claim_ids"],
    "orders.update_last_used_at_for_accounts": ["accounts"],
    "orders.change_order_cargo_provider": ["order", "cargo_provider_code"],
    "orders.change_orders_cargo_provider_bulk": ["orders", "cargo_provider_code"],
    "listing.action_fetch_listings": ["api_account_ids"],
    "listing.action_update_approved_content_for_account": ["api_account_id", "items"],
    "listing.action_update_price_inventory_for_account": ["api_account_id", "items"],
    "stock.action_export_txs_excel": ["tx_ids", "output_path"],
}
_UI_PARAMETER_NAMES = {
    "table",
    "widget",
    "parent_widget",
    "progress_target",
    "view_instance",
    "dialog_instance",
    "list_widget",
    "company_list_widget",
}
_DOMAIN_ALIASES = {
    "ai": ("ai", "yapay zeka", "model", "provider", "hf", "huggingface", "ayar"),
    "account": ("hesap", "firma", "account", "platform"),
    "finance": ("finans", "maliyet", "gider", "fatura", "nakit", "marka", "sirket", "şirket"),
    "labels": ("etiket", "etiketi", "etiketini", "label", "yazdir", "yazdır"),
    "listing": ("ilan", "listing", "urun", "ürün", "fiyat", "stok", "pazaryeri"),
    "logistics": ("lojistik", "kargo", "tarife", "cargo"),
    "marketplaces": ("pazaryeri", "marketplace", "platform"),
    "orders": ("siparis", "sipariş", "order", "iade", "return", "claim", "kargo"),
    "stock": ("stok", "envanter"),
    "testing": ("test", "simule", "simulate", "saglik", "sağlık", "release"),
    "update": ("guncelleme", "güncelleme", "update", "surum", "sürüm"),
}
_ACTION_ALIASES = {
    "create": (
        "olustur",
        "olusturmak",
        "olusturmayi",
        "olusturulmasini",
        "oluştur",
        "oluşturmak",
        "oluşturmayı",
        "oluşturulmasını",
        "ekle",
        "yeni",
        "kaydet",
        "kaydetmek",
        "kaydetmeye",
        "kaydetmeyi",
        "kaydedilmesini",
        "create",
        "add",
    ),
    "update": ("guncelle", "güncelle", "degistir", "değiştir", "duzenle", "düzenle", "update"),
    "delete": ("sil", "kaldir", "kaldır", "delete"),
    "list": ("listele", "goster", "göster", "getir", "bak", "list"),
    "get": ("getir", "bul", "ara", "oku", "kontrol", "get"),
    "generate": ("uret", "uretmek", "üret", "üretmek", "generate"),
    "sync": ("senkron", "sync", "cek", "çek", "indir"),
    "save": (
        "kaydet",
        "kaydetmek",
        "kaydetmeye",
        "kaydetmeyi",
        "kaydedilmesini",
        "ekle",
        "save",
        "sakla",
    ),
    "manual": ("manuel", "hareket", "hareketi"),
    "export": ("export", "disa", "dışa", "excel", "aktar"),
    "activate": ("aktif", "activate", "etkinlestir", "etkinleştir"),
    "deactivate": ("pasif", "deactivate", "devre disi", "devre dışı"),
    "approve": ("onay", "onayla", "onaylat", "kabul", "kabul et", "approve"),
    "fetch": ("cek", "çek", "fetch", "indir"),
    "download": ("indir", "download", "yukle", "yükle"),
    "simulate": ("simule", "simulate", "sahte", "test"),
}
_ENTITY_ALIASES = {
    "brand": ("marka", "markasi", "markasini"),
    "company": ("sirket", "şirket", "firma"),
    "warehouse": ("depo", "deposu", "depoyu", "deposunu"),
    "account": ("hesap", "hesabi", "hesabini", "hesaplari", "account", "accounts"),
    "item": ("kart", "urun", "ürün", "kalem", "kalemi"),
    "stock": ("stok",),
    "tx": ("hareket", "hareketi", "islem", "işlem"),
    "barcode": ("barkod",),
    "label": ("etiket", "etiketi", "etiketini"),
    "labels": ("etiket", "etiketi", "etiketini"),
    "return": ("iade",),
    "returns": ("iade",),
    "claim": ("iade", "talep"),
    "order": ("siparis", "sipariş"),
    "orders": ("siparis", "sipariş"),
    "tariff": ("tarife", "tarifesi", "tarifesini"),
    "cargo": ("kargo",),
    "listing": ("ilan",),
    "marketplace": ("pazaryeri", "pazaryerini", "pazaryerine", "pazaryerinde"),
    "finance": ("finans",),
    "cost": ("maliyet", "gider"),
    "invoice": ("fatura",),
    "manual": ("manuel",),
    "model": ("model",),
    "provider": ("provider", "saglayici", "sağlayıcı"),
    "root": ("root", "klasor", "klasoru", "klasorunu", "folder", "dizin", "indirme klasoru", "download root"),
    "runtime": ("runtime", "calisma"),
    "settings": ("ayar", "ayarlar", "settings"),
    "in": ("giris", "giriş", "girdi"),
    "out": ("cikis", "çıkış", "cikti"),
}


@dataclass(frozen=True)
class ManualCapability:
    capability_id: str
    domain: str
    function_name: str
    module_path: str
    source_path: str
    parameters: list[str]
    required_parameters: list[str]
    is_async: bool
    mode: str
    risk_level: str
    requires_approval: bool
    destructive: bool
    external_write: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["operation_metadata"] = self.operation_metadata().to_dict()
        return payload

    def operation_metadata(self) -> OperationMetadata:
        effect_class = (
            "read"
            if self.mode == "read"
            else "external_mutation"
            if self.external_write
            else "local_effect"
        )
        risk_level = "R0" if self.mode == "read" else "R2" if self.external_write else "R1"
        properties = {
            parameter.lstrip("*"): {}
            for parameter in self.parameters
            if parameter and not parameter.startswith("*")
        }
        record_ref_types = ()
        if self.domain in {"orders", "labels"}:
            record_ref_types = ("orders.order", "orders.return_claim")
        elif self.domain:
            record_ref_types = (f"{self.domain}.record",)
        return OperationMetadata(
            name=self.capability_id,
            version="1.0",
            owner_domain=self.domain,
            effect_class=effect_class,
            input_schema={
                "type": "object",
                "properties": properties,
                "required": list(self.required_parameters),
                "additionalProperties": any(
                    parameter.startswith("**") for parameter in self.parameters
                ),
            },
            output_schema={"type": "object", "additionalProperties": True},
            record_ref_types=record_ref_types,
            environment_scope=("local",) if self.mode == "read" else ("local", "production", "stage"),
            account_scope="runtime_resolved",
            risk_level=risk_level,
            approval_policy="none" if self.mode == "read" else "prepare_then_confirm",
            idempotency="safe" if self.mode == "read" else "operation_defined",
            retry_behavior="safe" if self.mode == "read" else "never_without_idempotency",
            supports_prepare=self.mode == "write",
            supports_execute=True,
            supports_verify=self.mode == "write",
            supports_cancellation=self.is_async,
            supports_progress=self.is_async,
            sensitive_fields=("credentials", "api_key", "api_secret", "token", "password"),
        )


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _repair_question_mark_text(value: Any) -> str:
    text = _compact_text(value)
    repairs = (
        (r"\bsipari\?+", "siparis"),
        (r"\bka\?", "kac"),
        (r"\bbug\?n", "bugun"),
        (r"\bhaz\?r", "hazir"),
        (r"\byazd\?r", "yazdir"),
        (r"\bg\?ster", "goster"),
        (r"(?<!\S)\?r\?n", "urun"),
        (r"\bsay\?s\?", "sayisi"),
        (r"\bd\?{2,}k", "dusuk"),
        (r"(?<!\S)\?lan", "ilan"),
        (r"\bba\?l\?kl", "baslikl"),
        (r"\bba\?l\?k", "baslik"),
        (r"\bg\?rsel", "gorsel"),
        (r"\bolu\?tur", "olustur"),
        (r"\b\?ret", "uret"),
        (r"\bde\?i\?tir", "degistir"),
        (r"\bad\?nda", "adinda"),
        (r"\bi\?in", "icin"),
        (r"\bkullan\?l\?r", "kullanilir"),
        (r"\bt\?m", "tum"),
        (r"\bsa\?l\?k", "saglik"),
        (r"\bma\?aza", "magaza"),
    )
    for pattern, replacement in repairs:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _normalized_text(value: Any) -> str:
    text = _repair_question_mark_text(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    replacements = {
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ş": "s",
        "Ş": "s",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(value: Any) -> set[str]:
    normalized = _normalized_text(value)
    return {token for token in re.split(r"[^a-z0-9]+", normalized) if len(token) > 1}


def _expanded_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for canonical, aliases in {**_ACTION_ALIASES, **_ENTITY_ALIASES}.items():
        alias_tokens = {_normalized_text(alias) for alias in aliases}
        if canonical in tokens or alias_tokens.intersection(tokens):
            expanded.add(canonical)
            expanded.update(alias_tokens)
    return expanded


def _capability_search_tokens(capability: "ManualCapability") -> set[str]:
    tokens = _tokenize(capability.capability_id)
    tokens.update(_tokenize(capability.function_name))
    tokens.update(_tokenize(capability.domain))
    tokens.update(_tokenize(" ".join(capability.parameters)))
    tokens.update(_normalized_text(alias) for alias in _DOMAIN_ALIASES.get(capability.domain, ()))
    for token in list(tokens):
        tokens.update(_normalized_text(alias) for alias in _ENTITY_ALIASES.get(token, ()))
        tokens.update(_normalized_text(alias) for alias in _ACTION_ALIASES.get(token, ()))
    return _expanded_tokens(tokens)


def _function_mode(name: str) -> str:
    clean = _compact_text(name)
    if clean.startswith(_WRITE_PREFIXES):
        return "write"
    if clean.startswith(_READ_PREFIXES):
        return "read"
    if any(token in clean for token in ("save", "delete", "update", "approve", "activate", "deactivate", "sync")):
        return "write"
    return "read"


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    names: list[str] = []
    for arg in list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs):
        if arg.arg not in {"self", "cls"}:
            names.append(str(arg.arg))
    if node.args.vararg is not None:
        names.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg is not None:
        names.append(f"**{node.args.kwarg.arg}")
    return names


def _required_parameters(
    *,
    capability_id: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    if capability_id in _REQUIRED_PARAMETER_OVERRIDES:
        return list(_REQUIRED_PARAMETER_OVERRIDES[capability_id])
    required: list[str] = []
    positional = [arg for arg in list(node.args.posonlyargs) + list(node.args.args) if arg.arg not in {"self", "cls"}]
    defaults = list(node.args.defaults or [])
    default_offset = max(0, len(positional) - len(defaults))
    for index, arg in enumerate(positional):
        if index < default_offset:
            required.append(str(arg.arg))
    for arg, default in zip(list(node.args.kwonlyargs), list(node.args.kw_defaults)):
        if arg.arg in {"self", "cls"}:
            continue
        if default is None:
            required.append(str(arg.arg))
    return required


def dynamic_parameter_blockers(parameters: list[str]) -> list[str]:
    params = [str(param) for param in list(parameters or [])]
    blockers: list[str] = []
    if any(param.startswith("*") and not param.startswith("**") for param in params):
        blockers.append("dynamic args")
    if any(param.startswith("**") for param in params) and not any(not param.startswith("*") for param in params):
        blockers.append("kwargs without named schema")
    return blockers


def manual_execute_blockers(capability: ManualCapability) -> list[str]:
    reasons: list[str] = []
    if capability.mode != "write":
        reasons.append("read capability")
    if not reasons and capability.capability_id in MANUAL_EXECUTE_ADAPTERS:
        return []
    reasons.extend(dynamic_parameter_blockers(capability.parameters))
    ui_parameters = [
        str(param)
        for param in capability.parameters
        if not str(param).startswith("*")
        and (
            str(param) in _UI_PARAMETER_NAMES
            or str(param).endswith("_widget")
            or str(param).endswith("_dialog")
            or str(param).endswith("_view")
        )
    ]
    if ui_parameters:
        reasons.append(f"ui parameter: {', '.join(ui_parameters)}")
    return reasons


def manual_read_blockers(capability: ManualCapability) -> list[str]:
    reasons: list[str] = []
    if capability.mode != "read":
        reasons.append("write capability")
    if capability.capability_id in _READ_BLOCKER_OVERRIDES:
        reasons.append(_READ_BLOCKER_OVERRIDES[capability.capability_id])
    ui_parameters = [
        str(param)
        for param in capability.parameters
        if not str(param).startswith("*")
        and (
            str(param) in _UI_PARAMETER_NAMES
            or str(param).endswith("_widget")
            or str(param).endswith("_dialog")
            or str(param).endswith("_view")
        )
    ]
    if ui_parameters:
        reasons.append(f"ui parameter: {', '.join(ui_parameters)}")
    return reasons


def _module_path_for(domain: str) -> str:
    package = domain.capitalize()
    if domain == "ai":
        package = "AI"
    if domain == "marketplaces":
        package = "Marketplaces"
    if domain == "labels":
        package = "Labels"
    return f"{package}.views.actions"


def _capability_from_node(
    *,
    domain: str,
    source_path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ManualCapability:
    function_name = str(node.name)
    capability_id = f"{domain}.{function_name}"
    mode = _MODE_OVERRIDES.get(capability_id, _function_mode(function_name))
    lowered = function_name.casefold()
    destructive = any(token in lowered for token in _DESTRUCTIVE_TOKENS)
    external_write = mode == "write" and (
        any(token in lowered for token in _EXTERNAL_TOKENS) or capability_id in _EXTERNAL_WRITE_OVERRIDES
    )
    risk_level = "low"
    if mode == "write":
        risk_level = "high" if destructive or external_write else "medium"
    return ManualCapability(
        capability_id=capability_id,
        domain=domain,
        function_name=function_name,
        module_path=_module_path_for(domain),
        source_path=str(source_path.relative_to(_DESKTOP_ROOT)),
        parameters=_parameters(node),
        required_parameters=_required_parameters(capability_id=capability_id, node=node),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        mode=mode,
        risk_level=risk_level,
        requires_approval=mode == "write",
        destructive=destructive,
        external_write=external_write,
    )


def list_manual_capabilities() -> list[ManualCapability]:
    capabilities: list[ManualCapability] = []
    for domain, path in sorted(_ACTION_FILES.items()):
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = str(node.name)
            if name.startswith("_"):
                continue
            if name in {"set_progress_stage_text", "update_records", "update_progress"}:
                continue
            if name.startswith("action_") or name.startswith(
                (
                    "save_",
                    "delete_",
                    "approve_",
                    "accept_",
                    "fetch_",
                    "get_",
                    "list_",
                    "load_",
                    "set_",
                    "update_",
                    "change_",
                    "mark_",
                    "restore_",
                )
            ):
                capabilities.append(_capability_from_node(domain=domain, source_path=path, node=node))
    capabilities.sort(key=lambda cap: (cap.domain, cap.function_name))
    return capabilities


def find_manual_capability(capability_id: str) -> ManualCapability | None:
    target = _compact_text(capability_id).casefold()
    if not target:
        return None
    for capability in list_manual_capabilities():
        if capability.capability_id.casefold() == target:
            return capability
    return None


def match_manual_capabilities(
    query: str,
    *,
    domain: str = "",
    mode: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    raw_query_tokens = _tokenize(query)
    query_tokens = _expanded_tokens(raw_query_tokens)
    if not query_tokens:
        return []
    clean_domain = _normalized_text(domain)
    clean_mode = _normalized_text(mode)
    rows: list[dict[str, Any]] = []
    query_text = _normalized_text(query)
    testing_intent = bool(
        raw_query_tokens.intersection(
            {_normalized_text(alias) for alias in _DOMAIN_ALIASES["testing"]}
        )
    )
    for capability in list_manual_capabilities():
        if clean_domain and _normalized_text(capability.domain) != clean_domain:
            continue
        if capability.domain == "testing" and clean_domain != "testing" and not testing_intent:
            continue
        if clean_mode and _normalized_text(capability.mode) != clean_mode:
            continue
        capability_tokens = _capability_search_tokens(capability)
        matched = sorted(query_tokens.intersection(capability_tokens))
        if not matched:
            continue
        score = len(matched) * 10
        if capability.domain in query_tokens:
            score += 8
        if _normalized_text(capability.domain) in query_text:
            score += 8
        domain_alias_tokens = {_normalized_text(alias) for alias in _DOMAIN_ALIASES.get(capability.domain, ())}
        if domain_alias_tokens.intersection(query_tokens):
            score += 30
        for action_token in _ACTION_ALIASES:
            if action_token in query_tokens and action_token in capability_tokens:
                score += 12
        for entity_token in _ENTITY_ALIASES:
            if entity_token in query_tokens and entity_token in capability_tokens:
                score += 6
        specific_tokens = _expanded_tokens(
            _tokenize(capability.function_name)
            | _tokenize(" ".join(param for param in capability.parameters if not str(param).startswith("*")))
        )
        specific_matches = query_tokens.intersection(specific_tokens)
        score += len(specific_matches) * 8
        for important_token, bonus in (
            ("provider", 24),
            ("account", 18),
            ("root", 36),
            ("download", 18),
            ("model", 12),
            ("runtime", 18),
            ("settings", 18),
        ):
            if important_token in query_tokens and important_token in specific_tokens:
                score += bonus
        if capability.capability_id == "ai.action_set_ai_download_root" and "root" in query_tokens:
            score += 35
        if capability.capability_id == "ai.action_download_hf_model" and "root" in query_tokens:
            score -= 35
        if capability.capability_id == "orders.update_last_used_at_for_accounts" and (
            "last used" in query_text or "last_used" in query_text or "son kullanim" in query_text
        ):
            score += 90
        if "stale" in query_tokens and any(token in query_tokens for token in ("return", "returns", "iade", "claim")):
            mark_intent = any(token in query_tokens for token in ("mark", "isaretle", "pasifle", "gizle", "cleanup"))
            restore_intent = any(token in query_tokens for token in ("restore", "geri", "al", "aktif"))
            list_intent = any(token in query_tokens for token in ("list", "listele", "goster", "getir", "review", "incele"))
            if mark_intent:
                if capability.capability_id == "orders.mark_return_claims_stale":
                    score += 180
                elif capability.capability_id in {"orders.get_stale_return_claims", "orders.restore_return_claims_from_stale"}:
                    score -= 80
            if restore_intent:
                if capability.capability_id == "orders.restore_return_claims_from_stale":
                    score += 180
                elif capability.capability_id in {"orders.get_stale_return_claims", "orders.mark_return_claims_stale"}:
                    score -= 80
            if list_intent and capability.capability_id == "orders.get_stale_return_claims":
                score += 120
        if "warehouse" in query_tokens and "create" in query_tokens:
            if capability.capability_id == "stock.action_create_warehouse":
                score += 140
            elif capability.domain == "stock" and "warehouse" in capability_tokens:
                score -= 20
        listing_local_cache_intent = any(
            marker in query_text
            for marker in (
                "yerel cache",
                "local cache",
                "ilan cache",
                "listing cache",
                "yerel ilan kaydi",
                "yerel listing kaydi",
            )
        )
        if listing_local_cache_intent:
            if capability.capability_id == "listing.action_update_listing_price_inventory_cache":
                score += 420
            elif capability.domain == "listing" and capability.mode == "write":
                score -= 180
        if "cost" in query_tokens and ("item" in query_tokens or "kalem" in query_text):
            if capability.capability_id == "finance.save_finance_cost_item":
                score += 120
            if any(token in query_tokens for token in ("approve", "kabul", "onayla", "activate", "kullanima")):
                if capability.capability_id == "finance.accept_finance_cost_item":
                    score += 260
                elif capability.capability_id == "finance.save_finance_cost_item":
                    score -= 80
            if any(token in query_tokens for token in ("delete", "sil", "kaldir")):
                bulk_cost_intent = any(token in query_tokens for token in ("bulk", "toplu", "hepsi", "tum", "ikisini", "secili"))
                if bulk_cost_intent and capability.capability_id == "finance.delete_finance_cost_items":
                    score += 420
                elif capability.capability_id == "finance.delete_finance_cost_item":
                    score += 240
                elif capability.capability_id == "finance.save_finance_cost_item":
                    score -= 80
            if capability.domain == "finance" and capability.function_name in {"action_create_brand", "action_create_company"}:
                score -= 40
        if "invoice" in query_tokens or "fatura" in query_tokens:
            invoice_save_intent = any(token in query_tokens for token in ("save", "kaydet", "create", "olustur", "ekle"))
            invoice_delete_intent = any(token in query_tokens for token in ("delete", "sil", "kaldir"))
            if invoice_save_intent:
                if capability.capability_id == "finance.save_finance_invoice_document":
                    score += 340
                elif capability.domain == "finance" and capability.function_name in {"action_create_brand", "action_create_company"}:
                    score -= 160
            if invoice_delete_intent:
                if capability.capability_id == "finance.delete_finance_invoice_document":
                    score += 340
                elif capability.domain == "finance" and capability.function_name in {"action_create_brand", "action_create_company"}:
                    score -= 160
        finance_catalog_create_intent = any(token in query_tokens for token in ("create", "olustur", "ekle", "kaydet", "yeni", "add"))
        finance_catalog_update_intent = any(token in query_tokens for token in ("update", "guncelle", "degistir", "duzenle", "notunu", "kodunu"))
        finance_catalog_delete_intent = any(token in query_tokens for token in ("delete", "sil", "kaldir"))
        finance_brand_intent = "brand" in query_tokens or "marka" in query_text
        finance_company_intent = "company" in query_tokens or "sirket" in query_text or "firma" in query_text
        stock_brand_intent = finance_brand_intent and "stock" in query_tokens
        account_last_used_intent = "last used" in query_text or "last_used" in query_text or "son kullanim" in query_text
        if account_last_used_intent:
            if capability.capability_id == "orders.update_last_used_at_for_accounts":
                score += 520
            elif capability.capability_id == "marketplaces.set_marketplaces_active_state":
                score -= 520
        if finance_brand_intent:
            if stock_brand_intent and capability.domain == "finance":
                score -= 500
            elif stock_brand_intent and capability.capability_id == "stock.action_create_brand":
                score += 300
            elif capability.capability_id == "finance.action_create_brand" and finance_catalog_create_intent:
                score += 260
            elif capability.capability_id == "finance.action_update_brand" and finance_catalog_update_intent:
                score += 360
            elif capability.capability_id == "finance.action_delete_brand" and finance_catalog_delete_intent:
                score += 360
            elif capability.domain == "finance" and capability.function_name.endswith("create_brand") and not finance_catalog_create_intent:
                score -= 160
            elif capability.domain == "finance" and "cargo_tariff" in capability.capability_id:
                score -= 120
            if capability.function_name.endswith("create_item"):
                score -= 80
        if finance_company_intent:
            if account_last_used_intent and capability.domain == "finance":
                score -= 500
            elif capability.capability_id == "finance.action_create_company" and finance_catalog_create_intent:
                score += 300
            elif capability.capability_id == "finance.action_update_company" and finance_catalog_update_intent:
                score += 420
            elif capability.capability_id == "finance.action_delete_company" and finance_catalog_delete_intent:
                score += 420
            elif capability.domain == "finance" and capability.function_name in {
                "action_sync_finance_for_accounts",
                "action_sync_finance_for_selected_companies",
                "action_sync_finance_for_company_pks",
                "action_sync_all_finance_transactions",
                "action_create_company",
            } and not finance_catalog_create_intent:
                score -= 180
            elif capability.domain in {"finance", "logistics"} and "cargo_tariff" in capability.capability_id:
                score -= 120
        if "stock" in query_tokens and "brand" in query_tokens and capability.capability_id == "stock.action_create_brand":
            score += 80
        if "stock" in query_tokens and "brand" in query_tokens and capability.domain == "finance":
            score -= 50
        if "barcode" in query_tokens and "generate" in query_tokens:
            if capability.capability_id == "stock.action_generate_unique_barcode":
                score += 160
            elif "barcode" in capability_tokens:
                score -= 30
        if "marketplace" in query_tokens:
            marketplace_save_intent = any(
                token in query_tokens
                for token in (
                    "save",
                    "kaydet",
                    "update",
                    "guncelle",
                    "degistir",
                    "adini",
                    "adi",
                    "label",
                    "etiket",
                    "etiketi",
                    "etiketiyle",
                )
            )
            marketplace_delete_intent = "delete" in query_tokens or "sil" in query_tokens
            marketplace_active_intent = bool(
                any(token in query_tokens for token in ("deactivate", "pasif", "activate"))
                or any(
                    phrase in query_text
                    for phrase in (
                        "aktif et",
                        "aktife al",
                        "aktif yap",
                        "aktif duruma",
                        "durumunu aktif",
                    )
                )
            )
            if marketplace_active_intent:
                if capability.capability_id == "marketplaces.set_marketplaces_active_state":
                    score += 420
                elif capability.domain == "marketplaces":
                    score -= 200
            if ("approve" in query_tokens or "kabul" in query_tokens) and not marketplace_active_intent:
                if capability.capability_id == "marketplaces.accept_marketplace_record":
                    score += 40 if marketplace_save_intent or marketplace_delete_intent or marketplace_active_intent else 200
                elif capability.domain == "marketplaces":
                    score -= 60
            if marketplace_delete_intent:
                if capability.capability_id == "marketplaces.delete_marketplace":
                    score += 200
                elif capability.domain == "marketplaces":
                    score -= 60
            if marketplace_save_intent:
                if capability.capability_id == "marketplaces.save_marketplace":
                    score += 300
                elif capability.capability_id == "marketplaces.accept_marketplace_record":
                    score -= 180
                elif capability.domain == "finance":
                    score -= 80
        tariff_text_intent = any(fragment in query_text for fragment in ("tariff", "tarife", "tarifeler", "tarifelerini"))
        cargo_text_intent = "cargo" in query_text or "kargo" in query_text
        bulk_tariff_text_intent = any(
            fragment in query_text
            for fragment in (
                "tum",
                "hepsi",
                "toplu",
                "secili",
                "birden",
                "cok",
                "ilk",
                "bulk",
                "tarifeleri",
                "tarifelerini",
                "tariffs",
            )
        )
        if ("tariff" in query_tokens or tariff_text_intent) and "delete" in query_tokens:
            if capability.capability_id == "logistics.delete_logistics_cargo_tariff":
                score += 180
            elif capability.capability_id == "logistics.delete_logistics_cargo_provider_record":
                score -= 90
        if ("tariff" in query_tokens or "tarife" in query_tokens or tariff_text_intent) and (
            "cargo" in query_tokens or "kargo" in query_tokens or cargo_text_intent
        ):
            finance_tariff_intent = "finance" in query_tokens or "finans" in query_tokens
            bulk_tariff_intent = bulk_tariff_text_intent or any(
                token in query_tokens
                for token in (
                    "tum",
                    "hepsi",
                    "toplu",
                    "secili",
                    "birden",
                    "cok",
                    "ilk",
                    "bulk",
                    "tarifeleri",
                    "tarifelerini",
                    "tariffs",
                )
            )
            if any(token in query_tokens for token in ("save", "kaydet", "create", "olustur", "ekle", "update", "guncelle")):
                if finance_tariff_intent and capability.capability_id == "finance.save_finance_cargo_tariff":
                    score += 360
                elif capability.capability_id == "logistics.save_logistics_cargo_tariff":
                    score += 260
                elif capability.domain == "logistics" and "cargo_provider" in capability.capability_id:
                    score -= 120
            if any(token in query_tokens for token in ("approve", "kabul", "onayla", "activate", "kullanima")):
                if finance_tariff_intent and bulk_tariff_intent and capability.capability_id == "finance.accept_finance_cargo_tariffs":
                    score += 520
                elif finance_tariff_intent and capability.capability_id == "finance.accept_finance_cargo_tariff":
                    score += 360
                elif bulk_tariff_intent and capability.capability_id == "logistics.accept_logistics_cargo_tariffs":
                    score += 420
                elif bulk_tariff_intent and capability.capability_id == "logistics.accept_logistics_cargo_tariff":
                    score -= 120
                elif capability.capability_id == "logistics.accept_logistics_cargo_tariff":
                    score += 260
                elif capability.domain == "logistics" and "cargo_provider" in capability.capability_id:
                    score -= 180
            if any(token in query_tokens for token in ("delete", "sil", "kaldir")):
                if finance_tariff_intent and bulk_tariff_intent and capability.capability_id == "finance.delete_finance_cargo_tariffs":
                    score += 520
                elif finance_tariff_intent and capability.capability_id == "finance.delete_finance_cargo_tariff":
                    score += 360
                elif bulk_tariff_intent and capability.capability_id == "logistics.delete_logistics_cargo_tariffs":
                    score += 420
                elif bulk_tariff_intent and capability.capability_id == "logistics.delete_logistics_cargo_tariff":
                    score -= 120
                elif capability.capability_id == "logistics.delete_logistics_cargo_tariff":
                    score += 260
                elif capability.domain == "logistics" and "cargo_provider" in capability.capability_id:
                    score -= 180
        if "cargo" in query_tokens and (
            "provider" in query_tokens or "firmasi" in query_tokens or "firmasini" in query_tokens or "firmalari" in query_tokens
        ):
            tariff_intent = "tariff" in query_tokens or "tarife" in query_tokens or tariff_text_intent
            if not tariff_intent:
                if any(token in query_tokens for token in ("approve", "kabul", "activate", "kullanima")):
                    if capability.capability_id == "logistics.accept_logistics_cargo_provider_record":
                        score += 260
                    elif capability.domain == "logistics" and "tariff" in capability.capability_id:
                        score -= 120
                if any(token in query_tokens for token in ("save", "kaydet", "create", "olustur", "ekle", "update", "guncelle", "degistir")):
                    if capability.capability_id == "logistics.save_logistics_cargo_provider_record":
                        score += 260
                    elif capability.domain == "logistics" and "tariff" in capability.capability_id:
                        score -= 120
                if any(token in query_tokens for token in ("delete", "sil", "kaldir")):
                    if capability.capability_id == "logistics.delete_logistics_cargo_provider_record":
                        score += 260
                    elif capability.domain == "logistics" and "tariff" in capability.capability_id:
                        score -= 120
        if "stock" in query_tokens and "manual" in query_tokens and "in" in query_tokens:
            if capability.capability_id == "stock.action_manual_in":
                score += 180
            elif capability.domain == "stock" and "manual" in capability_tokens:
                score -= 40
        if "stock" in query_tokens and "manual" in query_tokens and "out" in query_tokens:
            if capability.capability_id == "stock.action_manual_out":
                score += 180
            elif capability.domain == "stock" and "manual" in capability_tokens:
                score -= 40
        if "label" in query_tokens:
            if capability.capability_id == "labels.action_create_labels_from_selected_orders":
                score += 140
            if capability.domain == "logistics":
                score -= 60
        if any(token in query_tokens for token in ("fis", "extracted")) and any(token in query_tokens for token in ("mark", "isaretle", "guncelle")):
            if capability.capability_id == "labels.mark_orders_extracted_from_label_result":
                score += 180
            elif capability.domain == "labels":
                score -= 40
        if "root" in specific_tokens and "root" not in query_tokens:
            score -= 25
        if capability.mode == "write" and any(
            token in query_tokens
            for token in ("olustur", "ekle", "yeni", "guncelle", "degistir", "sil", "onay", "sync", "cek", "kaydet", "yap")
        ):
            score += 5
        if capability.mode == "read" and any(token in query_tokens for token in ("listele", "goster", "getir", "bul", "oku", "kontrol")):
            score += 5
        if capability.destructive and not any(
            token in query_tokens
            for token in ("sil", "delete", "kaldir", "deactivate", "pasif", "devre", "iptal", "cancel")
        ):
            score -= 30
        if capability.mode == "read" and any(
            token in query_tokens
            for token in ("olustur", "ekle", "yeni", "guncelle", "degistir", "set", "kaydet", "indir", "download", "yukle", "yap")
        ):
            score -= 15
        row = capability.to_dict()
        row.update(
            {
                "score": score,
                "matched_tokens": matched,
                "missing_parameters": list(capability.required_parameters),
                "suggested_tool": "operations.manual_action.prepare"
                if capability.mode == "write"
                else "operations.manual_action.read",
            }
        )
        rows.append(row)
    rows.sort(key=lambda row: (-int(row.get("score") or 0), str(row.get("capability_id") or "")))
    return rows[: max(1, min(20, int(limit or 5)))]


def manual_capability_summary() -> dict[str, Any]:
    capabilities = list_manual_capabilities()
    by_domain: dict[str, dict[str, int]] = {}
    for capability in capabilities:
        bucket = by_domain.setdefault(capability.domain, {"total": 0, "read": 0, "write": 0})
        bucket["total"] += 1
        bucket[capability.mode] = bucket.get(capability.mode, 0) + 1
    return {
        "total": len(capabilities),
        "write_total": sum(1 for capability in capabilities if capability.mode == "write"),
        "read_total": sum(1 for capability in capabilities if capability.mode == "read"),
        "by_domain": by_domain,
    }
