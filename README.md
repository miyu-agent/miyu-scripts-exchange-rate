# 汇率查询

Miyu 脚本包，带一件工具 `exchange_rate`：按最新汇率换算金额，也能查过去某天的汇率。

- 主源 [Frankfurter](https://frankfurter.dev)（v2 接口，各国央行公布的汇率，160 多种货币，有历史汇率，免密钥、不要求署名）。
- 兜底 [ExchangeRate-API](https://www.exchangerate-api.com) 的免费接口 open.er-api.com：Frankfurter 连不上、或缺某种货币时才问它，只有最新汇率；它要求注明来源，用到时输出里会写上。

## 参数

| 参数 | 说明 |
|---|---|
| `base` | 必写。从哪种货币换：ISO 4217 代码（USD）或常见中文名（美元、日元、港币……） |
| `target` | 必写。换成哪种，可以写几种，用逗号隔开：`日元,欧元,CNY` |
| `amount` | 金额，默认 1 |
| `date` | 查哪天的汇率，`YYYY-MM-DD`；不写是最新的。只走 Frankfurter，周末、假日给的是之前最近一次公布的 |
| `format` | `md`（默认）或 `json` |

## 注意

- 只用 Python 标准库。汇率表放在 `MIYU_SCRIPT_CACHE_DIR`：最新的缓存 1 小时，过去某天的不会再变，一直用缓存。
- 每一行写明汇率日期和实际用的是哪个源（`json` 里是每行的 `date`、`source`）。Frankfurter 的日期是各央行公布的生效日，可能比本地日期早一天或晚一天。
- 是参考汇率，不是银行牌价。
- 不支持加密货币。
