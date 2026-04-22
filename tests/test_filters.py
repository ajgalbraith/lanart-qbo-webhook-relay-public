import unittest

from app.filters import matches_customer_name


class CustomerFilterTests(unittest.TestCase):
    def test_excludes_costco_web_customers(self) -> None:
        self.assertFalse(
            matches_customer_name(
                "COSTCO_WEB",
                include_terms=["COSTCO"],
                exclude_terms=["COSTCO_WEB", "COSTCO WEB"],
            )
        )
        self.assertFalse(
            matches_customer_name(
                "COSTCO WHOLESALE CANADA LTD:COSTCO WEB",
                include_terms=["COSTCO"],
                exclude_terms=["COSTCO_WEB", "COSTCO WEB"],
            )
        )

    def test_allows_non_web_costco_customers(self) -> None:
        self.assertTrue(
            matches_customer_name(
                "COSTCO WHOLESALE CANADA #1034",
                include_terms=["COSTCO"],
                exclude_terms=["COSTCO_WEB", "COSTCO WEB"],
            )
        )


if __name__ == "__main__":
    unittest.main()
