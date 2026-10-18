from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from Feedback.processors.pipeline import Result
import Testing.processors.trendyol_stage as stage_pipeline
import Testing.views.actions as testing_actions


class TestTrendyolStagePipeline(TestCase):
    @staticmethod
    def _account(*, environment: str) -> SimpleNamespace:
        return SimpleNamespace(
            pk=7,
            comp_name="Stage QA",
            platform="TRENDYOL",
            account_id="2738",
            api_key="key",
            api_secret="secret",
            extra_config={"environment": environment},
        )

    @staticmethod
    def _scope() -> stage_pipeline._StageScope:
        api = SimpleNamespace(
            header={"Content-Type": "application/json"},
            auth=("key", "secret"),
            _send_request=AsyncMock(),
        )
        return stage_pipeline._StageScope(
            api_account_id=7,
            account=TestTrendyolStagePipeline._account(environment="stage"),
            api=api,
            seller_id="2738",
        )

    def test_stage_guard_blocks_production_before_client_creation(self) -> None:
        account_result = Result.ok(
            "ok",
            close_dialog=False,
            data={"records": [self._account(environment="production")]},
        )
        with patch.object(stage_pipeline, "get_company_by_id", return_value=account_result), patch.object(
            stage_pipeline.TrendyolApi,
            "__init__",
            side_effect=AssertionError("production must be blocked before client creation"),
        ):
            result = stage_pipeline._load_stage_scope(7, db_name="unused.sqlite3")

        self.assertFalse(result.success)
        self.assertTrue(bool((result.data or {}).get("production_blocked")))

    def test_stage_guard_accepts_trendyol_stage_account(self) -> None:
        account_result = Result.ok(
            "ok",
            close_dialog=False,
            data={"records": [self._account(environment="stage")]},
        )
        with patch.object(stage_pipeline, "get_company_by_id", return_value=account_result):
            result = stage_pipeline._load_stage_scope(7, db_name="unused.sqlite3")

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("environment"), "stage")

    def test_create_test_order_uses_stage_endpoint_and_seller_header(self) -> None:
        scope = self._scope()
        scope.api._send_request.return_value = Result.ok(
            "ok",
            close_dialog=False,
            data={"json": {"orderNumber": "QA-123"}, "status_code": 200},
        )
        synced = Result.ok(
            "synced",
            close_dialog=False,
            data={"order_number": "QA-123", "status": "ReadyToShip"},
        )
        with patch.object(
            stage_pipeline,
            "_scope_or_result",
            return_value=(scope, Result.ok("ok", close_dialog=False)),
        ), patch.object(stage_pipeline, "sync_stage_order", return_value=synced):
            result = stage_pipeline.create_stage_test_order(
                api_account_id=7,
                barcode="9900000000486",
                quantity=2,
            )

        self.assertTrue(result.success, result.message)
        kwargs = scope.api._send_request.await_args.kwargs
        self.assertEqual(kwargs.get("method"), "POST")
        self.assertTrue(str(kwargs.get("url") or "").endswith("/integration/test/order/orders/core"))
        self.assertEqual((kwargs.get("headers") or {}).get("SellerID"), "2738")
        self.assertEqual(((kwargs.get("json") or {}).get("lines") or [])[0]["quantity"], 2)

    def test_context_places_official_test_product_first(self) -> None:
        scope = self._scope()
        with patch.object(
            stage_pipeline,
            "_scope_or_result",
            return_value=(scope, Result.ok("ok", close_dialog=False)),
        ), patch.object(
            stage_pipeline,
            "get_latest_orders",
            return_value=Result.ok("ok", close_dialog=False, data={"orders": []}),
        ), patch.object(
            stage_pipeline,
            "get_latest_return_claims",
            return_value=Result.ok("ok", close_dialog=False, data={"claims": []}),
        ), patch.object(
            stage_pipeline,
            "_listing_context",
            return_value=[{"barcode": "merchant-item", "title": "Merchant item"}],
        ):
            result = stage_pipeline.stage_lab_context(api_account_id=7)

        self.assertTrue(result.success, result.message)
        listings = (result.data or {}).get("listings") or []
        self.assertEqual(listings[0]["barcode"], "9900000000486")
        self.assertTrue(listings[0]["official_test_product"])

    def test_waiting_in_action_uses_stage_only_test_endpoint(self) -> None:
        scope = self._scope()
        scope.api._send_request.return_value = Result.ok(
            "ok",
            close_dialog=False,
            data={"json": None, "status_code": 200},
        )
        before = Result.ok(
            "created",
            close_dialog=False,
            data={"claim_id": "claim-1", "shipment_package_id": 56526451, "status": "Created"},
        )
        after = Result.ok(
            "waiting",
            close_dialog=False,
            data={"claim_id": "claim-1", "shipment_package_id": 56526451, "status": "WaitingInAction"},
        )
        with patch.object(
            stage_pipeline,
            "_scope_or_result",
            return_value=(scope, Result.ok("ok", close_dialog=False)),
        ), patch.object(stage_pipeline, "sync_stage_claim", side_effect=[before, after]):
            result = stage_pipeline.advance_stage_claim_to_waiting_action(
                api_account_id=7,
                claim_id="claim-1",
            )

        self.assertTrue(result.success, result.message)
        kwargs = scope.api._send_request.await_args.kwargs
        self.assertTrue(
            str(kwargs.get("url") or "").endswith(
                "/integration/test/order/sellers/2738/claims/waiting-in-action"
            )
        )
        self.assertEqual(kwargs.get("json"), {"shipmentPackageId": 56526451})


class TestTrendyolStageActions(TestCase):
    def test_full_lifecycle_uses_real_approval_action_boundary(self) -> None:
        prepared = Result.ok(
            "prepared",
            close_dialog=False,
            data={
                "steps": [{"step": "stage.claim.waiting_in_action", "success": True}],
                "order_number": "QA-123",
                "claim_id": "claim-1",
            },
        )
        approved = Result.ok(
            "approved",
            close_dialog=False,
            data={"claim_id": "claim-1", "status": "Accepted"},
        )
        with patch.object(testing_actions, "_stage_action") as stage_action, patch.object(
            testing_actions,
            "action_approve_stage_return",
            return_value=approved,
        ) as approve_action:
            stage_action.return_value.return_value = prepared
            result = testing_actions.action_run_stage_return_lifecycle(
                api_account_id=7,
                barcode="9900000000486",
                quantity=1,
            )

        self.assertTrue(result.success, result.message)
        approve_action.assert_called_once_with(api_account_id=7, claim_id="claim-1")
        self.assertEqual((result.data or {}).get("status"), "Accepted")
