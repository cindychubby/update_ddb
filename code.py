import os
import time
import re
import logging
from datetime import datetime
import requests
import pandas as pd
from requests.adapters import HTTPAdapter, Retry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BinanceSwapClient")

# ------------------ Binance 客户端 ------------------
class BinanceSwapClient:
    BASE_URL = "https://fapi.binance.com"

    def __init__(self):
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1,
                        status_forcelist=[429,500,502,503,504],
                        allowed_methods=["GET"])
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def fetch_json(self, url):
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return True, resp.json()
        except Exception as e:
            logger.warning(f"请求出错: {e}")
            return False, {}

    def get_all_swap_symbols(self):
        url = f"{self.BASE_URL}/fapi/v1/exchangeInfo"
        ok, data = self.fetch_json(url)
        if ok and "symbols" in data:
            return [
                s["symbol"] for s in data["symbols"]
                if s["status"] == "TRADING"
                and s["symbol"].endswith("USDT")
                and s.get("contractType") == "PERPETUAL"
            ]
        return []

    def get_index_constituents(self, symbol):
        url = f"{self.BASE_URL}/fapi/v1/constituents?symbol={symbol}"
        ok, data = self.fetch_json(url)
        time.sleep(0.2)
        if ok and "constituents" in data:
            df = pd.DataFrame(data["constituents"])
            df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)
            return df
        return pd.DataFrame()

# ------------------ 交易所 symbol ------------------
def get_mexc_symbols():
    try:
        r = requests.get("https://api.mexc.com/api/v3/exchangeInfo", timeout=10).json()
        return [x["symbol"] for x in r.get("symbols",[])]
    except:
        return []

def get_bitget_symbols():
    try:
        r = requests.get("https://api.bitget.com/api/spot/v1/market/tickers", timeout=10).json()
        if r.get("code")=="00000":
            return [x["symbol"] for x in r["data"]]
        return []
    except:
        return []

SPECIAL_MAPPING = {
    "NEIROETHUSDT":"NEIROUSDT","1000RATSUSDT":"RATSUSDT","1000RATS":"RATS",
    "1000WHYUSDT":"WHYUSDT","1000WHY":"WHY","1000XUSDT":"XUSDT","1000X":"X",
    "1000000MOGUSDT":"MOGUSDT","1000000MOG":"MOG","SOONUSDT":"SOON"
}

def map_symbol(symbol, exchange):
    if symbol in SPECIAL_MAPPING:
        return SPECIAL_MAPPING[symbol]
    if exchange=="gateio":
        s = re.sub(r'^\d+', '', symbol)
        return s[:-4] if s.endswith("USDT") else s
    return symbol

# ------------------ 主处理 ------------------
def process_binance_indices():
    client = BinanceSwapClient()
    symbols = client.get_all_swap_symbols()
    logger.info(f"共 {len(symbols)} 个 USDT 永续合约")
    results = []
    for sym in symbols:
        df = client.get_index_constituents(sym)
        if df.empty: continue
        df["exchange"] = df["exchange"].str.lower()

        # cross 权重合并到 binance
        cross_mask = df["exchange"].str.startswith("binance_cross")
        if cross_mask.any():
            total_cross_weight = df.loc[cross_mask,"weight"].sum()
            df = df[~cross_mask]
            if "binance" in df["exchange"].values:
                df.loc[df["exchange"]=="binance","weight"] += total_cross_weight
            else:
                df = pd.concat([df,pd.DataFrame([{"exchange":"binance","weight":total_cross_weight}])])

        if "binance" in df["exchange"].values:
            try:
                if float(df.loc[df["exchange"]=="binance","weight"].iloc[0])>0.5:
                    continue
            except: continue

        exchanges = ["mxc","bitget"]
        weight_dict = {ex:0.0 for ex in ["binance"]+exchanges}
        cond = []
        for ex in exchanges:
            if ex in df["exchange"].values:
                w = round(float(df.loc[df["exchange"]==ex,"weight"].iloc[0]),4)
                weight_dict[ex]=w
                cond.append(w<0.1)
            else:
                cond.append(True)
        if all(cond): continue
        if "binance" in df["exchange"].values:
            weight_dict["binance"] = float(df.loc[df["exchange"]=="binance","weight"].iloc[0])
        results.append({"symbol":sym,**weight_dict})
    return pd.DataFrame(results)

if __name__=="__main__":
    os.makedirs("target_csv", exist_ok=True)
    df_mid = process_binance_indices()
    if df_mid.empty:
        logger.warning("没有符合条件的币种")
        exit()

    mexc_syms = get_mexc_symbols()
    bitget_syms = get_bitget_symbols()

    rows=[]
    for _,row in df_mid.iterrows():
        sym=row["symbol"]
        if row["mxc"]>0 and map_symbol(sym,"mxc") in mexc_syms:
            rows.append({"Exchange":"mxc","Symbol":map_symbol(sym,"mxc")})
        if row["bitget"]>0 and map_symbol(sym,"bitget") in bitget_syms:
            rows.append({"Exchange":"bitget","Symbol":map_symbol(sym,"bitget")})

    result_df=pd.DataFrame(rows)
    output_path="target_csv/output.csv"
    result_df.to_csv(output_path,index=False)
    print(f"最终 CSV 已生成: {output_path}")



