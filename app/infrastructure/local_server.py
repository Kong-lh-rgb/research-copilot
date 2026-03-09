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
import tushare as ts

from dotenv import load_dotenv
load_dotenv()

# 强制绕过系统代理（macOS 会自动读取系统代理，导致请求失败）
PROXY_BYPASS = {"http": None, "https": None}

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = "smtp.163.com"
SMTP_PORT = 465
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()

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


def _normalize_ts_code(symbol: str) -> str:
    """Convert raw symbol (e.g. 600519) to Tushare ts_code format (e.g. 600519.SH)."""
    s = symbol.strip().upper()
    if "." in s:
        return s
    if len(s) != 6 or not s.isdigit():
        raise ValueError(f"无效 A 股代码: {symbol}")
    suffix = "SH" if s.startswith("6") else "SZ"
    return f"{s}.{suffix}"


def _get_tushare_pro_client():
    if not TUSHARE_TOKEN:
        raise ValueError("未配置 TUSHARE_TOKEN，请在 .env 中设置后重启服务")
    ts.set_token(TUSHARE_TOKEN)
    return ts.pro_api()


@ttl_cache(ttl_seconds=3600)
def _tushare_financial_report(
    symbol: str,
    report_type: str = "income",
    period: str = "latest",
    limit: int = 6,
) -> dict:
    """Fetch structured financial statement data from Tushare."""
    pro = _get_tushare_pro_client()
    ts_code = _normalize_ts_code(symbol)

    fields_map = {
        "income": "ts_code,ann_date,end_date,basic_eps,total_revenue,revenue,operate_profit,total_profit,n_income,n_income_attr_p",
        "balancesheet": "ts_code,ann_date,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int,undistr_porfit,money_cap",
        "cashflow": "ts_code,ann_date,end_date,n_cashflow_act,n_cashflow_inv_act,n_cash_flows_fnc_act,c_cash_equ_end_period",
        "fina_indicator": "ts_code,ann_date,end_date,roe,roa,grossprofit_margin,netprofit_margin,debt_to_assets,current_ratio,bps,ocfps,eps",
    }

    if report_type not in fields_map:
        raise ValueError("report_type 必须是 income/balancesheet/cashflow/fina_indicator 之一")

    fetch_limit = max(1, min(int(limit), 12))
    common_kwargs = {
        "ts_code": ts_code,
        "fields": fields_map[report_type],
        "limit": fetch_limit,
    }

    if period and period != "latest":
        period_compact = period.replace("-", "")
        if len(period_compact) != 8 or not period_compact.isdigit():
            raise ValueError("period 格式应为 YYYYMMDD 或 YYYY-MM-DD，或使用 latest")
        common_kwargs["period"] = period_compact

    if report_type == "income":
        df = pro.income(**common_kwargs)
    elif report_type == "balancesheet":
        df = pro.balancesheet(**common_kwargs)
    elif report_type == "cashflow":
        df = pro.cashflow(**common_kwargs)
    else:
        df = pro.fina_indicator(**common_kwargs)

    if df is None or df.empty:
        raise ValueError(f"Tushare 未返回 {ts_code} 的 {report_type} 数据")

    df = df.fillna("")
    rows = df.to_dict(orient="records")
    return {
        "source": "tushare",
        "ts_code": ts_code,
        "report_type": report_type,
        "period": period,
        "rows": rows,
    }


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
            import matplotlib
            import matplotlib.pyplot as plt
            import base64
            from io import BytesIO

            # ── 设置中文字体，按优先级尝试 ──────────────────────────────────
            matplotlib.rcParams['font.sans-serif'] = [
                'PingFang SC',      # macOS
                'Heiti SC',         # macOS 备选
                'Arial Unicode MS', # macOS 通用
                'WenQuanYi Micro Hei',  # Linux
                'Noto Sans CJK SC', # Linux 备选
                'DejaVu Sans',      # 最终回退（不支持中文，但不会崩溃）
            ]
            matplotlib.rcParams['axes.unicode_minus'] = False  # 修复负号显示

            dates = [r["日期"] for r in rows]
            closes = [float(r["收盘"]) for r in rows]
            fig, ax = plt.subplots(figsize=(8, 3))
            ax.plot(dates, closes, marker='o', markersize=3, color='#0072c6', linewidth=1.5)
            ax.set_xticks(range(0, len(dates), max(1, len(dates) // 8)))
            ax.set_xticklabels(dates[::max(1, len(dates) // 8)], rotation=45, ha='right', fontsize=8)
            ax.set_title(f"{symbol} 股价走势（近 {days} 个交易日）", fontsize=11)
            ax.set_ylabel("收盘价 (元)", fontsize=9)
            ax.grid(True, linestyle='--', alpha=0.5)
            fig.tight_layout()
            buf = BytesIO()
            fig.savefig(buf, format='png', dpi=120)
            plt.close(fig)
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
        # Backward-compatible behavior: map to new stable tool (income statement)
        data = _tushare_financial_report(
            symbol=symbol,
            report_type="income",
            period="latest",
            limit=6,
        )
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception as e:
        # Fallback for resilience
        try:
            rows = _sina_profit_statement(symbol)
            if rows:
                return json.dumps(
                    {
                        "source": "sina_fallback",
                        "ts_code": _normalize_ts_code(symbol),
                        "report_type": "income",
                        "period": "latest",
                        "rows": rows,
                    },
                    ensure_ascii=False,
                    default=str,
                )
        except Exception:
            pass
        return json.dumps({"error": f"获取财务数据失败: {e}"}, ensure_ascii=False)


@mcp.tool()
def get_financial_report(
    symbol: str,
    report_type: str = "income",
    period: str = "latest",
    limit: int = 6,
    market: str = "A",
) -> str:
    """
    获取上市公司财报/财务指标（稳定优先：Tushare API）。

    参数:
        symbol: 股票代码。A股6位(如 '600519')，港股5位(如 '01810')
        report_type: income / balancesheet / cashflow / fina_indicator
        period: latest 或具体报告期 YYYYMMDD(如 20241231)
        limit: 返回最近多少期（1~12）
        market: A 或 HK（HK 当前返回港股基础信息兜底）
    """
    try:
        if market == "HK":
            symbol = symbol.zfill(5)
            df = _hk_basic_info(symbol)
            info = dict(zip(df["item"], df["value"]))
            return json.dumps(
                {
                    "source": "akshare_hk_basic",
                    "symbol": symbol,
                    "report_type": report_type,
                    "period": period,
                    "rows": [info],
                },
                ensure_ascii=False,
                default=str,
            )

        data = _tushare_financial_report(
            symbol=symbol,
            report_type=report_type,
            period=period,
            limit=limit,
        )
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception as e:
        # For income reports, keep robust fallback
        if report_type == "income":
            try:
                rows = _sina_profit_statement(symbol)
                if rows:
                    return json.dumps(
                        {
                            "source": "sina_fallback",
                            "ts_code": _normalize_ts_code(symbol),
                            "report_type": report_type,
                            "period": period,
                            "rows": rows,
                        },
                        ensure_ascii=False,
                        default=str,
                    )
            except Exception:
                pass
        return json.dumps({"error": f"获取财报失败: {e}"}, ensure_ascii=False)


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