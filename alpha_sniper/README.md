# Alpha Sniper

币安非对称机会猎手。只做 **现货 / 1x 合约 / Alpha**。默认姿态是空仓蹲点，只在「沉寂之后多路独立证据同时点火」时开火。

完整框架与为什么不走技术指标，见 [`DESIGN.md`](DESIGN.md)。

## 这不是 100x 按钮

`1000 → 100000` 在半年内是肥尾结果，不是计划任务。本仓库实现的是：

- 负空间猎场（大盘币直接剔除）
- 缩簧表 + 预计算单（点火后不许现场想策略）
- 跨证据族共振（三个成交量指标 = 一票）
- 命题生命周期（失效价、时间止损、分批、跟踪）
- 1x 硬顶、棘轮金库、BTC 大跌禁止新多

默认 **纸上**。没有密钥、没有 `live: true` 不会碰真金。

## 跑起来

```bash
python -m alpha_sniper design
python -m alpha_sniper paper --days 40 --seed 42
python -m unittest alpha_sniper.tests.test_sniper
```

纸上宇宙里种了缩簧暴涨、单独放量假突破、抛物线解锁大跌、叙事滞后、BTC 压力日假点火。用来打门控，不是用来吹回测。
