from __future__ import annotations

import unittest

from alpha_sniper.binance_feed import BinanceFeed


class FeedParseTests(unittest.TestCase):
    def test_filters_stables_and_picks_quiet_over_fat(self):
        feed = BinanceFeed()
        feed.refresh_quotes(
            [
                {
                    "symbol": "BTCUSDT",
                    "lastPrice": "60000",
                    "priceChangePercent": "1.2",
                    "quoteVolume": "2000000000",
                    "count": 10,
                    "highPrice": "61000",
                    "lowPrice": "59000",
                },
                {
                    "symbol": "USDCUSDT",
                    "lastPrice": "1",
                    "priceChangePercent": "0.01",
                    "quoteVolume": "900000000",
                    "count": 10,
                    "highPrice": "1",
                    "lowPrice": "1",
                },
                {
                    "symbol": "ABCUPUSDT",
                    "lastPrice": "2",
                    "priceChangePercent": "40",
                    "quoteVolume": "5000000",
                    "count": 10,
                    "highPrice": "3",
                    "lowPrice": "1",
                },
                {
                    "symbol": "PEPEUSDT",
                    "lastPrice": "0.000012",
                    "priceChangePercent": "18.5",
                    "quoteVolume": "12000000",
                    "count": 80,
                    "highPrice": "0.000014",
                    "lowPrice": "0.00001",
                },
                {
                    "symbol": "QUIETUSDT",
                    "lastPrice": "1.2",
                    "priceChangePercent": "2.4",
                    "quoteVolume": "8000000",
                    "count": 40,
                    "highPrice": "1.22",
                    "lowPrice": "1.17",
                },
                {
                    "symbol": "FATUSDT",
                    "lastPrice": "10",
                    "priceChangePercent": "1.0",
                    "quoteVolume": "500000000",
                    "count": 10,
                    "highPrice": "10.1",
                    "lowPrice": "9.9",
                },
                {
                    "symbol": "NVDABUSDT",
                    "lastPrice": "225",
                    "priceChangePercent": "0.2",
                    "quoteVolume": "2000000",
                    "count": 10,
                    "highPrice": "228",
                    "lowPrice": "220",
                },
                {
                    "symbol": "ETHUSDT",
                    "lastPrice": "3000",
                    "priceChangePercent": "1.0",
                    "quoteVolume": "8000000",
                    "count": 40,
                    "highPrice": "3050",
                    "lowPrice": "2950",
                },
                {
                    "symbol": "TRBUSDT",
                    "lastPrice": "13.3",
                    "priceChangePercent": "1.0",
                    "quoteVolume": "3000000",
                    "count": 10,
                    "highPrice": "13.6",
                    "lowPrice": "13.0",
                },
            ]
        )
        self.assertIn("BTCUSDT", feed.quotes)
        self.assertNotIn("USDCUSDT", feed.quotes)
        self.assertNotIn("ABCUPUSDT", feed.quotes)
        self.assertNotIn("NVDABUSDT", feed.quotes)
        self.assertIn("TRBUSDT", feed.quotes)
        picked = feed.pick_universe(8)
        names = [q.symbol for q in picked]
        self.assertIn("QUIETUSDT", names)
        self.assertIn("PEPEUSDT", names)
        self.assertNotIn("FATUSDT", names)
        self.assertNotIn("ETHUSDT", names)
        quiet = next(q for q in picked if q.symbol == "QUIETUSDT")
        self.assertEqual(quiet.bucket, "coil")
        pepe = next(q for q in picked if q.symbol == "PEPEUSDT")
        self.assertEqual(pepe.bucket, "parabolic")
        from alpha_sniper.binance_feed import profile_from_quote

        self.assertEqual(profile_from_quote(quiet).narrative, "solo:QUIETUSDT")
        self.assertEqual(profile_from_quote(pepe).narrative, "solo:PEPEUSDT")
