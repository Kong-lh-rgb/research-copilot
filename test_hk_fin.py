import akshare as ak
try:
    df = ak.stock_financial_hk_analysis_indicator_em(symbol="01810")
    print("HK indicator EM:", df.shape)
    print(df.head(1).columns)
except Exception as e:
    print("Err EM:", e)
