from __future__ import annotations

import re
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from xml.etree import ElementTree

from docxtpl import DocxTemplate

from Feedback.processors.pipeline import Result
import Labels.processors.pipeline as label_pipeline
from Labels.processors.catalog import get_label_model_config, resolve_label_model_reference


class TestLabelPipeline(unittest.TestCase):
    @staticmethod
    def _document_xml(path: Path) -> str:
        with zipfile.ZipFile(path) as package:
            return package.read("word/document.xml").decode("utf-8")

    def test_tanex_2610_config_and_template_match_official_sheet_geometry(self) -> None:
        cfg = get_label_model_config("TANEX", "TANEX_2610")

        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["manufacturer_ref"], "TW-2610")
        self.assertEqual(cfg["labels_per_page"], 10)
        self.assertEqual((cfg["sheet_rows"], cfg["sheet_columns"]), (5, 2))
        self.assertEqual((cfg["label_width_mm"], cfg["label_height_mm"]), (105, 57))
        self.assertEqual(cfg["fields"]["product"]["font_size"], 18)
        self.assertEqual(cfg["fields"]["address"]["font_size"], 11)
        self.assertEqual(cfg["barcode"]["image_width_mm"], 54)
        self.assertEqual(cfg["barcode"]["module_height"], 9.0)
        self.assertAlmostEqual(cfg["barcode"]["image_width_mm"] / 60, 0.9)
        self.assertEqual(cfg["sla_image_width_mm"], 20)

        template_path = Path(cfg["template_path"])
        self.assertTrue(template_path.is_file())
        xml = self._document_xml(template_path)
        root = ElementTree.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        body = root.find("w:body", ns)
        outer_table = body.find("w:tbl", ns)
        grid_widths = [
            int(column.attrib[f"{{{ns['w']}}}w"])
            for column in outer_table.findall("w:tblGrid/w:gridCol", ns)
        ]
        row_heights = [
            int(row.find("w:trPr/w:trHeight", ns).attrib[f"{{{ns['w']}}}val"])
            for row in outer_table.findall("w:tr", ns)
        ]

        self.assertEqual(grid_widths, [5952, 5952])
        self.assertEqual(row_heights, [3231] * 5)
        self.assertIn('<w:pgMar w:top="340" w:right="0" w:bottom="0" w:left="0"', xml)
        self.assertEqual(xml.count('<w:tblStyle w:val="TableGrid"'), 10)

        outer_cells = outer_table.findall("w:tr/w:tc", ns)
        self.assertEqual(len(outer_cells), 10)
        for cell in outer_cells:
            top_margin = cell.find("w:tcPr/w:tcMar/w:top", ns)
            trailing_paragraph = cell.findall("w:p", ns)[-1]
            spacing = trailing_paragraph.find("w:pPr/w:spacing", ns)
            mark_size = trailing_paragraph.find("w:pPr/w:rPr/w:sz", ns)
            self.assertEqual(top_margin.attrib[f"{{{ns['w']}}}w"], "113")
            self.assertEqual(spacing.attrib[f"{{{ns['w']}}}line"], "20")
            self.assertEqual(spacing.attrib[f"{{{ns['w']}}}lineRule"], "exact")
            self.assertEqual(mark_size.attrib[f"{{{ns['w']}}}val"], "2")

        variables = DocxTemplate(str(template_path)).get_undeclared_template_variables()
        expected_roles = {
            "barcode",
            "ordernumber",
            "name",
            "address",
            "cargotrackingnumber",
            "cargoprovidername",
            "storename",
            "platform",
            "sla_hours_left",
            *(f"prod{i}" for i in range(1, 5)),
            *(f"qty{i}" for i in range(1, 5)),
        }
        expected_variables = {
            f"{role}_{slot}"
            for slot in range(1, 11)
            for role in expected_roles
        }
        self.assertEqual(variables, expected_variables)

    def test_label_catalog_resolves_user_facing_model_code_aliases_canonically(self) -> None:
        canonical = get_label_model_config("TANEX", "TANEX_2610")

        for brand_code, model_code in (
            ("tanex", "2610"),
            ("TANEX", "TW-2610"),
            ("Tanex", "tanex_2610"),
        ):
            resolved = get_label_model_config(brand_code, model_code)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.get("code"), "TANEX_2610")
            self.assertEqual(resolved.get("template_path"), canonical.get("template_path"))

    def test_label_catalog_resolves_combined_brand_and_model_argument(self) -> None:
        resolved = resolve_label_model_reference(
            "güzel bu siparişlerin tamamını TANEX 2610 etiketi olarak hazırla",
            brand_code="TANEX 2610",
            model_code="",
        )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.get("brand_code"), "TANEX")
        self.assertEqual(resolved.get("model_code"), "TANEX_2610")

    def test_tanex_2610_docxtpl_renders_all_ten_slots(self) -> None:
        cfg = get_label_model_config("TANEX", "TANEX_2610")
        template_path = Path(cfg["template_path"])
        doc = DocxTemplate(str(template_path))
        variables = doc.get_undeclared_template_variables()
        context = {variable: f"VALUE-{variable}" for variable in variables}

        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "tanex-2610-rendered.docx"
            doc.render(context)
            doc.save(output_path)
            rendered_text = re.sub(r"<[^>]+>", "", self._document_xml(output_path))

        for slot in range(1, 11):
            self.assertIn(f"VALUE-ordernumber_{slot}", rendered_text)

    def test_tanex_2610_export_paginates_eleven_labels(self) -> None:
        labels = []
        for index in range(1, 12):
            labels.append(
                {
                    "orderNumber": f"ORD-2610-{index:02d}",
                    "fullname": f"Test Kullanıcı {index}",
                    "address": f"Test adresi {index}",
                    "cargoTrackingNumber": f"869000000{index:02d}",
                    "cargoProviderName": "Test Kargo",
                    "storeName": "OrderScout Test",
                    "platform": "TRENDYOL",
                    "agreedDeliveryDate_ms": None,
                    "is_primary_for_order": True,
                    "prod1": f"Test ürünü {index}",
                    "qty1": "1",
                    "prod2": "",
                    "qty2": "",
                    "prod3": "",
                    "qty3": "",
                    "prod4": "",
                    "qty4": "",
                }
            )
        payload = {
            "brand_code": "TANEX",
            "model_code": "TANEX_2610",
            "labels_per_page": 10,
            "total_labels": len(labels),
            "total_pages": 2,
            "pages": [labels[:10], labels[10:]],
        }

        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "tanex-2610-eleven-labels.docx"
            result = label_pipeline.export_labels_to_word(payload, output_path=str(output_path))
            self.assertTrue(result.success, result.message)
            self.assertTrue(output_path.is_file())
            self.assertTrue((result.data or {}).get("geometry_verified"))
            self.assertEqual((result.data or {}).get("page_table_count"), 2)
            rendered_text = re.sub(r"<[^>]+>", "", self._document_xml(output_path))
            root = ElementTree.fromstring(self._document_xml(output_path))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            top_level_tables = root.findall("w:body/w:tbl", ns)
            self.assertEqual(len(top_level_tables), 2)
            for table in top_level_tables:
                grid_widths = [
                    int(column.attrib[f"{{{ns['w']}}}w"])
                    for column in table.findall("w:tblGrid/w:gridCol", ns)
                ]
                self.assertEqual(grid_widths, [5952, 5952])

        for index in range(1, 12):
            self.assertIn(f"ORD-2610-{index:02d}", rendered_text)

    def test_generate_code128_barcode_returns_png_bytes(self) -> None:
        cfg = get_label_model_config("TANEX", "TANEX_2736")
        barcode_cfg = cfg["barcode"]

        res = label_pipeline.generate_code128_barcode(
            value="11123930849",
            barcode_cfg=barcode_cfg,
            dpi=300,
        )

        self.assertTrue(res.success, res.message)
        self.assertGreater(len(res.data["png_bytes"]), 0)

    def test_fitted_label_text_reduces_and_then_truncates_long_values(self) -> None:
        with patch.object(
            label_pipeline,
            "_style_text",
            side_effect=lambda value, style: Result.ok(
                "ok",
                close_dialog=False,
                data={"val": value, "style": dict(style)},
            ),
        ):
            fitted = label_pipeline._style_fitted_text(
                "X" * 60,
                {
                    "font_name": "Arial",
                    "font_size": 18,
                    "fit_chars_at_base": 22,
                    "min_font_size": 8,
                },
            )

        self.assertTrue(fitted.success, fitted.message)
        self.assertEqual((fitted.data or {})["style"]["font_size"], 8)
        self.assertEqual(len((fitted.data or {})["val"]), 49)
        self.assertTrue((fitted.data or {})["val"].endswith("..."))

    def test_build_ctx_for_label_fails_when_primary_barcode_generation_fails(self) -> None:
        cfg = get_label_model_config("TANEX", "TANEX_2736")
        styles_res = label_pipeline._get_styles(cfg)
        self.assertTrue(styles_res.success, styles_res.message)

        doc = DocxTemplate(str(Path("desktop/Labels/assets/TANEX_2736.docx")))
        lbl = {
            "orderNumber": "ORD-1",
            "fullname": "Test User",
            "address": "Test Address",
            "cargoTrackingNumber": "11123930849",
            "cargoProviderName": "Aras",
            "storeName": "MDB",
            "platform": "TRENDYOL",
            "agreedDeliveryDate_ms": None,
            "is_primary_for_order": True,
            "prod1": "Urun",
            "qty1": "1",
        }

        with patch.object(
            label_pipeline,
            "generate_code128_barcode",
            return_value=Result.fail("simulated barcode failure", close_dialog=False),
        ):
            res = label_pipeline._build_ctx_for_label(
                doc=doc,
                cfg=cfg,
                styles=styles_res.data["styles"],
                lbl=lbl,
                cargo_logo_cfg_norm={},
                n=1,
                sla_threshold_hours=24,
                sla_mode="lte",
                qty_attention_threshold=2,
                qty_attention_color="FF0000",
                qty_attention_bold=True,
            )

        self.assertFalse(res.success)
        self.assertIn("Barkod", str(res.message))

    def test_safe_inline_image_uses_cached_bytes(self) -> None:
        cfg = get_label_model_config("TANEX", "TANEX_2736")
        doc = DocxTemplate(str(Path("desktop/Labels/assets/TANEX_2736.docx")))
        first_logo = next(iter(cfg["cargo_provider_logos"].values()))
        resolved = (label_pipeline.LABEL_IMAGES_DIR / first_logo["filename"]).resolve()
        label_pipeline._read_inline_image_bytes.cache_clear()
        before = label_pipeline._read_inline_image_bytes.cache_info()

        first = label_pipeline._read_inline_image_bytes(str(resolved))
        second = label_pipeline._read_inline_image_bytes(str(resolved))
        after = label_pipeline._read_inline_image_bytes.cache_info()
        one = label_pipeline._safe_inline_image(doc, path=resolved, width_mm=12)

        self.assertEqual(first, second)
        self.assertTrue(one.success, one.message)
        self.assertGreaterEqual(after.hits, before.hits + 1)

    def test_merge_pages_uses_chunked_merge_for_large_inputs(self) -> None:
        files = [f"page_{idx}.docx" for idx in range(120)]
        calls: list[list[str]] = []

        def _fake_merge(page_files: list[str], output_path: str):
            calls.append(list(page_files))
            return Result.ok("ok", close_dialog=False, data={"output_path": output_path})

        with patch.object(label_pipeline, "_merge_docx_files", side_effect=_fake_merge):
            with TemporaryDirectory() as temp_dir:
                output_path = str(Path(temp_dir) / "merged.docx")
                res = label_pipeline._merge_pages(files, output_path, chunk_size=50)

        self.assertTrue(res.success, res.message)
        self.assertGreater(len(calls), 1)
        self.assertLessEqual(max(len(call) for call in calls), 50)


if __name__ == "__main__":
    unittest.main()
