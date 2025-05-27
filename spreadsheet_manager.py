import os
import gspread
from google.oauth2.service_account import Credentials

def update_spreadsheet(data):
    """
    スプレッドシートに認識結果を記録（常に3行目に追加）
    """
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        raise Exception("GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.")
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    SPREADSHEET_ID = os.environ.get("BATTLELOG_SHEET_ID")
    if not SPREADSHEET_ID:
        raise Exception("BATTLELOG_SHEET_ID environment variable is not set.")
    worksheet = client.open_by_key(SPREADSHEET_ID).worksheet("戦闘ログ")
    worksheet.insert_row(data, 3)
    print("スプレッドシートを更新しました:", data)

def get_striker_list_from_sheet():
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        raise Exception("GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.")
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    SPREADSHEET_ID = os.environ.get("CHARDATA_SHEET_ID")
    if not SPREADSHEET_ID:
        raise Exception("CHARDATA_SHEET_ID environment variable is not set.")
    worksheet = client.open_by_key(SPREADSHEET_ID).worksheet("STRIKER")
    records = worksheet.get_all_records()
    char_list = []
    for row in records:
        name = row.get("キャラ名")
        icon_url = row.get("アイコン")
        if name and icon_url:
            char_list.append({"name": name, "image": icon_url})
    return char_list

def get_special_list_from_sheet():
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        raise Exception("GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.")
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    SPREADSHEET_ID = os.environ.get("CHARDATA_SHEET_ID")
    if not SPREADSHEET_ID:
        raise Exception("CHARDATA_SHEET_ID environment variable is not set.")
    worksheet = client.open_by_key(SPREADSHEET_ID).worksheet("SPECIAL")
    records = worksheet.get_all_records()
    char_list = []
    for row in records:
        name = row.get("キャラ名")
        icon_url = row.get("アイコン")
        if name and icon_url:
            char_list.append({"name": name, "image": icon_url})
    return char_list

# ========== その他アイコンのキャッシュ ==========
_OTHER_ICON_SPREADSHEET_ID = os.environ.get("CHARDATA_SHEET_ID")
_OTHER_ICON_SHEET = "その他アイコン"
_other_icon_cache = {}

def load_other_icon_cache():
    global _other_icon_cache
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        raise Exception("GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.")
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    ws = client.open_by_key(_OTHER_ICON_SPREADSHEET_ID).worksheet(_OTHER_ICON_SHEET)
    records = ws.get_all_records()
    cache = {}
    for row in records:
        key = row.get('種別', '').strip()
        url = row.get('アイコン', '').strip()
        if key and url:
            cache[key] = url
    _other_icon_cache = cache

def get_other_icon(key):
    return _other_icon_cache.get(key, "")

def reload_other_icon_cache():
    load_other_icon_cache()

# ========== 空欄・重複ヘッダーでも安全な取得関数 ==========
def get_sheet_records_with_empty_safe(worksheet, head_row=2):
    rows = worksheet.get_all_values()
    headers = rows[head_row - 1]
    seen = {}
    uniq_headers = []
    for h in headers:
        base = h.strip() if h.strip() else "空欄"
        count = seen.get(base, 0)
        if count > 0:
            uniq_headers.append(f"{base}_{count+1}")
        else:
            uniq_headers.append(base)
        seen[base] = count + 1

    data = []
    for row in rows[head_row:]:
        record = {}
        for idx, val in enumerate(row):
            if idx < len(uniq_headers):
                record[uniq_headers[idx]] = val
        data.append(record)
    return data

# ========== 表記ゆれを吸収して一致判定 ==========
def normalize(s):
    if s is None:
        return ""
    s = str(s)
    s = s.replace(" ", "").replace("　", "").replace("＊", "*")
    s = s.replace("（", "(").replace("）", ")").replace("(", "(").replace(")", ")")
    return s.strip()

# ========== 部分一致仕様・全部空欄禁止の検索（限定/一般のsource属性付） ==========
def search_battlelog_output_sheet(query, search_side):
    SPREADSHEET_ID = os.environ.get("OUTPUT_SHEET_ID")
    if not SPREADSHEET_ID:
        raise Exception("OUTPUT_SHEET_ID environment variable is not set.")
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_path = os.environ.get("GOOGLE_APPLICATIONS_CREDENTIALS", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    if not creds_path:
        raise Exception("GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.")
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    
    worksheet_main = client.open_by_key(SPREADSHEET_ID).worksheet("出力結果")
    worksheet_import = client.open_by_key(SPREADSHEET_ID).worksheet("一般版から転送")
    all_records_main = get_sheet_records_with_empty_safe(worksheet_main, head_row=2)
    all_records_import = get_sheet_records_with_empty_safe(worksheet_import, head_row=2)

    if search_side == "attack":
        char_cols = ["A1", "A2", "A3", "A4", "ASP1", "ASP2"]
    else:
        char_cols = ["D1", "D2", "D3", "D4", "DSP1", "DSP2"]

    query_norm = [normalize(x) for x in query]

    # 全部空欄の場合は空リスト返す
    if not any(query_norm):
        print("全枠空欄のため検索しません")
        return []

    result = []

    # --- 限定データ ---
    for row in all_records_main:
        match = True
        for i in range(4):
            if query_norm[i]:
                if normalize(row.get(char_cols[i], "")) != query_norm[i]:
                    match = False
                    break
        if not match:
            continue
        query_sp = set([q for q in query_norm[4:6] if q])
        data_sp = set([normalize(row.get(char_cols[4], "")), normalize(row.get(char_cols[5], ""))])
        if query_sp and not query_sp.issubset(data_sp):
            continue
        # ここでsource属性を付加
        row_with_source = dict(row)
        row_with_source["source"] = "限定"
        result.append(row_with_source)

    # --- 一般データ ---
    for row in all_records_import:
        match = True
        for i in range(4):
            if query_norm[i]:
                if normalize(row.get(char_cols[i], "")) != query_norm[i]:
                    match = False
                    break
        if not match:
            continue
        query_sp = set([q for q in query_norm[4:6] if q])
        data_sp = set([normalize(row.get(char_cols[4], "")), normalize(row.get(char_cols[5], ""))])
        if query_sp and not query_sp.issubset(data_sp):
            continue
        row_with_source = dict(row)
        row_with_source["source"] = "一般"
        result.append(row_with_source)

    return result
