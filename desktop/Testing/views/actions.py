from __future__ import annotations

from Feedback.processors.pipeline import Result


_PIPELINE_MODULE = None


def _pipeline_action(name: str):
    global _PIPELINE_MODULE
    if _PIPELINE_MODULE is None:
        from Testing.processors import pipeline

        _PIPELINE_MODULE = pipeline
    return getattr(_PIPELINE_MODULE, name)


def _stage_action(name: str):
    from Testing.processors import trendyol_stage

    return getattr(trendyol_stage, name)


def clear_testing_action_cache() -> None:
    global _PIPELINE_MODULE
    _PIPELINE_MODULE = None


def action_load_test_companies() -> Result:
    return _pipeline_action("list_companies_for_testing")()


def action_load_company_listings(
    *,
    api_account_id: int,
    search: str | None = None,
    limit: int = 300,
) -> Result:
    return _pipeline_action("list_company_listings_for_testing")(
        api_account_id=int(api_account_id),
        search=(search or "").strip() or None,
        limit=int(limit),
    )


def action_simulate_orders(
    *,
    api_account_id: int,
    order_count: int,
    lines_per_order: int,
    order_status: str = "Picking",
    shipment_status: str = "ReadyToShip",
    status_preset: str | None = None,
    lifecycle_key: str | None = None,
) -> Result:
    return _pipeline_action("simulate_order_arrival")(
        api_account_id=int(api_account_id),
        order_count=int(order_count),
        lines_per_order=int(lines_per_order),
        order_status=str(order_status or "Picking"),
        shipment_status=str(shipment_status or "ReadyToShip"),
        status_preset=str(status_preset or "").strip() or None,
        lifecycle_key=str(lifecycle_key or "").strip() or None,
    )


def action_simulate_orders_from_listings(
    *,
    api_account_id: int,
    listing_items: list[dict],
    order_count: int,
    order_status: str = "Picking",
    shipment_status: str = "ReadyToShip",
    status_preset: str | None = None,
    lifecycle_key: str | None = None,
) -> Result:
    return _pipeline_action("simulate_order_arrival_from_listings")(
        api_account_id=int(api_account_id),
        listing_items=listing_items or [],
        order_count=int(order_count),
        order_status=str(order_status or "Picking"),
        shipment_status=str(shipment_status or "ReadyToShip"),
        status_preset=str(status_preset or "").strip() or None,
        lifecycle_key=str(lifecycle_key or "").strip() or None,
    )


def action_verify_listing_order_flow(
    *,
    api_account_id: int,
    listing_items: list[dict] | None = None,
    order_count: int = 1,
    lifecycle_key: str | None = "created",
) -> Result:
    return _pipeline_action("verify_listing_order_simulation")(
        api_account_id=int(api_account_id),
        listing_items=listing_items or [],
        order_count=int(order_count),
        lifecycle_key=str(lifecycle_key or "").strip() or "created",
    )


def action_simulate_listings(
    *,
    api_account_id: int,
    item_count: int,
) -> Result:
    return _pipeline_action("simulate_listing_arrival")(
        api_account_id=int(api_account_id),
        item_count=int(item_count),
    )


def action_run_domain_healthcheck(*, api_account_id: int | None = None) -> Result:
    account_id = int(api_account_id) if api_account_id is not None else None
    return _pipeline_action("run_domain_healthcheck")(api_account_id=account_id)


def action_run_local_unittest_suite(
    *,
    pattern: str = "test_*.py",
    timeout_sec: int = 240,
) -> Result:
    return _pipeline_action("run_local_unittest_suite")(
        pattern=(pattern or "test_*.py").strip() or "test_*.py",
        timeout_sec=int(timeout_sec),
    )


def action_build_exe_and_setup_release(
    *,
    version: str,
    output_root: str,
    progress_callback=None,
    log_callback=None,
) -> Result:
    return _pipeline_action("build_exe_and_setup_release")(
        version=str(version or "").strip(),
        output_root=str(output_root or "").strip(),
        progress_callback=progress_callback,
        log_callback=log_callback,
    )


def action_publish_desktop_release(
    *,
    version: str,
    output_root: str = "",
    release_repo_path: str = "",
    release_repo_slug: str = "hermanjons/OrderScout-releases",
    progress_callback=None,
    log_callback=None,
) -> Result:
    return _pipeline_action("publish_desktop_release")(
        version=str(version or "").strip(),
        output_root=str(output_root or "").strip(),
        release_repo_path=str(release_repo_path or "").strip(),
        release_repo_slug=str(release_repo_slug or "").strip(),
        progress_callback=progress_callback,
        log_callback=log_callback,
    )


def action_run_cargo_tariff_sandbox(
    *,
    platform_code: str,
    sale_price: float,
    dimensional_weight: float,
    cargo_provider_code: str = "",
    cargo_provider_name: str = "",
    cargo_provider_id: int | None = None,
) -> Result:
    return _pipeline_action("run_cargo_tariff_sandbox")(
        platform_code=str(platform_code or "").strip(),
        sale_price=float(sale_price),
        dimensional_weight=float(dimensional_weight),
        cargo_provider_code=str(cargo_provider_code or "").strip(),
        cargo_provider_name=str(cargo_provider_name or "").strip(),
        cargo_provider_id=int(cargo_provider_id) if cargo_provider_id is not None else None,
    )


def action_simulate_stock_depletion(*, item_limit: int = 500) -> Result:
    return _pipeline_action("simulate_stock_depletion")(item_limit=int(item_limit))


def action_run_label_stress_test(*, api_account_id: int, order_count: int = 1000) -> Result:
    return _pipeline_action("run_label_stress_test")(api_account_id=int(api_account_id), order_count=int(order_count))


def action_configure_test_chaos(*, enabled: bool, mode: str = "timeout", rate: float = 0.30, seed: int | None = None) -> Result:
    return _pipeline_action("configure_test_chaos_mode")(
        enabled=bool(enabled),
        mode=str(mode or "timeout").strip(),
        rate=float(rate),
        seed=int(seed) if seed is not None else None,
    )


def action_load_stage_lab_context(*, api_account_id: int) -> Result:
    return _stage_action("stage_lab_context")(api_account_id=int(api_account_id))


def action_create_stage_test_order(
    *,
    api_account_id: int,
    barcode: str,
    quantity: int = 1,
) -> Result:
    return _stage_action("create_stage_test_order")(
        api_account_id=int(api_account_id),
        barcode=str(barcode or "").strip(),
        quantity=int(quantity),
    )


def action_advance_stage_order_status(
    *,
    api_account_id: int,
    order_number: str,
    target_status: str,
) -> Result:
    return _stage_action("advance_stage_order_status")(
        api_account_id=int(api_account_id),
        order_number=str(order_number or "").strip(),
        target_status=str(target_status or "").strip(),
    )


def action_create_stage_return_claim(
    *,
    api_account_id: int,
    order_number: str,
    quantity: int = 1,
) -> Result:
    return _stage_action("create_stage_return_claim")(
        api_account_id=int(api_account_id),
        order_number=str(order_number or "").strip(),
        quantity=int(quantity),
    )


def action_advance_stage_claim_to_waiting_action(
    *,
    api_account_id: int,
    claim_id: str,
) -> Result:
    return _stage_action("advance_stage_claim_to_waiting_action")(
        api_account_id=int(api_account_id),
        claim_id=str(claim_id or "").strip(),
    )


def action_approve_stage_return(
    *,
    api_account_id: int,
    claim_id: str,
) -> Result:
    synced = _stage_action("sync_stage_claim")(
        api_account_id=int(api_account_id),
        claim_id=str(claim_id or "").strip(),
        attempts=3,
        expected_statuses=["WaitingInAction"],
    )
    if not synced.success:
        return synced
    claim = (synced.data or {}).get("claim")
    from Orders.views.actions import approve_return_claim

    approved = approve_return_claim(claim)
    if not approved.success:
        return approved
    verified = _stage_action("sync_stage_claim")(
        api_account_id=int(api_account_id),
        claim_id=str(claim_id or "").strip(),
        attempts=12,
        expected_statuses=["Accepted", "WaitingFraudCheck"],
    )
    if not verified.success:
        return Result.fail(
            "İade onay isteği gönderildi ancak son durum doğrulanamadı.",
            error=verified.error,
            close_dialog=False,
            data={"approval": approved.data or {}, "verify": verified.data or {}},
        )
    return Result.ok(
        "İade uygulamanın gerçek onay aksiyonuyla onaylandı ve Stage'den doğrulandı.",
        close_dialog=False,
        data={"approval": approved.data or {}, **(verified.data or {})},
    )


def action_run_stage_return_lifecycle(
    *,
    api_account_id: int,
    barcode: str,
    quantity: int = 1,
) -> Result:
    prepared = _stage_action("prepare_stage_return_lifecycle")(
        api_account_id=int(api_account_id),
        barcode=str(barcode or "").strip(),
        quantity=int(quantity),
    )
    if not prepared.success:
        return prepared
    data = dict(prepared.data or {})
    steps = list(data.get("steps") or [])
    claim_id = str(data.get("claim_id") or "").strip()

    approved = action_approve_stage_return(
        api_account_id=int(api_account_id),
        claim_id=claim_id,
    )
    steps.append(
        {
            "step": "orders.return.approve",
            "success": approved.success,
            "detail": approved.message,
        }
    )
    if not approved.success:
        return Result.fail(
            approved.message,
            error=approved.error,
            close_dialog=False,
            data={**data, "steps": steps, "approval": approved.data or {}},
        )

    return Result.ok(
        "Stage sipariş → teslimat → iade → onay yaşam döngüsü tamamlandı.",
        close_dialog=False,
        data={
            **data,
            "steps": steps,
            "approval": approved.data or {},
            "status": (approved.data or {}).get("status"),
        },
    )
