import requests
from datetime import datetime


def get_moex_bond(isin_code):
    isin_code = isin_code.strip().upper()
    try:
        search_url = f"https://iss.moex.com/iss/securities.json?q={isin_code}"
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

        return {
            'secid': secid,
            'name': get_val(sec_data, sec_cols, 'SHORTNAME'),
            'price': round(price_rub, 2),
            'facevalue': facevalue,
            'nkd': round(get_val(sec_data, sec_cols, 'ACCRUEDINT') or 0, 2),
            'ytm': round(get_val(mkt_data, mkt_cols, 'DURATION_MUTATION_YIELD') or get_val(sec_data, sec_cols,
                                                                                           'YIELDTOOFFER') or 0, 2)
        }
    except Exception as e:
        print("Ошибка MOEX API:", e)
        return None


def get_bond_history_all(secid, facevalue=1000):
    labels, prices, nkd_history, ytm_history = [], [], [], []
    start_offset = 0
    try:
        while start_offset < 1000:
            url = f"https://iss.moex.com/iss/history/engines/stock/markets/bonds/securities/{secid}.json" \
                  f"?history_shares.columns=TRADEDATE,CLOSE,ACCINT,YIELDCLOSE&start={start_offset}"
            res = requests.get(url, timeout=5).json()
            if not res.get('history') or not res['history'].get('data'):
                break

            columns = res['history']['columns']
            date_idx = columns.index('TRADEDATE')
            close_idx = columns.index('CLOSE')
            accint_idx = columns.index('ACCINT')
            yield_idx = columns.index('YIELDCLOSE')

            page_data = res['history']['data']
            if not page_data:
                break

            for row in page_data:
                if row[close_idx] is not None:
                    labels.append(row[date_idx])
                    prices.append(round((float(row[close_idx]) / 100) * facevalue, 2))
                    nkd_history.append(round(float(row[accint_idx]) if row[accint_idx] else 0, 2))
                    ytm_history.append(round(float(row[yield_idx]) if row[yield_idx] else 0, 2))

            if len(page_data) < 100:
                break
            start_offset += 100
    except Exception as e:
        print(f"Ошибка пагинации MOEX ISS: {e}")
    return {"labels": labels, "data": prices, "nkd": nkd_history, "ytm": ytm_history}


def get_coupon_calendar(secid):
    try:
        url = f"https://iss.moex.com/iss/statistics/engines/stock/markets/bonds/bondization/{secid}.json"
        res = requests.get(url, timeout=5).json()
        calendar = []
        if res.get('coupons') and res['coupons'].get('data'):
            cols = res['coupons']['columns']
            for row in res['coupons']['data']:
                calendar.append({"date": row[cols.index('coupondate')], "value": row[cols.index('value')]})
        return calendar[:6]
    except:
        return []