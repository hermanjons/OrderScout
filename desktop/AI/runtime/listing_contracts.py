"""Model-facing contracts for the shared local listing catalog operations."""
from __future__ import annotations

from AI.runtime.contracts import AgentTool


def _object(fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def listing_read_tool(name, handler):
    text = {"type": "string"}
    integer = {"type": "integer"}
    boolean = {"type": "boolean"}
    fields = {
        **{key: text for key in ("title", "barcode", "stock_code", "product_id", "product_code", "brand",
                                "category_name", "currency", "product_url")},
        **{key: {"type": ["integer", "null"]} for key in ("listing_id", "api_account_id", "stock_item_id")},
        **{key: {"type": ["number", "null"]} for key in ("quantity", "sale_price", "list_price")},
        "approved": {"type": ["boolean", "null"]},
        **{key: boolean for key in ("archived", "on_sale", "locked", "has_active_campaign")},
    }
    sample_keys = ("listing_id", "api_account_id", "product_id", "title", "barcode", "stock_code",
                   "quantity", "sale_price", "currency", "on_sale", "approved")
    account_parameter = {"type": "array", "items": {"type": "integer", "minimum": 1}, "minItems": 1,
                         "description": "Omit to read all permitted accounts; IDs identify catalog owners."}
    parameters = {"api_account_ids": account_parameter}
    paged = {"count": integer, "offset": integer, "has_more": boolean}
    owner = "Listing.processors.catalog_queries."
    descriptions = {
        "listing.summary": "Kayıtlı ilanların durum ve stok sayılarını özetler. active_listings arşivlenmemiş ilanlardır; "
                           "satıştaki ilan sayısı on_sale alanıdır. needs_attention yalnız açık onaysız/kilitli kayıt sayısıdır; "
                           "geniş sorun listesi için listing.attention kullan. limit yalnız örnekleri sınırlar.",
        "listing.attention": "Kayıtlı arşivlenmemiş ilanlarda stok, onay, kilit veya satış durumu sorunu olanları "
                             "nedenleriyle sayfalar. attention_count ve reason_counts tüm kapsamı, count bu sayfayı belirtir.",
        "listing.counts": "Kayıtlı ilanların toplam, arşivlenmemiş, satış ve onay/stok durum sayılarını getirir.",
        "listing.attention_count": "Kayıtlı arşivlenmemiş ilanlarda stok/onay/kilit/satış sorunu olanların sayısını ve neden sayılarını getirir.",
    }
    lookups = {
        "listing.search": ("results", None, "İlanları ad, barkod, stok veya ürün koduyla arar; temel kayıt detaylarını getirir."),
        "listing.detail_lookup": ("details", None, "Eşleşen ilanların kayıtlı detaylarını getirir."),
        "listing.title_lookup": ("titles", ("title", "barcode", "stock_code"), "Eşleşen ilanların kayıtlı başlıklarını getirir."),
        "listing.stock_lookup": ("stocks", ("title", "barcode", "stock_code", "quantity", "on_sale", "approved"),
                                 "Eşleşen ilanların kayıtlı ilan miktarını getirir; fiziksel depo bakiyesi değildir."),
        "listing.status_lookup": ("statuses", ("title", "barcode", "stock_code", "approved", "archived", "on_sale", "locked", "has_active_campaign"),
                                  "Eşleşen ilanların kayıtlı onay, satış, arşiv, kilit ve kampanya bayraklarını getirir."),
        "listing.url_lookup": ("urls", ("title", "barcode", "stock_code", "product_url"), "Eşleşen ilanların kayıtlı ürün bağlantısını getirir."),
        "listing.price_lookup": ("prices", ("title", "barcode", "stock_code", "sale_price", "list_price", "quantity", "approved", "on_sale"),
                                 "Eşleşen ilanların kayıtlı satış/liste fiyatlarını ve para birimini getirir."),
    }
    if name in lookups:
        collection, keys, description = lookups[name]
        keys = fields if keys is None else ("listing_id", "api_account_id", "product_id", "currency", *keys)
        result_fields = {"query": text, "total": integer, **paged,
                         collection: {"type": "array", "items": _object({key: fields[key] for key in keys})}}
        parameters.update(query=text, limit={"type": "integer", "minimum": 1, "maximum": 50},
                          offset={"type": "integer", "minimum": 0})
        description += " Arşivlenmiş ilanlar dışarıdadır; tam kimlik eşleşmesi önceliklidir. "
        canonical = owner + "read_listing_search"
    else:
        description = descriptions[name]
        if name == "listing.summary":
            result_fields = {**{key: integer for key in (
                "total_listings", "active_listings", "archived", "on_sale", "not_on_sale", "approved",
                "unapproved", "locked", "needs_attention", "out_of_stock",
            )}, "sample_listings": {"type": "array", "items": _object({key: fields[key] for key in sample_keys})}}
            parameters["limit"] = {"type": "integer", "minimum": 1, "maximum": 30}
            canonical = owner + "read_listing_summary"
        elif name == "listing.counts":
            result_fields = {key: integer for key in ("total", "active", "archived", "on_sale", "not_on_sale",
                                                      "approved", "unapproved", "locked", "out_of_stock")}
            canonical = owner + "read_listing_summary"
        else:
            reasons = {"type": "object", "additionalProperties": integer}
            result_fields = {"count": integer, "reason_counts": reasons}
            canonical = owner + "read_listing_attention"
            if name == "listing.attention":
                row = {key: fields[key] for key in (*sample_keys, "locked", "archived")}
                row["reasons"] = {"type": "array", "items": {"type": "string",
                    "enum": ["out_of_stock", "not_approved", "locked", "not_on_sale"]}}
                result_fields = {"total_listings": integer, "active_listings": integer, "attention_count": integer,
                                 "reason_counts": reasons, **paged, "listings": {"type": "array", "items": _object(row)}}
                parameters.update(limit={"type": "integer", "minimum": 1, "maximum": 50}, offset={"type": "integer", "minimum": 0})
    description += (" Yerel katalog okumasıdır; pazaryerine istek veya yazma yapmaz. "
                    "Miktarlar kesirli olabilir; eksik fiyat/miktar null, açık sıfır fiyat 0 kalır. "
                    "sale_price eksikse mevcut list_price kullanılır; ikisi eksikse null. "
                    "approved=null onayın bilinmediğini belirtir; currency manuel editörle aynı kayıt kuralını kullanır "
                    "(kayıtta yoksa TRY). Sayfalı sonuçlarda total/count ayrımını koru; has_more=true ise offset ile devam et.")
    result_fields["tool"] = {"const": name, "type": "string"}
    return AgentTool(name=name, handler=handler, domain="listing", description=description,
                     parameters={"type": "object", "properties": parameters, "additionalProperties": False},
                     canonical_callable=canonical, result_schema=_object(result_fields))
