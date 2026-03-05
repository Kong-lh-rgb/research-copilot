import akshare as ak
try:
    df1 = ak.stock_financial_analysis_indicator(symbol="600519")
    print("Without prefix:", df1.shape)
except Exception as e:
    print("ERROR without prefix:", e)

