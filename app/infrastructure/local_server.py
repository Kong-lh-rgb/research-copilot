from mcp.server.fastmcp import FastMCP
import pandas as pd
import json
import os
import time
import smtplib
import ssl
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


# ─── MCP 工具：股票筛选 (选股) ──────────────────────────────────────────────────

@mcp.tool()
def screen_stocks(
    max_price: float = None,
    min_price: float = None,
    max_pe: float = None,
    min_pe: float = None,
    max_pb: float = None,
    min_pb: float = None,
    limit: int = 20
) -> str:
    """
    根据条件筛选符合要求的A股股票池（基于AkShare提供的实时行情指标）。
    非常适合用于“寻找低价股”、“寻找低估值(PE/PB)股票”等需求。

    参数:
        max_price: 最高股价 (元)，例如 5.0 表示查找5元以下的低价股
        min_price: 最低股价 (元)
        max_pe: 最高市盈率 (PE, 动), 例如 30.0 表示剔除高估值
        min_pe: 最低市盈率, 如果要剔除亏损股可以设为 0.01
        max_pb: 最高市净率 (PB)
        min_pb: 最低市净率
        limit: 返回的股票数量上限，默认 20 只
    """
    try:
        import akshare as ak
        import datetime
        
        # 获取最新的A股所有股票实时行情
        # 这个接口包含 最新价、市盈率-动态、市净率等字段
        df = ak.stock_zh_a_spot_em()
        
        if df is None or df.empty:
            return json.dumps({"error": "未能获取到实时板块数据，请稍后再试。"}, ensure_ascii=False)
            
        # 字段映射方便处理
        # 东方财富实时接口字段: 
        # '代码', '名称', '最新价', '涨跌额', '涨跌幅', '成交量', '成交额', '振幅', '最高', '最低', '今开', '昨收', '量比', '换手率', '市盈率-动态', '市净率', '总市值', '流通市值'
        
        # 清洗数据，将 "-" 转为空值并转为数字
        df['最新价'] = pd.to_numeric(df['最新价'], errors='coerce')
        df['市盈率-动态'] = pd.to_numeric(df['市盈率-动态'], errors='coerce')
        df['市净率'] = pd.to_numeric(df['市净率'], errors='coerce')
        df['总市值'] = pd.to_numeric(df['总市值'], errors='coerce')
        
        target_date = datetime.date.today().strftime("%Y%m%d")
        
        # 依次应用筛选条件
        if max_price is not None:
            df = df[df['最新价'] <= max_price]
        if min_price is not None:
            df = df[df['最新价'] >= min_price]
            
        if max_pe is not None:
            df = df[df['市盈率-动态'] <= max_pe]
        if min_pe is not None:
            df = df[df['市盈率-动态'] >= min_pe]
            
        if max_pb is not None:
            df = df[df['市净率'] <= max_pb]
        if min_pb is not None:
            df = df[df['市净率'] >= min_pb]
            
        # 按市值从大到小排序，优先返回大盘股 (排除没有市值的退市股)
        df = df.dropna(subset=['总市值'])
        df = df.sort_values(by="总市值", ascending=False)
        
        # 截取结果
        result_df = df.head(limit).copy()
        
        if result_df.empty:
            return json.dumps({"message": "没有找到符合条件的股票。"}, ensure_ascii=False)
            
        result_df = result_df.fillna("")
        result_df = result_df.rename(columns={
            "代码": "股票代码",
            "名称": "股票名称"
        })
        
        # 计算 TS代码 格式
        def _to_ts_code(code):
            c = str(code)
            if c.startswith(('6', '9')): return f"{c}.SH"
            if c.startswith(('8', '4')): return f"{c}.BJ"
            return f"{c}.SZ"
            
        result_df['TS代码'] = result_df['股票代码'].apply(_to_ts_code)
        # 将市值转为万元单位以便配合之前的结构(akshare原本单位是元)
        result_df['总市值(万元)'] = (pd.to_numeric(result_df['总市值'], errors='coerce') / 10000).round(2)
        result_df['动态市盈率PE'] = result_df['市盈率-动态']
        result_df['市净率PB'] = result_df['市净率']
        
        # 只取需要的列
        cols = ["股票代码", "股票名称", "最新价", "动态市盈率PE", "市净率PB", "总市值(万元)", "TS代码"]
        # 给“最新价”重命名为“最新收盘价”保持兼容
        result_df = result_df.rename(columns={"最新价": "最新收盘价"})
        cols = ["股票代码", "股票名称", "最新收盘价", "动态市盈率PE", "市净率PB", "总市值(万元)", "TS代码"]
        
        rows = result_df[cols].to_dict(orient="records")
        
        return json.dumps({
            "count": len(rows),
            "date": target_date,
            "stocks": rows
        }, ensure_ascii=False, default=str)
        
    except Exception as e:
        return json.dumps({"error": f"筛选股票池失败: {str(e)}"}, ensure_ascii=False)

# 邮件 HTML 外壳样式
_EMAIL_CSS = """
    body  { font-family: 'Helvetica Neue', Arial, sans-serif; line-height: 1.6;
            color: #333; max-width: 860px; margin: 0 auto; padding: 24px; }
    h1, h2, h3 { color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 8px; }
    table { border-collapse: collapse; width: 100%; margin: 20px 0; font-size: 14px; }
    th, td { border: 1px solid #ddd; padding: 10px 12px; text-align: left; }
    th    { background: #f8f9fa; font-weight: bold; }
    tr:nth-child(even) { background: #f9f9f9; }
    code  { background: #f4f4f4; padding: 2px 5px; border-radius: 4px; font-size: 13px; }
    pre   { background: #f4f4f4; padding: 12px; border-radius: 6px; overflow-x: auto; }
    blockquote { border-left: 4px solid #ccc; margin: 0; padding-left: 16px; color: #666; }
    .footer { margin-top: 40px; font-size: 12px; color: #999; border-top: 1px solid #eee;
              padding-top: 12px; }
"""


def _render_email_html(markdown_body: str) -> str:
    """将 Markdown 正文渲染为完整的 HTML 邮件文档。"""
    html_body = markdown.markdown(markdown_body, extensions=["tables", "fenced_code"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <style>{_EMAIL_CSS}</style>
</head>
<body>
{html_body}
<div class="footer">由 AI 投研助手自动生成</div>
</body>
</html>"""


def _smtp_send(to_address: str, subject: str, html: str) -> None:
    """建立 SMTP_SSL 连接并发送 HTML 邮件，失败时抛出异常。"""
    if not SENDER_EMAIL:
        raise ValueError("未配置 SENDER_EMAIL，请在 .env 中设置发件人邮箱地址")
    if not SENDER_PASSWORD:
        raise ValueError("未配置 SENDER_PASSWORD，请在 .env 中设置邮箱 SMTP 授权码")

    msg = MIMEText(html, "html", "utf-8")
    msg["From"]    = formataddr((str(Header("AI 投研助手", "utf-8")), SENDER_EMAIL))
    msg["To"]      = to_address
    msg["Subject"] = Header(subject, "utf-8")

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT,
                          context=ssl.create_default_context(),
                          timeout=30) as smtp:
        smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
        smtp.sendmail(SENDER_EMAIL, [to_address], msg.as_string())


# ─── MCP 工具：发送邮件 ────────────────────────────────────────────────────────

@mcp.tool()
def send_email(to_address: str, subject: str, content: str) -> str:
    """
    将 Markdown 格式的研报内容渲染为 HTML 邮件并发送给指定收件人。
    当用户要求发送报告或分析结果时调用此工具。

    Args:
        to_address: 收件人邮箱地址
        subject:    邮件主题
        content:    邮件正文（Markdown 格式）
    """
    try:
        _smtp_send(to_address, subject, _render_email_html(content))
        return f"✅ 邮件已发送至 {to_address}。"
    except Exception as e:
        return f"❌ 邮件发送失败: {e}"


if __name__ == "__main__":
    mcp.run()