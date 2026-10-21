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

```powershell
# 6. 建立第一個管理員（工號即帳號）
python manage.py createsuperuser
```

開啟 http://127.0.0.1:8000/ 會導向登入頁；管理後台在 http://127.0.0.1:8000/admin/ 。

> 使用 PyMySQL 連線 MySQL，純 Python 實作，Windows 上不需要編譯工具。

## 帳號與權限

- 登入帳號為工號，不開放自行註冊，由管理員在 admin 建立。
- 職級（員工、組長、主任、經理、管理員）決定能做多少；部門決定看得到哪些頁面。
- 頁面權限在 admin 的「頁面權限」設定（最低職級、開放部門），新功能頁用 `PageAccessMixin` 或 `page_access_required("頁面代碼")` 套用。
- 執行測試（不需要 MySQL）：`$env:DB_ENGINE="sqlite"; python manage.py test`

## 專案結構

- `apps/`：所有功能模組（Django app）都放在這裡，新增 app 用 `python manage.py startapp 名稱 apps/名稱`；建立後把 `apps.py` 的 `name` 改成 `apps.名稱`，並加進 `INSTALLED_APPS`
  - `apps/accounts/`：使用者、部門、工位、頁面權限
- `config/`：Django 設定（資料庫等設定皆由 `.env` 讀取）
- `templates/`：全站共用 template
  - `base.html`：共用骨架（導覽列、訊息、`title` / `heading` / `content` / `extra_css` / `extra_js` 區塊）
  - `components/`：可用 `{% include %}` 的共用元件（`_table`、`_pagination`、`_form`、`_form_field`、`_messages`、`_navbar`）
- `static/`：全站共用靜態檔（`css/base.css`、`js/base.js`、`img/`）
- `requirements.txt`：套件清單
- `.env.example`：環境變數範本（`.env` 不會被提交）

## 新增 app 時的 template 慣例

- app 的 template 放在 `apps/<app>/templates/<app>/`，並以 app 名稱當子資料夾避免檔名衝突，例如 `apps/inventory/templates/inventory/item_list.html`。
- 每個頁面開頭 `{% extends "base.html" %}`，填入 `title`、`heading`、`content` 區塊。
- app 專屬的 CSS/JS 放在 `apps/<app>/static/<app>/`，用 `extra_css` / `extra_js` 區塊載入。
- 共用元件範例：`{% include "components/_pagination.html" %}`、`{% include "components/_form.html" with form=form %}`。
- 新 app 的連結請加進 `templates/components/_navbar.html`。
