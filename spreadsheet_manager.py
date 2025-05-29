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

    # 限定データ（"出力結果"）
    worksheet_limited = client.open_by_key(SPREADSHEET_ID).worksheet("出力結果")
    records_limited = get_sheet_records_with_empty_safe(worksheet_limited, head_row=2)
    for row in records_limited:
        row["source"] = "限定"

    # 一般データ（"一般版から転送" シート名は環境によって変更してね）
    try:
        worksheet_general = client.open_by_key(SPREADSHEET_ID).worksheet("一般版から転送")
        records_general = get_sheet_records_with_empty_safe(worksheet_general, head_row=2)
        for row in records_general:
            row["source"] = "一般"
    except Exception as e:
        print(f"「一般版から転送」シート取得失敗: {e}")
        records_general = []

    # 先に限定、後に一般
    return records_limited + records_general

def refresh_output_sheet_cache():
    global _output_sheet_cache
    print("出力結果シートのキャッシュを更新します...")
    try:
        main = _fetch_output_sheet_records()
        _output_sheet_cache = {
            "data_main": main,
            "timestamp": time.time()
        }
        print(f"キャッシュ更新完了（{len(main)}件）")
    except Exception as e:
        print(f"出力結果シートキャッシュの更新失敗: {e}")

def get_output_sheet_cache():
    global _output_sheet_cache
    if _output_sheet_cache["data_main"] is None:
        refresh_output_sheet_cache()
    return _output_sheet_cache

def append_battlelog_row_from_api(row_dict, source="一般"):
    """
    API経由またはしらす式変換後に受信した「出力結果」形式データをキャッシュに追加
    """
    global _output_sheet_cache
    if _output_sheet_cache["data_main"] is None:
        refresh_output_sheet_cache()
    row_dict["source"] = source
    _output_sheet_cache["data_main"].insert(0, row_dict)
    print(f"API経由で{source}データをキャッシュに追加: {row_dict}")

def fetch_latest_output_row_as_dict():
    """
    出力結果シートの3行目（最新追加行）をdictで返す
    重複ヘッダーもユニーク化して区別できるようにする
    """
    try:
        SPREADSHEET_ID = os.environ.get("OUTPUT_SHEET_ID")
        if not SPREADSHEET_ID:
            raise Exception("OUTPUT_SHEET_ID environment variable is not set.")
        SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
        creds_path = os.environ.get("GOOGLE_APPLICATIONS_CREDENTIALS", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
        if not creds_path:
            raise Exception("GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.")
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        client = gspread.authorize(creds)
        worksheet = client.open_by_key(SPREADSHEET_ID).worksheet("出力結果")
        headers = worksheet.row_values(2)    # 2行目がヘッダー
        latest_row = worksheet.row_values(3) # 3行目が最新データ

        # --- 重複カラム名も区別してdict化する ---
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

        row_dict = {}
        for i, key in enumerate(uniq_headers):
            row_dict[key] = latest_row[i] if i < len(latest_row) else ""
        return row_dict
    except Exception as e:
        print(f"出力結果シート最新行取得失敗: {e}")
        return None

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
    cache = get_output_sheet_cache()
    all_records_main = cache["data_main"] or []

    if search_side == "attack":
        char_cols = ["A1", "A2", "A3", "A4", "ASP1", "ASP2"]
    else:
        char_cols = ["D1", "D2", "D3", "D4", "DSP1", "DSP2"]

    query_norm = [normalize(x) for x in query]
    if not any(query_norm):
        print("全枠空欄のため検索しません")
        return []

    result = []
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
        result.append(row)
    return result
