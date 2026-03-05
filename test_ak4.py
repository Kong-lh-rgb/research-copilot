import akshare as ak
try:
    df = ak.stock_zcfz_em(date="20230331")
    print("EM ZCFZ:", df.shape)
except Exception as e:
    print(e)
