#!/usr/bin/env python3
# Display name: Exchange rate
# 显示名称：汇率查询
# Description: Convert an amount between currencies at the latest daily exchange rate, or the rate of a past day; takes ISO codes or common Chinese currency names.
# 描述：查汇率、换算金额，也能查过去某天的汇率：ISO 代码或「美元」「日元」这样的中文名都认，汇率每天更新一次。
# Timeout: 30
# Clicall: yes
# Parameters:
# {"type": "object", "properties": {
#   "base": {"type": "string", "description": "Currency to convert from: an ISO 4217 code such as USD, or a Chinese name such as 美元."},
#   "target": {"type": "string", "description": "Currency or currencies to convert to, comma separated, such as JPY or 日元,欧元,CNY."},
#   "amount": {"type": "number", "description": "Amount in the base currency. Default 1."},
#   "date": {"type": "string", "description": "Historical rate for this day, YYYY-MM-DD (central bank rates; weekends use the last published day). Omit for the latest."},
#   "format": {"type": "string", "enum": ["md", "json"], "description": "md (default) for reading; json for code, e.g. piping miyu call into jq or python."}
# }, "required": ["base", "target"]}
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

FRANKFURTER = "https://api.frankfurter.dev/v2/rates?{query}"
ER_API = "https://open.er-api.com/v6/latest/{code}"
SOURCES = {
    "frankfurter": ("Frankfurter", "https://frankfurter.dev", "各国央行公布的汇率"),
    "er-api": ("ExchangeRate-API", "https://www.exchangerate-api.com", "Rates By Exchange Rate API"),
}
CACHE_TTL = 3600
HTTP_TIMEOUT = 15

NAMES = {
    "人民币": "CNY", "元": "CNY", "块": "CNY", "rmb": "CNY",
    "美元": "USD", "美金": "USD", "刀": "USD",
    "日元": "JPY", "日币": "JPY", "円": "JPY",
    "欧元": "EUR", "英镑": "GBP", "港币": "HKD", "港元": "HKD",
    "台币": "TWD", "新台币": "TWD", "澳门元": "MOP", "澳门币": "MOP",
    "韩元": "KRW", "韩币": "KRW", "卢布": "RUB", "俄罗斯卢布": "RUB",
    "澳元": "AUD", "澳币": "AUD", "加元": "CAD", "加币": "CAD",
    "新西兰元": "NZD", "纽币": "NZD", "瑞士法郎": "CHF", "法郎": "CHF",
    "新加坡元": "SGD", "新币": "SGD", "泰铢": "THB", "越南盾": "VND",
    "马来西亚林吉特": "MYR", "林吉特": "MYR", "马币": "MYR",
    "印尼盾": "IDR", "菲律宾比索": "PHP", "印度卢比": "INR", "卢比": "INR",
    "土耳其里拉": "TRY", "里拉": "TRY", "巴西雷亚尔": "BRL", "雷亚尔": "BRL",
    "墨西哥比索": "MXN", "阿根廷比索": "ARS", "南非兰特": "ZAR", "兰特": "ZAR",
    "瑞典克朗": "SEK", "挪威克朗": "NOK", "丹麦克朗": "DKK", "波兰兹罗提": "PLN",
    "迪拉姆": "AED", "阿联酋迪拉姆": "AED", "沙特里亚尔": "SAR",
    "乌克兰格里夫纳": "UAH", "以色列新谢克尔": "ILS", "哈萨克斯坦坚戈": "KZT",
}


class Failed(Exception):
    pass


def code_of(name):
    text = name.strip()
    if text.lower() in NAMES:
        return NAMES[text.lower()]
    if text in NAMES:
        return NAMES[text]
    if re.fullmatch(r"[A-Za-z]{3}", text):
        return text.upper()
    raise Failed(f"认不出货币「{name}」：写 ISO 4217 三位代码（如 USD、JPY），或常见中文名（如 美元、日元）")


def cache_path(name):
    root = os.environ.get("MIYU_SCRIPT_CACHE_DIR")
    return os.path.join(root, name) if root else None


def cached(name, ttl):
    path = cache_path(name)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        if ttl is None or time.time() - saved["fetched"] < ttl:
            return saved["data"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def remember(name, data):
    path = cache_path(name)
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fetched": time.time(), "data": data}, f)
        os.replace(tmp, path)
    except OSError:
        pass


def get_json(url, host):
    request = urllib.request.Request(url, headers={"User-Agent": "miyu-scripts-exchange-rate/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.load(exc).get("message") or ""
        except (ValueError, AttributeError, OSError):
            pass
        raise Failed(f"{host} 返回 HTTP {exc.code}{'：' + detail if detail else ''}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Failed(f"连不上 {host}：{getattr(exc, 'reason', exc)}")
    except ValueError:
        raise Failed(f"{host} 返回的不是 JSON")


def fetch_frankfurter(code, day):
    """一种 base 的整张表：{目标: (汇率, 汇率日期)}。day 为 None 是最新的。"""
    name = f"frankfurter-{code}-{day or 'latest'}.json"
    # 过去某天的汇率不会再变，一直用缓存；最新的缓存 1 小时。
    table = cached(name, None if day else CACHE_TTL)
    if table is None:
        query = urllib.parse.urlencode({"base": code, **({"date": day} if day else {})})
        data = get_json(FRANKFURTER.format(query=query), "api.frankfurter.dev")
        if not isinstance(data, list):
            raise Failed(f"api.frankfurter.dev 返回的格式不对：{str(data)[:200]}")
        table = {row["quote"]: [row["rate"], row["date"]] for row in data
                 if isinstance(row, dict) and "quote" in row and "rate" in row}
        if not table:
            raise Failed(f"api.frankfurter.dev 没有 {code} {day or '最新'} 的汇率")
        remember(name, table)
    return {quote: (rate, date) for quote, (rate, date) in table.items()}


def fetch_er_api(code):
    name = f"er-api-{code}.json"
    data = cached(name, CACHE_TTL)
    if data is None:
        data = get_json(ER_API.format(code=code), "open.er-api.com")
        if data.get("result") != "success":
            if data.get("error-type") == "unsupported-code":
                raise Failed(f"open.er-api.com 不认 {code} 这个货币代码")
            raise Failed(f"open.er-api.com 报错：{data.get('error-type') or data}")
        remember(name, data)
    day = time.strftime("%Y-%m-%d", time.gmtime(data.get("time_last_update_unix", 0)))
    return {quote: (rate, day) for quote, rate in (data.get("rates") or {}).items()}


def lookup(base, targets, day):
    """先问 Frankfurter；它连不上、或缺几种货币时，最新汇率再问 er-api。历史汇率只有 Frankfurter 有。"""
    found = {code: (1.0, day or time.strftime("%Y-%m-%d"), "same") for code in targets if code == base}
    errors = []
    if len(found) == len(targets):
        return found
    try:
        table = fetch_frankfurter(base, day)
        for code in targets:
            if code in table and code not in found:
                found[code] = (*table[code], "frankfurter")
    except Failed as exc:
        errors.append(str(exc))
    missing = [code for code in targets if code not in found]
    if missing and not day:
        try:
            table = fetch_er_api(base)
            for code in missing:
                if code in table:
                    found[code] = (*table[code], "er-api")
        except Failed as exc:
            errors.append(str(exc))
    missing = [code for code in targets if code not in found]
    if missing:
        reason = "；".join(errors) if errors else "汇率表里没有，检查货币代码"
        if day and not errors:
            reason = f"{day} 那天的汇率表里没有（历史汇率只有央行数据，可能是这种货币当时还没收录）"
        raise Failed(f"取不到 {base} 到 {', '.join(missing)} 的汇率：{reason}")
    return found


def fmt_number(value):
    if value == 0:
        return "0"
    if abs(value) >= 1:
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return f"{value:.6g}"


def run(args):
    base_raw = str(args.get("base") or "").strip()
    target_raw = str(args.get("target") or "").strip()
    if not base_raw or not target_raw:
        raise Failed("base 和 target 都要写，例：{\"base\":\"美元\",\"target\":\"日元\"}")
    amount = args.get("amount", 1)
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise Failed("amount 要是数字，例：100")
    fmt = args.get("format") or "md"
    if fmt not in ("md", "json"):
        raise Failed("format 只能是 md 或 json")
    base = code_of(base_raw)
    day = str(args.get("date") or "").strip() or None
    if day:
        try:
            parsed = time.strptime(day, "%Y-%m-%d")
        except ValueError:
            raise Failed("date 要写成 YYYY-MM-DD，例：2026-09-01")
        if time.mktime(parsed) > time.time():
            raise Failed(f"{day} 还没到，查不了汇率")
    targets = []
    for part in re.split(r"[,，、;；\s]+", target_raw):
        if part:
            code = code_of(part)
            if code not in targets:
                targets.append(code)
    found = lookup(base, targets, day)
    rows = [{"target": code, "rate": found[code][0], "amount": amount * found[code][0],
             "date": found[code][1], "source": found[code][2]} for code in targets]
    used = [key for key in SOURCES if any(row["source"] == key for row in rows)]
    if fmt == "json":
        return json.dumps({"base": base, "amount": amount, "results": rows,
                           "sources": {key: SOURCES[key][1] for key in used}},
                          ensure_ascii=False)
    dates = {row["date"] for row in rows if row["source"] in SOURCES}
    per_row = len(dates) > 1 or len(used) > 1
    lines = [f"{fmt_number(amount)} {base} =" if len(rows) > 1 else ""]
    for row in rows:
        conversion = f"**{fmt_number(row['amount'])} {row['target']}**"
        rate = "" if amount == 1 else f"1 {base} = {fmt_number(row['rate'])} {row['target']}"
        note = "，".join(part for part in (rate, f"{row['date']}，{SOURCES[row['source']][0] if row['source'] in SOURCES else '同一种货币'}" if per_row else "") if part)
        note = f"（{note}）" if note else ""
        lines.append(f"- {conversion}{note}" if len(rows) > 1 else f"{fmt_number(amount)} {base} = {conversion}{note}")
    credits = "；".join(f"{SOURCES[key][0]}（{SOURCES[key][2]}，{SOURCES[key][1]}）" for key in used)
    when = "" if per_row else f"汇率日期 {dates.pop()}，"
    if not used:
        return lines[-1] if len(rows) == 1 else "\n".join(line for line in lines if line)
    ahead = "（是央行公布的生效日，可能比今天晚一天）" if any(
        row["date"] > time.strftime("%Y-%m-%d") for row in rows if row["source"] in SOURCES) else ""
    lines.append(f"{when}来源 {credits}。仅供参考，不是银行牌价{ahead}")
    return "\n".join(line for line in lines if line)


def main():
    try:
        args = json.load(sys.stdin)
        if not isinstance(args, dict):
            raise Failed("参数要是一个 JSON 对象")
        print(run(args))
    except json.JSONDecodeError as exc:
        print(f"错误：参数不是 JSON：{exc}")
        sys.exit(1)
    except Failed as exc:
        print(f"错误：{exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
