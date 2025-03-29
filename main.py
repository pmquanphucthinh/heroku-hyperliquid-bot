import os
import asyncio
import websockets
import json
import gspread
import requests
from flask import Flask
from oauth2client.service_account import ServiceAccountCredentials

# Lấy thông tin từ Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GOOGLE_SHEET_URL = os.getenv("GOOGLE_SHEET_URL")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
PORT = int(os.getenv("PORT", 10000))  # Mặc định PORT 10000 nếu không có biến môi trường

# Kiểm tra xem các biến môi trường đã được thiết lập chưa
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not GOOGLE_SHEET_URL or not GOOGLE_CREDENTIALS_JSON:
    raise ValueError("❌ Thiếu Environment Variables cần thiết!")

# Xử lý Google Credentials từ ENV
creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open_by_url(GOOGLE_SHEET_URL).sheet1

# Flask server để tránh lỗi "No open ports detected"
app = Flask(__name__)

@app.route("/")
def home():
    return "Please contact quanphucthinh@gmail.com for more information"

# Hàm gửi tin nhắn Telegram
def send_telegram_message(user_address, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    reply_markup = json.dumps({
        "inline_keyboard": [[
            {"text": "Xem trên HypurrScan", "url": f"https://hypurrscan.io/address/{user_address}"}
        ]]
    })
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML", "reply_markup": reply_markup}
    requests.post(url, json=payload)

# Kiểm tra vị thế của user
async def check_positions(user_address):
    url = "wss://api.hyperliquid.xyz/ws"
    try:
        async with websockets.connect(url, ping_interval=30) as websocket:
            subscribe_message = {"method": "subscribe", "subscription": {"type": "webData2", "user": user_address}}
            await websocket.send(json.dumps(subscribe_message))
            
            while True:
                response = await websocket.recv()
                data = json.loads(response)

                if "channel" in data and data["channel"] == "subscriptionResponse":
                    continue

                current_positions = {}
                if "data" in data and "clearinghouseState" in data["data"]:
                    asset_positions = data["data"]["clearinghouseState"].get("assetPositions", [])
                    for asset in asset_positions:
                        position = asset.get("position", {})
                        if position:
                            coin = position.get("coin")
                            size = float(position.get("szi", 0))
                            position_type = "LONG" if size > 0 else "SHORT"
                            current_positions[coin] = position_type
                
                # Lấy dữ liệu cũ từ Google Sheets
                try:
                    cell = sheet.find(user_address)
                    row_data = sheet.row_values(cell.row)
                    old_coins = row_data[1].split(",") if len(row_data) > 1 else []
                    old_positions = row_data[2].split(",") if len(row_data) > 2 else []
                except:
                    old_coins, old_positions = [], []
                
                new_coins = list(current_positions.keys())
                new_positions = list(current_positions.values())
                
                opened_positions = [coin for coin in new_coins if coin not in old_coins]
                closed_positions = [(coin, old_positions[old_coins.index(coin)]) for coin in old_coins if coin not in new_coins]
                
                if old_coins == new_coins and old_positions == new_positions:
                    print(f"🔇 Không có thay đổi vị thế cho {user_address}. Không gửi tin nhắn.")
                    return
                
                message = f"📌 <b>Thay đổi vị thế ({user_address})</b>\n-----------------------------\n"
                for coin, position in current_positions.items():
                    symbol = "🔹" if position == "LONG" else "🔻"
                    status = "(🟢 Mở mới)" if coin in opened_positions else ""
                    message += f"{symbol} <b>{coin}USDT</b> {symbol} {status}\n   - Pos: {position}\n-----------------------------\n"
                
                for coin, old_position in closed_positions:
                    message += f"❌ <b>{coin}USDT</b> ({old_position}) đã đóng vị thế\n-----------------------------\n"

                send_telegram_message(user_address, message)
                
                # Cập nhật lại Google Sheets nếu có thay đổi
                sheet.update(range_name=f"B{cell.row}:C{cell.row}", values=[[",".join(new_coins), ",".join(new_positions)]])
                await websocket.close()
                return
    except Exception as e:
        print(f"🚨 Lỗi với {user_address}: {e}")

# Chạy vòng lặp kiểm tra
async def main():
    while True:
        user_data = sheet.get_all_records()
        user_addresses = [user["User_address"] for user in user_data]
        
        for user_address in user_addresses:
            print(f"🔍 Kiểm tra vị thế: {user_address}")
            await check_positions(user_address)
            await asyncio.sleep(5)
        
        print("🔄 Hoàn thành vòng kiểm tra, bắt đầu lại sau 10 giây...")
        await asyncio.sleep(10)

# Chạy song song Flask và WebSocket
def start_async_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())

if __name__ == "__main__":
    from threading import Thread
    worker_thread = Thread(target=start_async_loop)
    worker_thread.start()
    app.run(host="0.0.0.0", port=PORT)
