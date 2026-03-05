from mcp.server.fastmcp import FastMCP
import pandas as pd
import json
import os
import time
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr 
import markdown 
from email.header import Header
from datetime import date, timedelta
from functools import wraps
import requests
import requests.utils
import urllib.request


for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "ALL_PROXY", "all_proxy", "REQUESTS_CA_BUNDLE"]:
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
requests.utils.getproxies = lambda: {}
requests.utils.get_environ_proxies = lambda *a, **kw: {}
urllib.request.getproxies = lambda: {}


import akshare as ak
from dotenv import load_dotenv

load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = "smtp.163.com"
SMTP_PORT = 465

mcp = FastMCP("Finance-Data-Server")



def ttl_cache(ttl_seconds):
    def decorator(func):
        cache = {}
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = str(args) + str(sorted(kwargs.items()))
            if key in cache:
                result, ts = cache[key]
                if time.time() - ts < ttl_seconds:
                    return result
            result = func(*args, **kwargs)
            cache[key] = (result, time.time())
            return result
        return wrapper
    return decorator



@ttl_cache(ttl_seconds=120)
def _a_individual_info(symbol: str):
    return ak.stock_individual_info_em(symbol=symbol)

@ttl_cache(ttl_seconds=300)
def _a_hist(symbol: str, start: str, end: str):
    return ak.stock_zh_a_hist(symbol=symbol, period="daily",
                              start_date=start, end_date=end, adjust="")

@ttl_cache(ttl_seconds=3600)
def _a_financial(symbol: str):
    return ak.stock_financial_abstract(symbol=symbol)

@ttl_cache(ttl_seconds=3600)
def _hk_basic_info(symbol: str):
    return ak.stock_individual_basic_info_hk_xq(symbol=symbol)

@ttl_cache(ttl_seconds=3600)
def _hk_financial(symbol: str):
    return ak.stock_financial_hk_analysis_indicator_em(symbol=symbol)




@mcp.tool()
def get_stock_spot(symbol: str, market: str = "A") -> str:
    """
    获取股票当前行情（最新价、涨跌幅、股票简称等）。
    使用个股直连接口，不拉取全市场数据，速度快。

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
        else:
            df = _a_individual_info(symbol)
            info = dict(zip(df["item"], df["value"]))
            return json.dumps(info, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"获取行情失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def get_stock_history(symbol: str, days: int = 30) -> str:
    """
    获取 A 股个股近期历史日 K 线数据，包含收盘价、涨跌幅、成交量等。
    仅支持 A 股。港股历史数据请说明暂不支持。

    参数:
        symbol: A 股股票代码，6 位数字（如 '002594'）
        days:   向前取多少天的数据，默认 30 天
    """
    try:
        end_date = date.today().strftime("%Y%m%d")
        start_date = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
        df = _a_hist(symbol, start_date, end_date)
        if df.empty:
            return json.dumps({"error": f"未找到 {symbol} 的历史数据"}, ensure_ascii=False)
        return df.to_json(orient="records", force_ascii=False, date_format="iso")
    except Exception as e:
        return json.dumps({"error": f"获取历史行情失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def get_financial_indicators(symbol: str, market: str = "A") -> str:
    """
    获取上市公司核心财务指标（总营收、净利润、毛利率、ROE 等），近 3 期报告期数据。

    参数:
        symbol: 股票代码。A股6位（如 '002594'），港股5位（如 '01810'）
        market: "A" 代表 A 股，"HK" 代表港股
    """
    try:
        if market == "HK":
            symbol = symbol.zfill(5)
            df = _hk_financial(symbol)
            if df.empty:
                return json.dumps({"error": f"未找到港股 {symbol} 的财务数据"}, ensure_ascii=False)
            return json.dumps(df.head(3).to_dict(orient="records"),
                              ensure_ascii=False, default=str)
        else:
            df = _a_financial(symbol)
            if df.empty:
                return json.dumps({"error": f"未找到 A 股 {symbol} 的财务数据"}, ensure_ascii=False)
            return json.dumps(df.head(3).to_dict(orient="records"),
                              ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"获取财务指标失败: {str(e)}"}, ensure_ascii=False)



@mcp.tool()
def send_email(to_address: str, subject: str, content: str) -> str:
    """
    发送排版精美的 HTML 邮件给指定的收件人。
    当用户要求发送报告时调用此工具。
    """
    try:

        html_content = markdown.markdown(content, extensions=['tables', 'fenced_code'])
        

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


        message = MIMEText(beautiful_html, 'html', 'utf-8')

        message['From'] = formataddr((str(Header("AI 投研大脑", 'utf-8')), SENDER_EMAIL))
        message['To'] = to_address
        message['Subject'] = Header(subject, 'utf-8')


        smtp_obj = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        smtp_obj.login(SENDER_EMAIL, SENDER_PASSWORD)
        smtp_obj.sendmail(SENDER_EMAIL, [to_address], message.as_string())
        smtp_obj.quit()
        
        return f"✅ 成功！排版精美的研报已发送至 {to_address}。"
        
    except Exception as e:
        return f"❌ 邮件发送失败: {str(e)}"


if __name__ == "__main__":
    mcp.run()