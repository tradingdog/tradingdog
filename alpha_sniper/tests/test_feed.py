from __future__ import annotations

import unittest

from alpha_sniper.binance_feed import BinanceFeed


class FeedParseTests(unittest.TestCase):
    def test_filters_stables_and_picks_mover(self):
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
            ]
        )
        self.assertIn("BTCUSDT", feed.quotes)
        self.assertNotIn("USDCUSDT", feed.quotes)
        self.assertNotIn("ABCUPUSDT", feed.quotes)
        picked = feed.pick_universe(8)
        self.assertTrue(any(q.symbol == "PEPEUSDT" for q in picked))
