import os
import gspread
from google.oauth2.service_account import Credentials
import threading
import time

# ========== アップロード時スプレッドシート追加 ==========
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

# ===== キャッシュ管理（出力結果） =====
_output_sheet_cache = {
    "data_main": None,
    "data_import": None,
    "timestamp": 0
}
CACHE_LIFETIME = 60 * 60 * 24 * 365 * 10  # 実質無限に近く（強制更新だけ）

def _fetch_output_sheet_records():
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
    return all_records_main, all_records_import

def refresh_output_sheet_cache():
    global _output_sheet_cache
    print("出力結果シートのキャッシュを更新します...")
    try:
        main, imp = _fetch_output_sheet_records()
        _output_sheet_cache = {
            "data_main": main,
            "data_import": imp,
            "timestamp": time.time()
        }
        print(f"キャッシュ更新完了（限定:{len(main)}件／一般:{len(imp)}件）")
    except Exception as e:
        print(f"出力結果シートキャッシュの更新失敗: {e}")
        # 失敗時は古いキャッシュで続行

def get_output_sheet_cache():
    global _output_sheet_cache
    # 必要ならタイムスタンプで自動更新も可
    if _output_sheet_cache["data_main"] is None or _output_sheet_cache["data_import"] is None:
        refresh_output_sheet_cache()
    return _output_sheet_cache

# ========== キャラデータ（STRIKER/SPECIAL）6時間キャッシュ ==========
_CHAR_CACHE_LIFETIME = 6 * 60 * 60  # 6時間（秒）

_striker_cache = {
    "data": None,
    "timestamp": 0
}
_special_cache = {
    "data": None,
    "timestamp": 0
}

def _update_striker_cache():
    global _striker_cache
    try:
        print("STRIKERキャッシュを更新します...")
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
        _striker_cache = {
            "data": char_list,
            "timestamp": time.time()
        }
        print(f"STRIKERキャッシュ更新完了（{len(char_list)}件）")
    except Exception as e:
        print(f"STRIKERキャッシュ更新失敗: {e}")

def _update_special_cache():
    global _special_cache
    try:
        print("SPECIALキャッシュを更新します...")
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
        _special_cache = {
            "data": char_list,
            "timestamp": time.time()
        }
        print(f"SPECIALキャッシュ更新完了（{len(char_list)}件）")
    except Exception as e:
        print(f"SPECIALキャッシュ更新失敗: {e}")

def get_striker_list_from_sheet():
    global _striker_cache
    now = time.time()
    if (_striker_cache["data"] is None) or (now - _striker_cache["timestamp"] > _CHAR_CACHE_LIFETIME):
        _update_striker_cache()
    return _striker_cache["data"] or []

def get_special_list_from_sheet():
    global _special_cache
    now = time.time()
    if (_special_cache["data"] is None) or (now - _special_cache["timestamp"] > _CHAR_CACHE_LIFETIME):
        _update_special_cache()
    return _special_cache["data"] or []

# サーバー起動時に初回キャッシュ取得
_update_striker_cache()
_update_special_cache()

# バックグラウンドで6時間ごとに自動更新
def char_cache_scheduler():
    while True:
        time.sleep(_CHAR_CACHE_LIFETIME)
        _update_striker_cache()
        _update_special_cache()

threading.Thread(target=char_cache_scheduler, daemon=True).start()

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

# ========== キャッシュ参照での検索 ==========

def search_battlelog_output_sheet(query, search_side):
    # キャッシュ参照
    cache = get_output_sheet_cache()
    all_records_main = cache["data_main"] or []
    all_records_import = cache["data_import"] or []

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
