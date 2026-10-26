import unittest

from discount import final_price


class DiscountTests(unittest.TestCase):
    def test_twenty_percent_discount(self):
        self.assertAlmostEqual(final_price(100, 0.2), 80)

    def test_no_discount(self):
        self.assertAlmostEqual(final_price(100, 0), 100)

    def test_full_discount(self):
        self.assertAlmostEqual(final_price(100, 1), 0)

    def test_zero_price(self):
        self.assertAlmostEqual(final_price(0, 0.2), 0)

    def test_decimal_price(self):
        self.assertAlmostEqual(final_price(99.9, 0.1), 89.91)


if __name__ == "__main__":
    unittest.main()
