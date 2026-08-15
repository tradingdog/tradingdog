# Alpha Sniper

币安非对称机会猎手。只做 **现货 / 1x 合约 / Alpha**。默认空仓等待，只在「横盘缩量之后，至少三类独立信号同时出现」时开仓。

完整框架见 [`DESIGN.md`](DESIGN.md)。

## 这不是 100x 按钮

`1000 → 100000` 在半年内是肥尾结果，不是计划任务。本仓库实现的是：

- 先剔除大盘币，只看还有暴涨暴跌空间的标的
- 横盘缩量时先算好止损和方向，放量后只执行、不改主意
- 跨信号共振（三个成交量指标 = 一票）
- 持仓有失效价、时间止损、分批减仓
- 1x 硬顶、翻倍后锁定一部分利润、BTC 大跌禁止新开山寨多单

默认 **真实行情 + 模拟资金**。没有 `live: true` 不会下真单。

## 跑起来

密钥放环境变量，不要写进代码：

```
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
```

复制 `.env.example` 为 `.env`（已加入 gitignore）。

默认是 **币安真实行情 + 模拟资金**，不会下真单：

```bash
python -m alpha_sniper ui
```

本地回放、导出静态页、跑测试：

```bash
python -m alpha_sniper ui --paper
python -m alpha_sniper export
python -m alpha_sniper design
python -m alpha_sniper paper --days 40 --seed 42
python -m unittest alpha_sniper.tests.test_sniper alpha_sniper.tests.test_dashboard alpha_sniper.tests.test_feed alpha_sniper.tests.test_env
```

监控台给交易员看：空仓 / 已盯上 / 持仓中、可用资金、锁定利润、浮动盈亏、监控列表、开仓/平仓/过滤原因。可以暂停开仓、全部平仓、单笔平仓、拉黑币对、刷新行情、重置模拟资金。
