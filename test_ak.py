import akshare as ak
try:
    df = ak.stock_financial_analysis_indicator(symbol="sh600519")
    print(df.head(1).to_dict())
except Exception as e:
    print("ERROR:", e)

try:
    df2 = ak.stock_hk_spot_em()
    print("HK Spot ok", df2.shape)
except Exception as e:
    print("ERROR2:", e)
