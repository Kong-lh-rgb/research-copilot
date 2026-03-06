from mcp.server.fastmcp import FastMCP
import pandas as pd
import json
import os
import time
import smtplib
import http.client
from email.mime.text import MIMEText
from email.utils import formataddr
import markdown
from email.header import Header
from datetime import date, timedelta
from functools import wraps
from io import StringIO
import requests

from dotenv import load_dotenv
load_dotenv()

# 强制绕过系统代理（macOS 会自动读取系统代理，导致请求失败）
PROXY_BYPASS = {"http": None, "https": None}

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = "smtp.163.com"
SMTP_PORT = 465

mcp = FastMCP("Finance-Data-Server")

# ─── 通用工具 ─────────────────────────────────────────────────────────────────

def ttl_cache(ttl_seconds):
    def decorator(func):
        cache = {}
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = str(args) + str(sorted(kwargs.items()))
            if key in cache:
                result, ts_val = cache[key]
                if time.time() - ts_val < ttl_seconds:
                    return result
            result = func(*args, **kwargs)
            cache[key] = (result, time.time())
            return result
        return wrapper
    return decorator


_HEADERS_TENCENT = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.qq.com",
}
_HEADERS_SINA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://vip.stock.finance.sina.com.cn",
}


def _stock_prefix(symbol: str) -> str:
    """根据股票代码返回 sh/sz/bj 前缀"""
    s = symbol.strip()
    if s.startswith("6"):
        return "sh"
    if s.startswith(("8", "4")):
        return "bj"
    return "sz"


# ─── 腾讯：实时行情 ────────────────────────────────────────────────────────────

@ttl_cache(ttl_seconds=60)
def _tencent_spot(symbol: str) -> dict:
    prefix = _stock_prefix(symbol)
    r = requests.get(
        f"http://qt.gtimg.cn/q={prefix}{symbol}",
        headers=_HEADERS_TENCENT,
        proxies=PROXY_BYPASS,
        timeout=8,
    )
    r.encoding = "gbk"
    parts = r.text.split("~")
    if len(parts) < 50:
        raise ValueError(f"腾讯返回数据字段不足: {r.text[:120]}")
    return {
        "名称": parts[1],
        "代码": parts[2],
        "当前价": parts[3],
        "昨收": parts[4],
        "今开": parts[5],
        "成交量(手)": parts[6],
        "涨跌额": parts[31],
        "涨跌幅%": parts[32],
        "最高": parts[33],
        "最低": parts[34],
        "换手率%": parts[38],
        "动态PE": parts[39],
        "振幅%": parts[43],
        "流通市值(亿)": parts[44],
        "总市值(亿)": parts[45],
        "市净率PB": parts[46],
        "52周最高": parts[47],
        "52周最低": parts[48],
        "量比": parts[49],
        "更新时间": parts[30],
    }


# ─── 腾讯：历史 K 线 ───────────────────────────────────────────────────────────

@ttl_cache(ttl_seconds=300)
def _tencent_history(symbol: str, start: str, end: str, days: int) -> list:
    """start/end 格式 YYYY-MM-DD，前复权日线"""
    prefix = _stock_prefix(symbol)
    params = {
        "_var": "kline_dayqfq",
        "param": f"{prefix}{symbol},day,{start},{end},{days},qfq",
    }
    r = requests.get(
        "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get",
        params=params,
        headers=_HEADERS_TENCENT,
        proxies=PROXY_BYPASS,
        timeout=10,
    )
    text = r.text
    json_str = text[text.index("=") + 1:]
    data = json.loads(json_str)
    raw = data.get("data", {}).get(f"{prefix}{symbol}", {}).get("qfqday", [])
    return [
        {
            "日期": row[0],
            "开盘": row[1],
            "收盘": row[2],
            "最高": row[3],
            "最低": row[4],
            "成交量": row[5],
        }
        for row in raw
    ]


# ─── 新浪：利润表（HTML 解析）─────────────────────────────────────────────────

@ttl_cache(ttl_seconds=3600)
def _sina_profit_statement(symbol: str) -> list:
    year = date.today().year
    r = requests.get(
        f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_ProfitStatement"
        f"/stockid/{symbol}/ctrl/{year}/displaytype/4.phtml",
        headers=_HEADERS_SINA,
        proxies=PROXY_BYPASS,
        timeout=12,
    )
    r.encoding = "gbk"
    tables = pd.read_html(StringIO(r.text), flavor="lxml")
    # 找含"利润"相关行的表格
    fin_table = None
    for t in tables:
        if t.shape[0] > 10 and t.shape[1] >= 5:
            cols_str = " ".join(str(c) for c in t.columns)
            if "利润" in cols_str or "收入" in cols_str or "报表" in str(t.iloc[0, 0] if len(t) else ""):
                fin_table = t
                break
    if fin_table is None and len(tables) >= 14:
        fin_table = tables[13]
    if fin_table is None:
        raise ValueError("未找到利润表")
    fin_table = fin_table.copy()
    fin_table.columns = ["指标"] + [f"期间{i}" for i in range(1, len(fin_table.columns))]
    fin_table = fin_table.dropna(subset=["指标"]).reset_index(drop=True)
    key_rows = fin_table[
        fin_table["指标"].astype(str).str.contains("营业|净利|收入|毛利|利润", na=False)
    ]
    return key_rows.head(10).to_dict(orient="records")


# ─── 港股备用（可选，依赖 akshare）─────────────────────────────────────────────

@ttl_cache(ttl_seconds=300)
def _hk_basic_info(symbol: str):
    import akshare as ak
    return ak.stock_individual_basic_info_hk_xq(symbol=symbol)


# ─── MCP 工具：实时行情 ────────────────────────────────────────────────────────

@mcp.tool()
def get_stock_spot(symbol: str, market: str = "A") -> str:
    """
    获取股票当前行情（最新价、涨跌幅、PE、PB、市值等）。

    参数:
        symbol: 股票代码。A股6位数字（如 '002594'），港股补前导零5位（如 '01810'）
        market: "A" 代表 A 股，"HK" 代表港股
    """
    try:
        if market == "HK":
            symbol = symbol.zfill(5)
            df = _hk_basic_info(symbol)
            info = dict(zip(df["item"], df["value"]))
            info["股票代码"] = symbol
            return json.dumps(info, ensure_ascii=False, default=str)
        record = _tencent_spot(symbol)
        return json.dumps(record, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"获取行情失败: {e}"}, ensure_ascii=False)


# ─── MCP 工具：历史 K 线 ───────────────────────────────────────────────────────

@mcp.tool()
def get_stock_history(symbol: str, days: int = 30) -> str:
    """
    获取 A 股个股近期历史日 K 线数据（前复权），包含开收高低价、成交量等，并生成折线图。

    参数:
        symbol: A 股股票代码，6 位数字（如 '002594'）
        days:   向前取多少天的数据，默认 30 天
    """
    try:
        end = date.today().strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = _tencent_history(symbol, start, end, days)
        if not rows:
            return json.dumps({"error": f"未找到 {symbol} 的历史数据"}, ensure_ascii=False)

        # 生成折线图
        try:
            import matplotlib.pyplot as plt
            import base64
            from io import BytesIO
            dates = [r["日期"] for r in rows]
            closes = [float(r["收盘"]) for r in rows]
            plt.figure(figsize=(6, 3))
            plt.plot(dates, closes, marker='o', color='#0072c6')
            plt.xticks(rotation=45)
            plt.title(f"{symbol} 股价走势")
            plt.tight_layout()
            buf = BytesIO()
            plt.savefig(buf, format='png')
            plt.close()
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')
            chart_url = f"data:image/png;base64,{img_base64}"
        except Exception as chart_err:
            chart_url = None

        return json.dumps({
            "history": rows,
            "chart": chart_url,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"获取历史行情失败: {e}"}, ensure_ascii=False)


# ─── MCP 工具：财务指标 ────────────────────────────────────────────────────────

@mcp.tool()
def get_financial_indicators(symbol: str, market: str = "A") -> str:
    """
    获取上市公司近期利润表核心指标（营业收入、净利润等），最近几期报告期数据。

    参数:
        symbol: 股票代码。A股6位(如 '002594'),港股5位(如 '01810')
        market: "A" 代表 A 股，"HK" 代表港股
    """
    try:
        if market == "HK":
            symbol = symbol.zfill(5)
            df = _hk_basic_info(symbol)
            info = dict(zip(df["item"], df["value"]))
            return json.dumps(info, ensure_ascii=False, default=str)
        rows = _sina_profit_statement(symbol)
        if not rows:
            return json.dumps({"error": f"未找到 A 股 {symbol} 的财务数据"}, ensure_ascii=False)
        return json.dumps(rows, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"获取财务数据失败: {e}"}, ensure_ascii=False)


# ─── MCP 工具：发送邮件 ────────────────────────────────────────────────────────

@mcp.tool()
def send_email(to_address: str, subject: str, content: str) -> str:
    """
    发送排版精美的 HTML 邮件给指定的收件人。
    当用户要求发送报告时调用此工具。
    """
    try:
        html_content = markdown.markdown(content, extensions=["tables", "fenced_code"])
        beautiful_html = f"""
        <html>
        <head>
        <style>
            body {{ font-family: 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; padding: 20px; }}
            h1, h2, h3 {{ color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 10px; }}
            table {{ border-collapse: collapse; width: 100%; margin: 20px 0; font-size: 14px; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background-color: #f8f9fa; font-weight: bold; color: #333; }}
            tr:nth-child(even) {{ background-color: #f9f9f9; }}
            code {{ background-color: #f4f4f4; padding: 2px 5px; border-radius: 4px; }}
            blockquote {{ border-left: 4px solid #ccc; margin-left: 0; padding-left: 16px; color: #666; }}
        </style>
        </head>
        <body>
        {html_content}
        </body>
        </html>
        """
        message = MIMEText(beautiful_html, "html", "utf-8")
        message["From"] = formataddr((str(Header("AI 投研大脑", "utf-8")), SENDER_EMAIL))
        message["To"] = to_address
        message["Subject"] = Header(subject, "utf-8")
        smtp_obj = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        smtp_obj.login(SENDER_EMAIL, SENDER_PASSWORD)
        smtp_obj.sendmail(SENDER_EMAIL, [to_address], message.as_string())
        smtp_obj.quit()
        return f"✅ 成功！排版精美的研报已发送至 {to_address}。"
    except Exception as e:
        return f"❌ 邮件发送失败: {str(e)}"


if __name__ == "__main__":
    mcp.run()