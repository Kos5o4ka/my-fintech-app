import requests

def get_moex_bond(query):
    query = query.strip().upper()
    try:
        search_url = f"https://iss.moex.com/iss/securities.json?q={query}"
        search_res = requests.get(search_url, timeout=5).json()
        
        if not search_res.get('securities') or not search_res['securities']['data']:
            return None
            
        sec_cols = search_res['securities']['columns']
        sec_data = search_res['securities']['data'][0]
        secid = sec_data[sec_cols.index('secid')]
        
        url = f"https://iss.moex.com/iss/engines/stock/markets/bonds/securities/{secid}.json"
        res = requests.get(url, timeout=5).json()
        
        if not res.get('securities') or not res['securities']['data']:
            return None

        sec_cols = res['securities']['columns']
        sec_data = res['securities']['data'][0]
        mkt_cols = res['marketdata']['columns']
        mkt_data = res['marketdata']['data'][0] if res['marketdata']['data'] else []

        def get_val(data, cols, name):
            if not data or name not in cols: return None
            return data[cols.index(name)]

        facevalue = get_val(sec_data, sec_cols, 'FACEVALUE') or 1000
        last_pct = get_val(mkt_data, mkt_cols, 'LAST') or get_val(sec_data, sec_cols, 'PREVPRICE')
        if not last_pct: last_pct = 100 

        price_rub = (last_pct / 100) * facevalue
        nkd = get_val(sec_data, sec_cols, 'ACCRUEDINT') or 0
        coupon = get_val(sec_data, sec_cols, 'COUPONVALUE') or 0

        return {
            'secid': secid,
            'name': get_val(sec_data, sec_cols, 'SHORTNAME'),
            'price': round(price_rub, 2),
            'nkd': round(nkd, 2),
            'coupon': coupon
        }
    except Exception as e:
        print("Ошибка MOEX API:", e)
        return None