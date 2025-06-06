import os
from dotenv import load_dotenv
load_dotenv()

import sys
import unicodedata
import subprocess
from flask import Flask, request, render_template, jsonify, redirect, url_for

from spreadsheet_manager import (
    update_spreadsheet,
    get_striker_list_from_sheet,
    get_special_list_from_sheet,
    search_battlelog_output_sheet,
    get_other_icon,
    load_other_icon_cache,
    append_battlelog_row_from_api,
    fetch_latest_output_row_as_dict  # 追加
)

app = Flask(__name__)

if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    print("GOOGLE_APPLICATION_CREDENTIALS not found in environment variables.")

load_other_icon_cache()

def normalize_sp_chars(chars: list, side: str) -> list:
    if not chars or len(chars) != 6:
        return chars
    main = chars[:4]
    sp = sorted(chars[4:6])
    return main + sp

def match_team(query, target, side):
    return normalize_sp_chars(query, side) == normalize_sp_chars(target, side)

# ========== トップページ ==========
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

# ========== アップロードページ ==========
@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "GET":
        return render_template("upload.html")
    file = request.files.get("image_file")
    if not file or file.filename == "":
        return "画像ファイルが選択されていません。", 400
    uploads_dir = os.path.abspath("uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    file_path = os.path.join(uploads_dir, file.filename)
    file.save(file_path)
    try:
        from main import process_image
        row_data = process_image(file_path)
        labels = [
            "日付", "攻撃側プレイヤー", "攻撃結果",
            "攻撃キャラ1", "攻撃キャラ2", "攻撃キャラ3",
            "攻撃キャラ4", "攻撃キャラ5", "攻撃キャラ6",
            "（空白）", "防衛側プレイヤー", "防衛結果",
            "防衛キャラ1", "防衛キャラ2", "防衛キャラ3",
            "防衛キャラ4", "防衛キャラ5", "防衛キャラ6"
        ]
        return render_template(
            "confirm.html",
            row_data=row_data,
            labels=labels
        )
    except Exception as e:
        print(f"render_template失敗: {e}")
        return render_template(
            "complete.html",
            message=f"エラーが発生しました: {e}"
        )

# ========== アップロード内容確認・確定 ==========
@app.route("/upload/confirm", methods=["POST"])
def upload_confirm():
    try:
        from main import call_apps_script
        row_data = [
            request.form.get(f"field{i}", "")
            for i in range(18)
        ]
        row_data = [unicodedata.normalize("NFKC", v) for v in row_data]
        update_spreadsheet(row_data)

        subprocess.run(
            [sys.executable, "call_gas.py"],
            check=True
        )

        latest_row = fetch_latest_output_row_as_dict()
        if latest_row:
            append_battlelog_row_from_api(latest_row, source="限定")
        else:
            print("出力結果3行目の取得に失敗しました。")

        return redirect(url_for("upload_complete"))
    except subprocess.CalledProcessError as e:
        print(f"しらす式変換エラー: {e}")
        return render_template(
            "complete.html",
            message=f"しらす式変換が失敗しました: {e}"
        )
    except Exception as e:
        print(f"スプレッドシート更新エラー: {e}")
        return render_template(
            "complete.html",
            message=f"スプレッドシートの更新に失敗しました: {e}"
        )

# ========== 限定サーバーAPI：一般サーバーからのデータ受信 ==========
@app.route("/api/add_battlelog", methods=["POST"])
def api_add_battlelog():
    try:
        row_dict = request.json
        if not row_dict:
            return jsonify({"result": "error", "detail": "No data received"}), 400
        source = row_dict.get("source", "一般")
        append_battlelog_row_from_api(row_dict, source=source)
        print(f"API経由でデータ受信・追加完了: {row_dict}")
        return jsonify({"result": "ok"})
    except Exception as e:
        print(f"API追加エラー: {e}")
        return jsonify({"result": "error", "detail": str(e)}), 500

# ========== アップロード完了 ==========
@app.route("/upload/complete", methods=["GET"])
def upload_complete():
    return render_template(
        "complete.html",
        message="アップロードが完了しました"
    )

# ========== 編成検索ページ・検索実行 ==========
@app.route("/search", methods=["GET"])
def search():
    try:
        striker_list = get_striker_list_from_sheet()
        special_list = get_special_list_from_sheet()
    except Exception as e:
        print(f"キャラリスト取得エラー: {e}")
        striker_list = []
        special_list = []

    # 検索パラメータ取得
    side = request.args.get("side", "attack")
    c1 = request.args.get("c1", "")
    c2 = request.args.get("c2", "")
    c3 = request.args.get("c3", "")
    c4 = request.args.get("c4", "")
    c5 = request.args.get("c5", "")
    c6 = request.args.get("c6", "")
    only_limited = request.args.get("only_limited", "false") == "true"

    show_results = any([c1, c2, c3, c4, c5, c6])

    results = []
    if show_results:
        # API経由せずサーバーサイドでそのまま取得して渡す
        try:
            matched_rows = search_battlelog_output_sheet(
                [c1, c2, c3, c4, c5, c6], side
            )

            from datetime import datetime

            def parse_date(row):
                try:
                    return datetime.strptime(row.get("日付", ""), "%Y-%m-%d %H:%M:%S")
                except Exception:
                    return datetime.min

            matched_rows = sorted(matched_rows, key=parse_date, reverse=True)

            win_icon = get_other_icon("勝ち")
            lose_icon = get_other_icon("負け")
            attack_icon = get_other_icon("攻撃側")
            defense_icon = get_other_icon("防衛側")

            for row in matched_rows:
                if only_limited and row.get("source") != "限定":
                    continue

                if side == "attack":
                    if row.get("勝敗_2", "") != "Win":
                        continue
                    results.append({
                        "source": row.get("source", ""),
                        "winner_type": "defense",
                        "winner_icon": defense_icon,
                        "winner_winlose_icon": win_icon,
                        "winner_player": row.get("プレイヤー名_2", ""),
                        "winner_characters": [
                            row.get("D1", ""),
                            row.get("D2", ""),
                            row.get("D3", ""),
                            row.get("D4", ""),
                            row.get("DSP1", ""),
                            row.get("DSP2", ""),
                        ],
                        "loser_type": "attack",
                        "loser_icon": attack_icon,
                        "loser_winlose_icon": lose_icon,
                        "loser_player": row.get("プレイヤー名", ""),
                        "loser_characters": [
                            row.get("A1", ""),
                            row.get("A2", ""),
                            row.get("A3", ""),
                            row.get("A4", ""),
                            row.get("ASP1", ""),
                            row.get("ASP2", ""),
                        ],
                        "date": row.get("日付", ""),
                    })
                else:
                    if row.get("勝敗", "") != "Win":
                        continue
                    results.append({
                        "source": row.get("source", ""),
                        "winner_type": "attack",
                        "winner_icon": attack_icon,
                        "winner_winlose_icon": win_icon,
                        "winner_player": row.get("プレイヤー名", ""),
                        "winner_characters": [
                            row.get("A1", ""),
                            row.get("A2", ""),
                            row.get("A3", ""),
                            row.get("A4", ""),
                            row.get("ASP1", ""),
                            row.get("ASP2", ""),
                        ],
                        "loser_type": "defense",
                        "loser_icon": defense_icon,
                        "loser_winlose_icon": lose_icon,
                        "loser_player": row.get("プレイヤー名_2", ""),
                        "loser_characters": [
                            row.get("D1", ""),
                            row.get("D2", ""),
                            row.get("D3", ""),
                            row.get("D4", ""),
                            row.get("DSP1", ""),
                            row.get("DSP2", ""),
                        ],
                        "date": row.get("日付", ""),
                    })
        except Exception as e:
            print(f"限定版検索エラー: {e}")
            results = []

    return render_template(
        "db.html",
        striker_list=striker_list,
        special_list=special_list,
        results=results,
        show_results=show_results,
        side=side,
        c1=c1, c2=c2, c3=c3, c4=c4, c5=c5, c6=c6,
        only_limited=only_limited,
    )

# ========== 検索API（限定版からも将来呼ばれる場合のみ） ==========
@app.route("/api/search", methods=["POST"])
def api_search():
    try:
        from datetime import datetime

        data = request.json
        if not data:
            return jsonify({"error": "No data received"}), 400
        side = data.get("side")
        characters = data.get("characters")
        only_limited = data.get("only_limited", False)
        if side not in ["attack", "defense"] or not isinstance(characters, list) or len(characters) != 6:
            return jsonify({"error": "Invalid parameters"}), 400
        if not any(characters):
            return jsonify({"error": "検索条件を1つ以上選択してください。"}), 400

        matched_rows = search_battlelog_output_sheet(characters, side)

        def parse_date(row):
            try:
                return datetime.strptime(row.get("日付", ""), "%Y-%m-%d %H:%M:%S")
            except Exception:
                return datetime.min

        matched_rows = sorted(matched_rows, key=parse_date, reverse=True)

        response = []
        win_icon = get_other_icon("勝ち")
        lose_icon = get_other_icon("負け")
        attack_icon = get_other_icon("攻撃側")
        defense_icon = get_other_icon("防衛側")

        for row in matched_rows:
            if only_limited and row.get("source") != "限定":
                continue

            if side == "attack":
                if row.get("勝敗_2", "") != "Win":
                    continue
                response.append({
                    "source": row.get("source", ""),
                    "winner_type": "defense",
                    "winner_icon": defense_icon,
                    "winner_winlose_icon": win_icon,
                    "winner_player": row.get("プレイヤー名_2", ""),
                    "winner_characters": [
                        row.get("D1", ""),
                        row.get("D2", ""),
                        row.get("D3", ""),
                        row.get("D4", ""),
                        row.get("DSP1", ""),
                        row.get("DSP2", ""),
                    ],
                    "loser_type": "attack",
                    "loser_icon": attack_icon,
                    "loser_winlose_icon": lose_icon,
                    "loser_player": row.get("プレイヤー名", ""),
                    "loser_characters": [
                        row.get("A1", ""),
                        row.get("A2", ""),
                        row.get("A3", ""),
                        row.get("A4", ""),
                        row.get("ASP1", ""),
                        row.get("ASP2", ""),
                    ],
                    "date": row.get("日付", ""),
                })
            else:
                if row.get("勝敗", "") != "Win":
                    continue
                response.append({
                    "source": row.get("source", ""),
                    "winner_type": "attack",
                    "winner_icon": attack_icon,
                    "winner_winlose_icon": win_icon,
                    "winner_player": row.get("プレイヤー名", ""),
                    "winner_characters": [
                        row.get("A1", ""),
                        row.get("A2", ""),
                        row.get("A3", ""),
                        row.get("A4", ""),
                        row.get("ASP1", ""),
                        row.get("ASP2", ""),
                    ],
                    "loser_type": "defense",
                    "loser_icon": defense_icon,
                    "loser_winlose_icon": lose_icon,
                    "loser_player": row.get("プレイヤー名_2", ""),
                    "loser_characters": [
                        row.get("D1", ""),
                        row.get("D2", ""),
                        row.get("D3", ""),
                        row.get("D4", ""),
                        row.get("DSP1", ""),
                        row.get("DSP2", ""),
                    ],
                    "date": row.get("日付", ""),
                })
        print("API返却データ:", response)
        return jsonify({"results": response})
    except Exception as e:
        print(f"/api/search エラー: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
