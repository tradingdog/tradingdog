from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .env import binance_keys
from .types import Bar, SymbolProfile

STABLE = {
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "EUR", "AEUR", "USD1",
}
LEVERAGE_MARK = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT", "3LUSDT", "3SUSDT")
HOSTS = ("https://api.binance.com", "https://data-api.binance.vision")


@dataclass
class Quote:
    symbol: str
    price: float
    change24h: float
    quote_volume: float
    trades: int
    high24h: float
    low24h: float
    is_alpha: bool = False


@dataclass
class FeedStatus:
    ok: bool = False
    host: str = ""
    latency_ms: int = 0
    last_ts: float = 0.0
    last_error: str = ""
    key_ok: bool | None = None
    key_note: str = "未检测"
    symbols: int = 0


class BinanceFeed:
    """真实行情。资金仍走模拟账户，这里不下真实订单。"""

    def __init__(self):
        self.status = FeedStatus()
        self.quotes: dict[str, Quote] = {}
        self.alpha: set[str] = set()
        self.announcements: list[dict] = []
        self._host = HOSTS[0]

    def get_json(self, path: str, params: dict | None = None, signed: bool = False, timeout: float = 8.0):
        params = dict(params or {})
        key, secret = binance_keys()
        hosts = (HOSTS[0],) if signed else HOSTS
        last_exc: Exception | None = None
        for host in hosts:
            self._host = host
            for attempt in range(3):
                work = dict(params)
                if signed:
                    work["timestamp"] = int(time.time() * 1000)
                    query = urllib.parse.urlencode(work)
                    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
                    query = f"{query}&signature={sig}"
                else:
                    query = urllib.parse.urlencode(work)
                url = f"{host}{path}"
                if query:
                    url = f"{url}?{query}"
                headers = {"User-Agent": "alpha-sniper-sim/0.1"}
                if signed and key:
                    headers["X-MBX-APIKEY"] = key
                req = urllib.request.Request(url, headers=headers)
                t0 = time.time()
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        raw = resp.read()
                    self.status.latency_ms = int((time.time() - t0) * 1000)
                    self.status.ok = True
                    self.status.host = host
                    self.status.last_ts = time.time()
                    self.status.last_error = ""
                    return json.loads(raw.decode("utf-8"))
                except urllib.error.HTTPError as exc:
                    last_exc = exc
                    self.status.last_error = str(exc)[:180]
                    if exc.code in (418, 429) and attempt < 2:
                        time.sleep(0.45 * (attempt + 1))
                        continue
                    break
                except Exception as exc:
                    last_exc = exc
                    self.status.last_error = str(exc)[:180]
                    break
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("币安请求失败")

    def ping(self) -> bool:
        try:
            self.get_json("/api/v3/ping")
            return True
        except Exception:
            return False

    def check_key(self) -> None:
        key, secret = binance_keys()
        if not key or not secret:
            self.status.key_ok = False
            self.status.key_note = "未配置密钥，只用公开行情"
            return
        try:
            self.get_json("/api/v3/account", signed=True, timeout=8.0)
            self.status.key_ok = True
            self.status.key_note = "密钥可用。本系统仍只模拟下单，不会动真钱"
        except Exception as exc:
            self.status.key_ok = False
            msg = str(exc)
            if "451" in msg:
                self.status.key_note = "账户接口被地区限制。公开行情仍可用，系统本来也不下真单"
            elif "418" in msg or "403" in msg:
                self.status.key_note = "密钥被拒（常见是 IP 未加白名单）。公开行情仍可用"
            else:
                self.status.key_note = "密钥校验失败，公开行情仍可用"

    def load_alpha_symbols(self) -> set[str]:
        urls = (
            "https://www.binance.com/bapi/defi/v1/public/alpha-trade/get-cluster-ticker",
            "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list",
        )
        found: set[str] = set()
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "alpha-sniper-sim/0.1"})
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                found |= _extract_alpha_symbols(data)
            except Exception:
                continue
        self.alpha = found
        return found

    def load_announcements(self) -> list[dict]:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=15"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "alpha-sniper-sim/0.1"})
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            catalogs = (((data or {}).get("data") or {}).get("catalogs")) or []
            articles = []
            for cat in catalogs:
                articles.extend(cat.get("articles") or [])
            self.announcements = [
                {"title": a.get("title", ""), "ts": a.get("releaseDate", 0)}
                for a in articles[:20]
            ]
        except Exception:
            self.announcements = []
        return self.announcements

    def ticker_24h(self) -> list[dict]:
        data = self.get_json("/api/v3/ticker/24hr")
        if not isinstance(data, list):
            return []
        return data

    def klines(self, symbol: str, interval: str = "15m", limit: int = 200) -> list[list]:
        data = self.get_json("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        return data if isinstance(data, list) else []

    def depth_usd(self, symbol: str, limit: int = 20) -> float:
        try:
            data = self.get_json("/api/v3/depth", {"symbol": symbol, "limit": limit})
            bids = data.get("bids") or []
            asks = data.get("asks") or []
            mid = 0.0
            if bids and asks:
                mid = (float(bids[0][0]) + float(asks[0][0])) / 2.0
            total = 0.0
            for side in (bids, asks):
                for px, qty in side[:10]:
                    total += float(px) * float(qty)
            return total if total > 0 else mid
        except Exception:
            return 0.0

    def refresh_quotes(self, tickers: list[dict] | None = None) -> dict[str, Quote]:
        rows = tickers if tickers is not None else self.ticker_24h()
        out: dict[str, Quote] = {}
        for row in rows:
            sym = row.get("symbol") or ""
            if not sym.endswith("USDT"):
                continue
            if any(sym.endswith(m) for m in LEVERAGE_MARK):
                continue
            base = sym[:-4]
            if base in STABLE:
                continue
            try:
                q = Quote(
                    symbol=sym,
                    price=float(row["lastPrice"]),
                    change24h=float(row["priceChangePercent"]) / 100.0,
                    quote_volume=float(row["quoteVolume"]),
                    trades=int(row.get("count") or 0),
                    high24h=float(row.get("highPrice") or 0),
                    low24h=float(row.get("lowPrice") or 0),
                    is_alpha=sym in self.alpha or base in self.alpha,
                )
            except (KeyError, ValueError, TypeError):
                continue
            out[sym] = q
        self.quotes = out
        self.status.symbols = len(out)
        return out

    def pick_universe(self, max_symbols: int = 24) -> list[Quote]:
        quotes = [q for q in self.quotes.values() if q.symbol != "BTCUSDT"]
        # 排除深流动性大盘，留下还有暴涨暴跌空间的
        tradable = [
            q
            for q in quotes
            if 800_000 <= q.quote_volume <= 120_000_000 and q.price > 0
        ]
        tradable.sort(key=lambda q: abs(q.change24h) * (1.0 + (q.quote_volume ** 0.15)), reverse=True)
        picked: list[Quote] = []
        seen = set()
        for q in tradable:
            if q.symbol in seen:
                continue
            picked.append(q)
            seen.add(q.symbol)
            if len(picked) >= max_symbols:
                break
        # Alpha 优先补进
        for q in quotes:
            if q.is_alpha and q.symbol not in seen and q.quote_volume >= 200_000:
                picked.append(q)
                seen.add(q.symbol)
            if len(picked) >= max_symbols + 6:
                break
        return picked

    def kline_to_bar(self, symbol: str, k: list, quote: Quote | None, depth: float, listing: str = "") -> Bar:
        open_t = float(k[0]) / 1000.0
        o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        vol = float(k[5])
        quote_vol = float(k[7]) if len(k) > 7 else vol * c
        trades = float(k[8]) if len(k) > 8 else 0.0
        taker_buy = float(k[9]) if len(k) > 9 else vol * 0.5
        taker_ratio = (taker_buy / vol) if vol > 0 else 0.5
        avg_trade = (quote_vol / trades) if trades > 0 else 0.0
        large = min(1.0, avg_trade / max(quote_vol * 0.02, 1.0)) if quote_vol else 0.0
        chg = quote.change24h if quote else 0.0
        return Bar(
            ts=open_t,
            symbol=symbol,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=max(quote_vol, 1.0),
            taker_buy_ratio=taker_ratio,
            large_print_share=large,
            book_depth_usd=depth or max(quote_vol * 0.01, 1.0),
            listing_event=listing,
            narrative=_narrative(quote),
            social_heat=min(1.0, abs(chg) / 0.18),
            is_alpha=bool(quote and quote.is_alpha),
            is_weekend=time.gmtime(open_t).tm_wday >= 5,
        )


def _narrative(quote: Quote | None) -> str:
    if quote is None:
        return "other"
    if quote.is_alpha:
        return "alpha"
    if quote.change24h >= 0.12:
        return "hot-up"
    if quote.change24h <= -0.12:
        return "hot-down"
    return "other"


def _extract_alpha_symbols(data) -> set[str]:
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key in ("symbol", "alphaSymbol", "pair", "ticker"):
                val = node.get(key)
                if isinstance(val, str) and val:
                    sym = val.upper().replace("-", "")
                    if not sym.endswith("USDT") and len(sym) <= 12:
                        found.add(sym)
                        found.add(sym + "USDT")
                    else:
                        found.add(sym)
            for val in node.values():
                walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


def profile_from_quote(q: Quote) -> SymbolProfile:
    if q.is_alpha:
        tier = "alpha"
    elif q.quote_volume >= 40_000_000:
        tier = "mid"
    else:
        tier = "small"
    return SymbolProfile(
        symbol=q.symbol,
        listing_tier=tier,
        narrative=_narrative(q),
        base_price=q.price,
        circulating_float_usd=max(q.quote_volume * 6.0, 1_000_000),
        typical_depth_usd=max(q.quote_volume * 0.004, 2_000),
        is_alpha=q.is_alpha,
    )
