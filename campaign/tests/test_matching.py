import unittest

from campaign.matching import similarity


class MatchingSimilarityTests(unittest.TestCase):
    def test_similarity_identical(self) -> None:
        self.assertGreaterEqual(similarity("Delay 5 min", "Delay 5 min"), 90.0)

    def test_similarity_different(self) -> None:
        self.assertLess(similarity("Delay 5 min", "Platform change"), 80.0)


if __name__ == "__main__":
    unittest.main()
