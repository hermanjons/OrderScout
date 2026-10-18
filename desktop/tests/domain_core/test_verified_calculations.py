from __future__ import annotations

import unittest

from Core.processors.verified_calculations import (
    evaluate_verified_calculation,
    evaluate_verified_comparison,
)


class VerifiedCalculationTests(unittest.TestCase):
    def test_division_uses_decimal_half_up_rounding_and_exposes_work(self) -> None:
        result = evaluate_verified_calculation(
            operator="divide",
            operands=[502518.01, 3112],
            precision=2,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(result.data["result"], "161.48")
        self.assertEqual(result.data["expression"], "502518.01 / 3112 = 161.48")
        self.assertEqual(result.data["rounding"], "ROUND_HALF_UP")
        self.assertTrue(result.data["verified"])
        self.assertEqual(len(result.data["evidence_hash"]), 64)

    def test_percentage_is_distinct_from_plain_division(self) -> None:
        result = evaluate_verified_calculation(
            operator="percentage",
            operands=[2957, 3112],
            precision=2,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(result.data["result"], "95.02")
        self.assertEqual(
            result.data["expression"],
            "2957 / 3112 × 100 = 95.02",
        )

    def test_division_by_zero_fails_closed(self) -> None:
        result = evaluate_verified_calculation(
            operator="divide",
            operands=[10, 0],
            precision=2,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.data["reason"], "division_by_zero")

    def test_quantity_scales_convert_a_ratio_once_and_preserve_existing_percent(self) -> None:
        cases = [
            ("divide", [99, 570], [1, 1], "0.01", "17.368", "100"),
            ("percentage", [99, 570], [1, 1], "0.01", "17.368", "100"),
            ("divide", ["17.37", 2], ["0.01", 1], "0.01", "8.685", "1"),
            ("percentage", ["17.37", 2], ["0.01", 1], "0.01", "8.685", "1"),
            ("divide", ["17.37", 10], ["0.01", "0.01"], "0.01", "173.700", "100"),
            ("multiply", ["17.37", 10], ["0.01", "0.01"], "0.01", "1.737", "0.01"),
            ("divide", ["17.37", 2], ["0.01", 1], 1, "0.087", "0.01"),
        ]
        for operator, operands, scales, output_scale, expected, factor in cases:
            with self.subTest(operator=operator, operands=operands, scales=scales, output_scale=output_scale):
                result = evaluate_verified_calculation(operator=operator, operands=operands,
                    precision=3, operand_scales=scales, result_scale=output_scale)
                self.assertTrue(result.success, result.data)
                self.assertEqual(result.data["operator"], operator)
                self.assertEqual(result.data["result"], expected)
                self.assertEqual(result.data["quantity_scaling"]["display_result_multiplier"], factor)
                self.assertEqual(len(result.data["evidence_hash"]), 64)

    def test_mixed_display_scales_share_one_base_without_intermediate_rounding(self) -> None:
        for operator, expected in (("add", "20.001"), ("subtract", "0.001"),
            ("minimum", "10.000"), ("maximum", "10.001")):
            with self.subTest(operator=operator):
                result = evaluate_verified_calculation(operator=operator,
                    operands=["10.001", "0.1"], operand_scales=["0.01", 1],
                    result_scale="0.01", precision=3)
                self.assertTrue(result.success, result.data)
                self.assertEqual(result.data["result"], expected)
                self.assertEqual(result.data["quantity_scaling"]["display_operand_multipliers"], ["1", "100"])

    def test_invalid_quantity_scales_fail_closed(self) -> None:
        for scales, output_scale in (([1], 1), ([1, 0], 1), ([1, -1], 1),
            ([1, True], 1), ([1, 1], 0), ([1, 1], float("inf"))):
            with self.subTest(scales=scales, output_scale=output_scale):
                result = evaluate_verified_calculation(operator="divide", operands=[1, 2],
                    operand_scales=scales, result_scale=output_scale)
                self.assertFalse(result.success)
                self.assertEqual(result.data["reason"], "invalid_quantity_scale")

    def test_non_finite_or_unbounded_precision_fails_closed(self) -> None:
        non_finite = evaluate_verified_calculation(
            operator="add",
            operands=[1, float("inf")],
            precision=2,
        )
        unbounded = evaluate_verified_calculation(
            operator="add",
            operands=[1, 2],
            precision=20,
        )

        self.assertFalse(non_finite.success)
        self.assertEqual(non_finite.data["reason"], "invalid_operand")
        self.assertFalse(unbounded.success)
        self.assertEqual(unbounded.data["reason"], "invalid_precision")

    def test_numeric_comparison_is_verified_with_immutable_evidence(self) -> None:
        equal = evaluate_verified_comparison(
            operator="equal",
            left="3119",
            right=3119,
        )
        mismatch = evaluate_verified_comparison(
            operator="equal",
            left=3118,
            right=3119,
        )

        self.assertTrue(equal.success, equal.message)
        self.assertTrue(equal.data["holds"])
        self.assertEqual(equal.data["expression"], "3119 = 3119")
        self.assertEqual(len(equal.data["evidence_hash"]), 64)
        self.assertTrue(mismatch.success, mismatch.message)
        self.assertFalse(mismatch.data["holds"])


if __name__ == "__main__":
    unittest.main()
