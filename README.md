# Warehouse System（倉儲系統）

使用 Python + Django + MySQL 開發，並預留網路爬蟲與機器學習／資料分析所需套件。

## 環境需求（Windows 10）

- Python 3.11 以上（安裝時勾選 "Add Python to PATH"）
- MySQL 8.x（Windows 安裝程式安裝並啟動服務）
- Git

## 建置步驟（PowerShell）

```powershell
# 1. 建立並啟用虛擬環境
python -m venv .venv
.venv\Scripts\Activate.ps1
# 若被執行原則擋下，先執行：Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 2. 安裝套件
pip install -r requirements.txt

# 3. 設定環境變數（填入你的 MySQL 帳密）
copy .env.example .env

# 4. 在 MySQL 建立資料庫（MySQL Command Line Client 內執行）
#    CREATE DATABASE warehouse CHARACTER SET utf8mb4;

# 5. 建立資料表並啟動
python manage.py migrate
python manage.py runserver
```

開啟 http://127.0.0.1:8000/ 看到 Django 歡迎頁即完成。

> 使用 PyMySQL 連線 MySQL，純 Python 實作，Windows 上不需要編譯工具。

## 專案結構

- `config/`：Django 設定（資料庫等設定皆由 `.env` 讀取）
- `requirements.txt`：套件清單
- `.env.example`：環境變數範本（`.env` 不會被提交）
