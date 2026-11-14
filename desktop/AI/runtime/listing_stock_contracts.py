"""Native single-purpose listing/stock adapters over the shared manual write."""
from __future__ import annotations

from AI.runtime.contracts import AgentTool
from Feedback.processors.pipeline import Result
from Listing.processors.stock_bindings import preview_listing_stock_link, read_listing_stock_links
from settings import DB_NAME


def listing_stock_links(*, listing_id: int, api_account_id: int, product_id: str,
                        db_name: str = DB_NAME) -> Result:
    result = read_listing_stock_links(listing_id=listing_id, api_account_id=api_account_id,
                                     product_id=product_id, db_name=db_name)
    if result.success:
        result.data = {**result.data, "tool": "listing.stock_links"}
    return result


def listing_stock_link_prepare(*, listing_id: int, api_account_id: int, product_id: str,
                               stock_item_id: int, qty: float = 1, db_name: str = DB_NAME) -> Result:
    from AI.processors.operation_policy import AgentOperationPolicy, build_approval_action, prepare_result
    from AI.processors.manual_capabilities import find_manual_capability, manual_execute_blockers
    from AI.processors.session_state import PendingActionSnapshot
    from Core.processors.record_refs import RecordRef

    preview = preview_listing_stock_link(listing_id=listing_id, api_account_id=api_account_id,
        product_id=product_id, stock_item_id=stock_item_id, qty=qty, db_name=db_name)
    if not preview.success:
        return preview
    capability_id = "listing.action_set_listing_stock_items"
    capability = find_manual_capability(capability_id)
    if capability is None or manual_execute_blockers(capability):
        return Result.fail("İlan stok eşleştirme işlemi yürütülemiyor.", close_dialog=False,
                           data={"reason": "manual_write_not_available", "db_write_performed": False})
    data = preview.data
    listing, stock = data["listing"], data["stock_item"]
    # Keep the established manual-action dispatcher and its exact approval and
    # database readback boundary. No execution capability is exposed here.
    policy = AgentOperationPolicy(domain="listing", tool="operations.manual_action.prepare",
        action_type=capability_id, risk_level=capability.risk_level)
    summary = (f"{listing['title'] or listing['product_id']} (ilan #{listing_id}, hesap #{api_account_id}) → "
               f"{stock['name']} ({stock['sku']}, stok #{stock_item_id}), miktar {float(qty):g}.")
    action = build_approval_action(policy=policy, title="İlan stok eşleştirmesi", summary=summary,
        arguments={"capability_id": capability_id, "payload": data["payload"]},
        rows=[{"listing": listing, "stock_item": stock, "qty": data["qty"],
               "current_stock_items": data["current_stock_items"],
               "desired_stock_items": data["desired_stock_items"]}], execute_enabled=True)
    # The listing is the mutation target; its account and selected stock card
    # are separate identities. Compound preview rows cannot infer this safely.
    action.update(record_refs=[RecordRef(domain="listing", record_type="listing",
        record_id=str(listing_id), source="prepared_action", account=str(api_account_id),
        environment="local", identifiers={"listing_id": str(listing_id),
            "api_account_id": str(api_account_id), "product_id": product_id}).to_dict()],
        selected_record_count=1, preview_item_count=1, execute_input_count=1)
    action = PendingActionSnapshot.refresh_identity(action)
    return prepare_result(policy=policy, message="İlan stok eşleştirmesi onaya hazır.", action=action,
        data={"tool": "listing.stock_link.prepare", "listing": listing, "stock_item": stock,
              "qty": data["qty"], "current_stock_items": data["current_stock_items"],
              "desired_stock_items": data["desired_stock_items"], "changed": data["changed"], "valid": True,
              "quantity_basis": data["quantity_basis"], "scope": data["scope"]})


def listing_stock_tools() -> dict[str, AgentTool]:
    def obj(fields):
        return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}

    text, integer, boolean = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
    nullable_text = {"type": ["string", "null"]}
    listing = obj({"listing_id": integer, "api_account_id": integer, "product_id": text,
                   "title": nullable_text, "barcode": nullable_text, "stock_code": nullable_text,
                   "archived": {"type": ["boolean", "null"]}})
    stock = obj({"stock_item_id": integer, "sku": text, "name": text, "barcode": nullable_text,
                 "unit": text, "is_active": boolean})
    links = {"type": "array", "items": obj({"stock_item_id": integer, "qty": {"type": "number"}})}
    basis = {"quantity_basis": {"type": "string", "const": "stock_units_per_listing_unit"},
             "scope": {"type": "string", "const": "local"}}
    identity = {"listing_id": {"type": "integer", "minimum": 1,
                              "description": "Exact local listing PK from listing.search; never a stock card ID."},
                "api_account_id": {"type": "integer", "minimum": 1,
                                   "description": "The listing's actual owning account PK."},
                "product_id": {"type": "string", "minLength": 1,
                               "description": "The listing's exact marketplace product_id, as read."}}
    return {
        "listing.stock_links": AgentTool(name="listing.stock_links", domain="listing",
            handler=listing_stock_links, canonical_callable="Listing.processors.stock_bindings.read_listing_stock_links",
            description="Read the exact local stock-card links for one listing. Requires matching local listing_id, "
                "api_account_id and marketplace product_id. Returns link quantities, not warehouse balances. "
                "Use listing.search for listing identities and stock.search/stock.items_list for stock card identities.",
            parameters={"type": "object", "properties": identity, "required": list(identity),
                        "additionalProperties": False},
            result_schema=obj({"tool": {"type": "string", "const": "listing.stock_links"},
                "listing": listing, "stock_items": links, "binding_state": text, "complete": boolean, **basis})),
        "listing.stock_link.prepare": AgentTool(name="listing.stock_link.prepare", domain="listing",
            handler=listing_stock_link_prepare, requires_approval=True, action_type="prepare_write",
            risk_level="medium", canonical_callable="Listing.views.actions.action_set_listing_stock_items",
            description="Prepare adding or updating ONE explicit stock card link for ONE existing listing. "
                "The model selects actual existing records from listing.search and stock.search/stock.items_list; "
                "do not use listing.stock_lookup quantities as stock card IDs. Supply exact listing_id, owner "
                "api_account_id, marketplace product_id and stock_item_id. qty defaults to 1 and is units of this "
                "stock card per listing unit. Other links are preserved. Checks local identities and active stock card, "
                "captures current binding/card state, and requires standard approval before the shared manual write "
                "and database readback. Does not select randomly, alter stock balances or call a marketplace.",
            parameters={"type": "object", "properties": {**identity,
                "stock_item_id": {"type": "integer", "minimum": 1,
                                  "description": "Actual stock card PK, distinct from listing/product IDs."},
                "qty": {"type": "number", "exclusiveMinimum": 0, "default": 1}},
                "required": [*identity, "stock_item_id"], "additionalProperties": False},
            result_schema=obj({"tool": {"type": "string", "const": "listing.stock_link.prepare"},
                "listing": listing, "stock_item": stock, "qty": {"type": "number"},
                "current_stock_items": links, "desired_stock_items": links, "changed": boolean, "valid": boolean,
                "approval_required": boolean, "api_call_performed": boolean, "db_write_performed": boolean,
                "action": {"type": "object"}, "operation_result": {"type": "object"}, **basis}))}
