import pytest
from openpyxl import load_workbook

from Orders.processors import profit_workbook
from Orders.views import actions


@pytest.fixture
def estimate():
    return {
        "estimated_profit_ready": True, "estimated_profit": 80, "estimated_profit_text": "80.00 TL",
        "estimated_profit_missing_reasons": [],
        "estimated_profit_detail": {
            "summary": {"order_number": "ORDER-17", "item_quantity_total_text": "2", "sale_price": 100},
            "results": {"sale_price": 100, "total_costs": 20, "total_costs_text": "20.00 TL"},
            "lines": [{"title": "=PRODUCT", "listing_title": "Test Listing", "qty_text": "2",
                       "unit_price_text": "50.00 TL", "amount": 100}],
            "applied_costs": [{"label": "Stock", "gross": 20, "note": "2 units"}],
        },
    }


def arguments(tmp_path, estimate):
    return dict(order_number="ORDER-17", api_account_id=101, estimated_profit_payload=estimate,
                output_path=str(tmp_path / "profit.xlsx"))


def test_manual_action_uses_the_shared_writer_and_every_sheet_is_read_back(tmp_path, estimate):
    kwargs = arguments(tmp_path, estimate)
    result = actions.action_export_order_profit_excel(**kwargs)
    assert result.success, result.message
    checked = profit_workbook.verify_order_profit_payload_xlsx(**kwargs)
    assert checked.success and checked.data["verified"]
    assert checked.data["verified_by"] == "xlsx_exact_snapshot_readback"
    assert checked.data["sheet_count"] == 3
    assert [row["row_count"] for row in checked.data["sheets"]] == [6, 1, 2]
    workbook = load_workbook(kwargs["output_path"], read_only=True, data_only=False)
    try:
        assert [sheet.title for sheet in workbook if sheet.sheet_state == "visible"] == ["Ozet", "Satis", "Maliyetler"]
        assert workbook["Satis"]["A2"].data_type != "f"
    finally:
        workbook.close()


@pytest.mark.parametrize("change", ["profit", "product", "cost", "missing_row", "extra_row", "formula", "manifest"])
def test_nonempty_workbook_with_altered_content_is_rejected(tmp_path, estimate, change):
    kwargs = arguments(tmp_path, estimate)
    assert profit_workbook.write_order_profit_payload_to_excel(**kwargs).success
    workbook = load_workbook(kwargs["output_path"])
    if change == "profit":
        workbook["Ozet"]["B6"] = "999.00 TL"
    elif change == "product":
        workbook["Satis"]["A2"] = "Other product"
    elif change == "cost":
        workbook["Maliyetler"]["C2"] = "0.00 TL"
    elif change == "missing_row":
        workbook["Satis"].delete_rows(2)
    elif change == "extra_row":
        workbook["Satis"].append(["Extra", "", "1", "0.00 TL", "0.00 TL"])
    elif change == "formula":
        workbook["Ozet"]["B6"] = "=80"
    else:
        del workbook["_OrderScout"]
    workbook.save(kwargs["output_path"])
    workbook.close()
    result = profit_workbook.verify_order_profit_payload_xlsx(**kwargs)
    assert not result.success and result.data["verified"] is False
    assert result.data["problems"]


def test_same_visible_values_for_another_account_cannot_replace_the_approved_workbook(tmp_path, estimate):
    kwargs = arguments(tmp_path, estimate)
    assert profit_workbook.write_order_profit_payload_to_excel(**kwargs).success
    result = profit_workbook.verify_order_profit_payload_xlsx(**{**kwargs, "api_account_id": 102})
    assert not result.success and "content_hash_mismatch" in result.data["problems"]


def test_incomplete_estimate_keeps_missing_values_unavailable(tmp_path, estimate):
    estimate.update(estimated_profit_ready=False, estimated_profit=None, estimated_profit_text="-",
                    estimated_profit_missing_reasons=["Stock cost is missing"])
    estimate["estimated_profit_detail"]["results"] = {}
    kwargs = arguments(tmp_path, estimate)
    assert profit_workbook.write_order_profit_payload_to_excel(**kwargs).success
    assert profit_workbook.verify_order_profit_payload_xlsx(**kwargs).success
    workbook = load_workbook(kwargs["output_path"], read_only=True)
    try:
        assert workbook["Ozet"]["B5"].value == "'-"
        assert workbook["Ozet"]["B7"].value == "Bekliyor"
    finally:
        workbook.close()


def test_snapshot_rejects_wrong_order_and_invalid_payload_without_overwriting_a_file(tmp_path, estimate):
    kwargs = arguments(tmp_path, estimate)
    path = tmp_path / "profit.xlsx"
    path.write_bytes(b"previous output")
    for values in ({**kwargs, "order_number": "OTHER"}, {**kwargs, "estimated_profit_payload": {}}):
        result = profit_workbook.write_order_profit_payload_to_excel(**values)
        assert not result.success
        assert path.read_bytes() == b"previous output"
        assert not profit_workbook.verify_order_profit_payload_xlsx(**values).success


def test_output_path_is_required_and_normalized_consistently(tmp_path, estimate):
    kwargs = arguments(tmp_path, estimate)
    kwargs["output_path"] = str(tmp_path / "profit")
    assert profit_workbook.write_order_profit_payload_to_excel(**kwargs).success
    assert (tmp_path / "profit.xlsx").is_file()
    assert profit_workbook.verify_order_profit_payload_xlsx(**kwargs).success
    assert not profit_workbook.write_order_profit_payload_to_excel(**{**kwargs, "output_path": " "}).success


def test_corrupted_zip_and_a_plain_file_do_not_count_as_verified_excel(tmp_path, estimate):
    kwargs = arguments(tmp_path, estimate)
    for content in (b"not a workbook", b"PK\x03\x04broken"):
        (tmp_path / "profit.xlsx").write_bytes(content)
        result = profit_workbook.verify_order_profit_payload_xlsx(**kwargs)
        assert not result.success and result.data["verified"] is False
