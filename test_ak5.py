import akshare as ak
try:
    df = ak.stock_financial_abstract(symbol="600519")
    print("Sina abstract:", df.shape)
except Exception as e:
    print("Sina err:", e)
