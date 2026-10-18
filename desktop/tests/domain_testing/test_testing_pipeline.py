from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, select

import Account.processors.pipeline as account_pipeline
import Listing.processors.pipeline as listing_pipeline
import Marketplaces.views.actions as marketplaces_actions
import Orders.processors.trendyol.pipeline as orders_pipeline
import Testing.processors.pipeline as testing_pipeline
from Core.utils.model_utils import get_engine
from Orders.models.trendyol.models import OrderData, OrderItem
from Orders.signals.signals import order_signals

from tests.support.db_case import IsolatedDbTestCase


class TestTestingPipeline(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._account_db_patch = patch.object(account_pipeline, "DB_NAME", self.db_path)
        self._account_db_patch.start()

    def tearDown(self) -> None:
        self._account_db_patch.stop()
        super().tearDown()

    def _create_company(self) -> int:
        accepted = marketplaces_actions.accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

        res = account_pipeline.save_company_to_db(
            {
                "account_id": "T-100",
                "comp_name": "Test Co",
                "platform": "trendyol",
            }
        )
        self.assertTrue(res.success, res.message)

        all_companies = testing_pipeline.list_companies_for_testing()
        self.assertTrue(all_companies.success, all_companies.message)

        companies = (all_companies.data or {}).get("companies", [])
        self.assertEqual(len(companies), 1)
        return int(companies[0]["pk"])

    def test_simulate_order_arrival_persists_orders(self) -> None:
        company_pk = self._create_company()

        sim = testing_pipeline.simulate_order_arrival(
            api_account_id=company_pk,
            order_count=2,
            lines_per_order=2,
            db_name=self.db_path,
        )
        self.assertTrue(sim.success, sim.message)
        self.assertEqual(len((sim.data or {}).get("order_numbers", [])), 2)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            latest = orders_pipeline.get_latest_orders(shipment_statuses=["ReadyToShip"])

        self.assertTrue(latest.success, latest.message)
        self.assertEqual(len((latest.data or {}).get("orders", [])), 2)

    def test_simulate_order_arrival_supports_status_presets(self) -> None:
        company_pk = self._create_company()

        sim = testing_pipeline.simulate_order_arrival(
            api_account_id=company_pk,
            order_count=1,
            lines_per_order=1,
            status_preset="delivered",
            db_name=self.db_path,
        )
        self.assertTrue(sim.success, sim.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            latest = orders_pipeline.get_latest_orders(shipment_statuses=["Delivered"])

        self.assertTrue(latest.success, latest.message)
        self.assertEqual(len((latest.data or {}).get("orders", [])), 1)

    def test_simulate_order_arrival_can_build_lifecycle_snapshots(self) -> None:
        company_pk = self._create_company()

        sim = testing_pipeline.simulate_order_arrival(
            api_account_id=company_pk,
            order_count=1,
            lines_per_order=1,
            lifecycle_key="created_to_shipped",
            db_name=self.db_path,
        )
        self.assertTrue(sim.success, sim.message)
        self.assertEqual(int((sim.data or {}).get("snapshot_count") or 0), 2)

        order_number = ((sim.data or {}).get("order_numbers") or [None])[0]
        self.assertIsNotNone(order_number)
        with Session(get_engine(self.db_path)) as session:
            snapshots = session.exec(
                select(OrderData)
                .where(OrderData.orderNumber == str(order_number))
                .order_by(OrderData.lastModifiedDate.asc())
            ).all()
        self.assertEqual([snapshot.shipmentPackageStatus for snapshot in snapshots], ["ReadyToShip", "Shipped"])

    def test_simulate_listing_arrival_persists_listings(self) -> None:
        company_pk = self._create_company()

        sim = testing_pipeline.simulate_listing_arrival(
            api_account_id=company_pk,
            item_count=4,
            db_name=self.db_path,
        )
        self.assertTrue(sim.success, sim.message)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[company_pk], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        self.assertEqual(len((read.data or {}).get("items", [])), 4)

    def test_list_company_listings_for_testing(self) -> None:
        company_pk = self._create_company()
        sim = testing_pipeline.simulate_listing_arrival(
            api_account_id=company_pk,
            item_count=3,
            db_name=self.db_path,
        )
        self.assertTrue(sim.success, sim.message)

        res = testing_pipeline.list_company_listings_for_testing(
            api_account_id=company_pk,
            db_name=self.db_path,
            limit=2,
        )
        self.assertTrue(res.success, res.message)
        self.assertEqual((res.data or {}).get("shown"), 2)
        self.assertEqual((res.data or {}).get("total"), 3)

    def test_simulate_order_arrival_from_listings(self) -> None:
        company_pk = self._create_company()
        listing_sim = testing_pipeline.simulate_listing_arrival(
            api_account_id=company_pk,
            item_count=3,
            db_name=self.db_path,
        )
        self.assertTrue(listing_sim.success, listing_sim.message)

        listing_res = testing_pipeline.list_company_listings_for_testing(
            api_account_id=company_pk,
            db_name=self.db_path,
        )
        self.assertTrue(listing_res.success, listing_res.message)
        listing_items = (listing_res.data or {}).get("items", [])
        self.assertGreaterEqual(len(listing_items), 2)

        order_res = testing_pipeline.simulate_order_arrival_from_listings(
            api_account_id=company_pk,
            listing_items=listing_items[:2],
            order_count=2,
            db_name=self.db_path,
        )
        self.assertTrue(order_res.success, order_res.message)
        self.assertEqual(len((order_res.data or {}).get("order_numbers", [])), 2)
        self.assertEqual((order_res.data or {}).get("source_count"), 2)

        order_numbers = (order_res.data or {}).get("order_numbers", []) or []
        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            items_res = orders_pipeline.get_latest_order_items_by_numbers(order_numbers, api_account_ids=[company_pk])
        self.assertTrue(items_res.success, items_res.message)
        item_rows = (items_res.data or {}).get("items", []) or []
        self.assertGreaterEqual(len(item_rows), 2)
        self.assertTrue(all(getattr(row, "order_data_pk", None) is not None for row in item_rows))

    def test_simulate_order_arrival_from_listings_emits_created_equivalent_items(self) -> None:
        company_pk = self._create_company()
        listing_sim = testing_pipeline.simulate_listing_arrival(
            api_account_id=company_pk,
            item_count=1,
            db_name=self.db_path,
        )
        self.assertTrue(listing_sim.success, listing_sim.message)

        listing_res = testing_pipeline.list_company_listings_for_testing(
            api_account_id=company_pk,
            db_name=self.db_path,
        )
        self.assertTrue(listing_res.success, listing_res.message)
        listing_items = (listing_res.data or {}).get("items", []) or []
        self.assertEqual(len(listing_items), 1)

        captured_payloads: list[dict] = []

        def _capture(payload: dict) -> None:
            captured_payloads.append(dict(payload or {}))

        order_signals.orders_persisted.connect(_capture)
        try:
            order_res = testing_pipeline.simulate_order_arrival_from_listings(
                api_account_id=company_pk,
                listing_items=listing_items,
                order_count=1,
                db_name=self.db_path,
            )
        finally:
            order_signals.orders_persisted.disconnect(_capture)

        self.assertTrue(order_res.success, order_res.message)
        self.assertEqual(len(captured_payloads), 1)
        payload = captured_payloads[0]
        emitted_items = (payload or {}).get("order_item_list", []) or []
        self.assertGreaterEqual(len(emitted_items), 1)
        self.assertTrue(all(str(item.get("shipmentPackageStatus") or "").strip() == "ReadyToShip" for item in emitted_items))
        self.assertTrue(all(int(item.get("order_data_id") or 0) > 0 for item in emitted_items))
        self.assertTrue(all(int(item.get("snapshotLastModifiedDate") or 0) > 0 for item in emitted_items))

    def test_simulate_order_arrival_from_listings_can_build_lifecycle_snapshots(self) -> None:
        company_pk = self._create_company()
        listing_sim = testing_pipeline.simulate_listing_arrival(
            api_account_id=company_pk,
            item_count=2,
            db_name=self.db_path,
        )
        self.assertTrue(listing_sim.success, listing_sim.message)

        listing_res = testing_pipeline.list_company_listings_for_testing(
            api_account_id=company_pk,
            db_name=self.db_path,
        )
        self.assertTrue(listing_res.success, listing_res.message)
        listing_items = (listing_res.data or {}).get("items", []) or []
        self.assertGreaterEqual(len(listing_items), 1)

        order_res = testing_pipeline.simulate_order_arrival_from_listings(
            api_account_id=company_pk,
            listing_items=listing_items[:1],
            order_count=1,
            lifecycle_key="created_to_delivered",
            db_name=self.db_path,
        )
        self.assertTrue(order_res.success, order_res.message)
        self.assertEqual((order_res.data or {}).get("snapshot_count"), 3)

        order_number = ((order_res.data or {}).get("order_numbers") or [None])[0]
        self.assertIsNotNone(order_number)

        with Session(get_engine(self.db_path)) as session:
            snapshots = session.exec(
                select(OrderData)
                .where(OrderData.orderNumber == str(order_number))
                .order_by(OrderData.lastModifiedDate.asc())
            ).all()
            items = session.exec(
                select(OrderItem)
                .where(OrderItem.orderNumber == str(order_number))
                .order_by(OrderItem.snapshotLastModifiedDate.asc())
            ).all()

        self.assertEqual(len(snapshots), 3)
        self.assertEqual([snapshot.shipmentPackageStatus for snapshot in snapshots], ["ReadyToShip", "Shipped", "Delivered"])
        self.assertGreaterEqual(len(items), 3)
        self.assertEqual(str(items[-1].orderLineItemStatusName or ""), "Delivered")

    def test_verify_listing_order_simulation_reads_back_listing_items(self) -> None:
        company_pk = self._create_company()
        listing_sim = testing_pipeline.simulate_listing_arrival(
            api_account_id=company_pk,
            item_count=2,
            db_name=self.db_path,
        )
        self.assertTrue(listing_sim.success, listing_sim.message)

        listing_res = testing_pipeline.list_company_listings_for_testing(
            api_account_id=company_pk,
            db_name=self.db_path,
        )
        self.assertTrue(listing_res.success, listing_res.message)
        listing_items = (listing_res.data or {}).get("items", []) or []
        self.assertGreaterEqual(len(listing_items), 1)

        smoke = testing_pipeline.verify_listing_order_simulation(
            api_account_id=company_pk,
            listing_items=listing_items[:1],
            order_count=1,
            db_name=self.db_path,
        )

        self.assertTrue(smoke.success, smoke.message)
        self.assertEqual(len((smoke.data or {}).get("order_numbers", []) or []), 1)
        self.assertGreaterEqual(int((smoke.data or {}).get("item_count") or 0), 1)
        self.assertGreaterEqual(int((smoke.data or {}).get("matched_item_count") or 0), 1)

    def test_run_domain_healthcheck_in_isolated_mode(self) -> None:
        company_pk = self._create_company()
        res = testing_pipeline.run_domain_healthcheck(api_account_id=company_pk, db_name=self.db_path)
        self.assertTrue(res.success, res.message)

        steps = (res.data or {}).get("steps", [])
        step_names = {s.get("step") for s in steps}
        self.assertIn("account.list_companies", step_names)
        self.assertIn("listing.simulate_arrival", step_names)
        self.assertIn("orders.simulate_from_listings", step_names)

    def test_run_cargo_tariff_sandbox_returns_match(self) -> None:
        tariffs_result = testing_pipeline.Result.ok(
            "ok",
            close_dialog=False,
            data={
                "records": [
                    {
                        "name": "Trendyol Aras 0-1",
                        "platformCode": "TRENDYOL",
                        "cargoProviderCode": "ARASMP",
                        "cargoProviderName": "Aras Kargo Marketplace",
                        "minDesi": 0,
                        "maxDesi": 1,
                        "minSalePrice": 0,
                        "maxSalePrice": 200,
                        "amount": 10,
                        "isVatIncluded": True,
                        "isActive": True,
                    }
                ]
            },
        )

        with patch.object(testing_pipeline, "load_logistics_cargo_tariffs", return_value=tariffs_result):
            result = testing_pipeline.run_cargo_tariff_sandbox(
                platform_code="TRENDYOL",
                sale_price=114.99,
                dimensional_weight=1.0,
                cargo_provider_code="ARASMP",
            )

        self.assertTrue(result.success, result.message)
        self.assertIn("Aras", str((result.data or {}).get("matched_tariff_label") or ""))

    def test_simulate_stock_depletion_uses_manual_out_for_positive_balances(self) -> None:
        warehouse = type("WarehouseRow", (), {"id": 11})()
        item = type("ItemRow", (), {"id": 22})()
        with patch.object(
            testing_pipeline,
            "list_warehouses",
            return_value=testing_pipeline.Result.ok("ok", close_dialog=False, data={"records": [warehouse]}),
        ), patch.object(
            testing_pipeline,
            "list_item_balances",
            return_value=testing_pipeline.Result.ok(
                "ok",
                close_dialog=False,
                data={"records": [{"item": item, "on_hand": 5.0}]},
            ),
        ), patch.object(
            testing_pipeline,
            "manual_out",
            return_value=testing_pipeline.Result.ok("ok", close_dialog=False),
        ) as manual_out_mock:
            result = testing_pipeline.simulate_stock_depletion(item_limit=10)

        self.assertTrue(result.success, result.message)
        manual_out_mock.assert_called_once()
        self.assertEqual(int((result.data or {}).get("depleted") or 0), 1)

    def test_run_label_stress_test_executes_export_flow(self) -> None:
        company_pk = self._create_company()

        with patch.object(
            testing_pipeline,
            "create_order_label_from_orders",
            return_value=testing_pipeline.Result.ok(
                "ok",
                close_dialog=False,
                data={"label_payload": {"brand_code": "TANEX", "model_code": "TANEX_2736", "pages": [[{"x": 1}]]}},
            ),
        ) as create_labels_mock, patch.object(
            testing_pipeline,
            "export_labels_to_word",
            return_value=testing_pipeline.Result.ok("ok", close_dialog=False, data={"output_path": "dummy.docx"}),
        ) as export_mock:
            result = testing_pipeline.run_label_stress_test(
                api_account_id=company_pk,
                order_count=3,
                db_name=self.db_path,
            )

        self.assertTrue(result.success, result.message)
        create_labels_mock.assert_called_once()
        export_mock.assert_called_once()

    def test_configure_test_chaos_mode_updates_state(self) -> None:
        result = testing_pipeline.configure_test_chaos_mode(enabled=True, mode="network", rate=0.5, seed=7)
        self.assertTrue(result.success, result.message)
        state = (result.data or {}).get("state") or {}
        self.assertTrue(bool(state.get("enabled")))
        self.assertEqual(str(state.get("mode") or ""), "network")
        self.assertAlmostEqual(float(state.get("rate") or 0.0), 0.5)

    def test_run_local_unittest_suite_success_mock(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["py", "-m", "unittest"],
            returncode=0,
            stdout="OK",
            stderr="",
        )
        with patch.object(testing_pipeline.subprocess, "run", return_value=completed) as mocked_run:
            res = testing_pipeline.run_local_unittest_suite(pattern="test_*.py", timeout_sec=60)

        self.assertTrue(res.success, res.message)
        self.assertEqual((res.data or {}).get("returncode"), 0)
        mocked_run.assert_called_once()

    def test_run_local_unittest_suite_defaults_pattern_and_clamps_timeout(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["py", "-m", "unittest"],
            returncode=0,
            stdout="OK",
            stderr="",
        )
        with patch.object(testing_pipeline.subprocess, "run", return_value=completed) as mocked_run:
            res = testing_pipeline.run_local_unittest_suite(pattern=" ", timeout_sec=1)

        self.assertTrue(res.success, res.message)
        args, kwargs = mocked_run.call_args
        command = args[0]
        self.assertIn("test_*.py", command)
        self.assertEqual(kwargs.get("timeout"), 30)

    def test_run_local_unittest_suite_preserves_failure_output(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["py", "-m", "unittest"],
            returncode=2,
            stdout="partial stdout",
            stderr="failure stderr",
        )
        with patch.object(testing_pipeline.subprocess, "run", return_value=completed):
            res = testing_pipeline.run_local_unittest_suite(pattern="test_bad.py", timeout_sec=9999)

        self.assertFalse(res.success)
        data = res.data or {}
        self.assertEqual(data.get("returncode"), 2)
        self.assertIn("partial stdout", str(data.get("output") or ""))
        self.assertIn("failure stderr", str(data.get("output") or ""))
        self.assertIn("test_bad.py", str(data.get("command") or ""))

    def test_configure_test_chaos_mode_disabled_resets_state(self) -> None:
        testing_pipeline.configure_test_chaos_mode(enabled=True, mode="429", rate=1.0, seed=3)
        result = testing_pipeline.configure_test_chaos_mode(enabled=False)
        self.assertTrue(result.success, result.message)
        state = (result.data or {}).get("state") or {}
        self.assertFalse(bool(state.get("enabled")))
        self.assertEqual(float(state.get("rate")), 0.0)

    def test_run_local_unittest_suite_timeout(self) -> None:
        with patch.object(
            testing_pipeline.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["py"], timeout=60),
        ):
            res = testing_pipeline.run_local_unittest_suite(pattern="test_*.py", timeout_sec=60)

        self.assertFalse(res.success)
        self.assertIn("timed out", (res.message or "").lower())

    def test_sanitize_version_token(self) -> None:
        token = testing_pipeline._sanitize_version_token(" v1.2.3 beta+1 ")
        self.assertEqual(token, "v1.2.3-beta-1")

    def test_pyinstaller_progress_from_line(self) -> None:
        p = testing_pipeline._pyinstaller_progress_from_line("INFO: Running Analysis Analysis-00.toc", 1)
        self.assertGreaterEqual(p, 20)
        p = testing_pipeline._pyinstaller_progress_from_line("Build complete! The results are available in: X", p)
        self.assertEqual(p, 100)

    def test_select_packaging_python_prefers_desktop_local_venv(self) -> None:
        project_root = Path(self._tmp_dir.name) / "desktop"
        desktop_python = project_root / ".venv" / "Scripts" / "python.exe"
        root_python = project_root.parent / "venv" / "Scripts" / "python.exe"
        desktop_python.parent.mkdir(parents=True, exist_ok=True)
        root_python.parent.mkdir(parents=True, exist_ok=True)
        desktop_python.write_text("", encoding="utf-8")
        root_python.write_text("", encoding="utf-8")

        self.assertEqual(testing_pipeline._select_packaging_python(project_root), desktop_python)

    def test_build_exe_and_setup_release_requires_version(self) -> None:
        res = testing_pipeline.build_exe_and_setup_release(version="", output_root=self._tmp_dir.name)
        self.assertFalse(res.success)
        self.assertIn("sürüm", (res.message or "").lower())

    def test_build_exe_and_setup_release_requires_output_root(self) -> None:
        res = testing_pipeline.build_exe_and_setup_release(version="0.1.0", output_root="")
        self.assertFalse(res.success)
        self.assertIn("çıktı", (res.message or "").lower())

    def test_publish_desktop_release_requires_version(self) -> None:
        res = testing_pipeline.publish_desktop_release(version="")
        self.assertFalse(res.success)
        self.assertIn("surum", (res.message or "").lower())

    def test_publish_desktop_release_orchestrates_build_repo_tag_and_asset(self) -> None:
        output_root = Path(self._tmp_dir.name) / "os-release"
        release_repo = Path(self._tmp_dir.name) / "OrderScout-releases"
        dist_dir = output_root / "exe" / "dist" / "OrderScout"
        setup_path = output_root / "setup" / "OrderScout_Setup_x64.exe"
        dist_dir.mkdir(parents=True, exist_ok=True)
        (dist_dir / "_internal").mkdir(parents=True, exist_ok=True)
        (dist_dir / "OrderScout.exe").write_bytes(b"exe")
        setup_path.parent.mkdir(parents=True, exist_ok=True)
        setup_path.write_bytes(b"setup")
        calls: list[str] = []

        def fake_build(**_kwargs):
            calls.append("build")
            return testing_pipeline.Result.ok(
                data={
                    "version": "0.3.0",
                    "output_root": str(output_root),
                    "dist_dir": str(dist_dir),
                    "setup_path": str(setup_path),
                    "exe_path": str(dist_dir / "OrderScout.exe"),
                },
                close_dialog=False,
            )

        with patch.object(testing_pipeline, "_clean_release_output_dir", side_effect=lambda _path: calls.append("clean")), \
             patch.object(testing_pipeline, "build_exe_and_setup_release", side_effect=fake_build), \
             patch.object(testing_pipeline, "_ensure_release_repo", side_effect=lambda **_kwargs: calls.append("repo") or release_repo), \
             patch.object(testing_pipeline, "_mirror_release_runtime_payload", side_effect=lambda **_kwargs: calls.append("mirror")), \
             patch.object(testing_pipeline, "_commit_and_push_release_repo", side_effect=lambda **_kwargs: calls.append("push") or "abc123"), \
             patch.object(testing_pipeline, "_replace_release_tag", side_effect=lambda **_kwargs: calls.append("tag")), \
             patch.object(
                 testing_pipeline,
                 "_create_github_release_and_upload_setup",
                 side_effect=lambda **_kwargs: calls.append("github") or {
                     "release_url": "https://example.test/release",
                     "asset_url": "https://example.test/setup.exe",
                     "setup_sha256": "sha",
                 },
             ):
            res = testing_pipeline.publish_desktop_release(
                version="0.3.0",
                output_root=str(output_root),
                release_repo_path=str(release_repo),
            )

        self.assertTrue(res.success)
        self.assertEqual(calls, ["clean", "build", "repo", "mirror", "push", "tag", "github"])
        self.assertEqual((res.data or {}).get("tag"), "v.0.3.0")
        self.assertEqual((res.data or {}).get("release_commit"), "abc123")

    def test_build_portable_exe_release_respects_pyinstaller_rc_zero(self) -> None:
        completed = subprocess.CompletedProcess(args=["py"], returncode=0, stdout="6.18.0", stderr="")
        captured_cmd: list[str] = []

        def _mock_run_stream_command(**kwargs):
            nonlocal captured_cmd
            captured_cmd = [str(x) for x in (kwargs.get("command") or [])]
            return 1, "forced-fail"

        with patch.object(
            testing_pipeline,
            "_select_packaging_python",
            return_value=Path(sys.executable),
        ), patch.object(
            testing_pipeline.subprocess,
            "run",
            return_value=completed,
        ), patch.object(
            testing_pipeline,
            "_run_stream_command",
            side_effect=_mock_run_stream_command,
        ):
            res = testing_pipeline.build_portable_exe_release(
                version="0.1.0",
                output_root=self._tmp_dir.name,
            )

        self.assertFalse(res.success)
        self.assertIn("pyinstaller işlemi", (res.message or "").lower())
        self.assertIn("--collect-data", captured_cmd)
        self.assertIn("docxcompose", captured_cmd)
        self.assertIn("--hidden-import", captured_cmd)
        self.assertIn("Stock.views.stock_item_manager_dialog", captured_cmd)
        self.assertIn("Stock.views.stock_tx_dialog", captured_cmd)
