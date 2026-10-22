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

開啟 http://127.0.0.1:8000/ 會導向登入頁；後台管理在 http://127.0.0.1:8000/manage/ 。
Django 內建的 http://127.0.0.1:8000/admin/ 只留給超級使用者緊急備用，平常不使用。

> 使用 PyMySQL 連線 MySQL，純 Python 實作，Windows 上不需要編譯工具。

## 帳號與權限

- 登入帳號為工號，不開放自行註冊，由後台管理的「系統帳號」建立；必須先有「人員資料」，建立帳號時選人員，工號、姓名、電話、部門都取自人員資料（之後到人員資料修改會同步）。
- 職級（員工、組長、主任、經理、管理員）決定能做多少；部門決定看得到哪些頁面。
- 頁面權限在後台的「頁面權限」設定（最低職級、開放部門），只有管理員能改。沒設定過的頁面只有管理員能進。
- 非管理員管理帳號時，只看得到、也只能設定比自己低的職級。
- 新功能頁用 `PageAccessMixin` 或 `page_access_required("頁面代碼")` 套用。

## 人員資料

- 人員資料和系統帳號分開：不是每個人都有帳號，需要操作系統的人才另外開帳號（在「系統帳號」選人員建立，不能憑空建立帳號）。
- 人員記錄應徵進來的「職務」；每天實際站的工位可能不同，之後在到班登記記錄。
- 離職請取消「在職」，不要刪除。
- 本機測試資料：`python manage.py seed_personnel` 產生 15 位假人員（工號 T001–T015，可加 `--count 數量`），只填工號、姓名、手機、到職日，不建立部門、職務、工位，也不建立系統帳號；重複執行不會重複建立。

## 到班登記

- 網址 `/attendance/`：選日期與部門，整批登記每個人的狀態（到班／請假／缺勤）、上下班時間、當日工位。
- 經理以上可登記所有部門；組長、主任只能登記自己的部門；員工不能使用。
- 當天的紀錄由登記人自己修改；之前日期的紀錄要主任以上才能新增或修改；不能登記未來日期。
- 到班人數 `/attendance/headcount/`：依日期看各部門在職、到班、請假、缺勤、未登記人數，以及到班人員所在工位。
- 工位安排 `/attendance/stations/`：先登記到班，再到這頁替「到班」的人手動安排當日工位（任何工位都可選，不限制職務；系統不自動建議，也還沒有各工位需求人數）。改完會先列出「原工位 → 新工位」，按「確認修改」才批次儲存。不鎖定：當天可隨時改，之前日期要主任以上，不能安排未來日期。到班登記頁的工位欄位只顯示。經理以上可安排所有部門，其他人只能安排自己的部門。
- 三個頁面都要先在「頁面權限」開放（頁面代碼 `attendance-register`、`attendance-headcount`、`attendance-stations`）。

## 後台管理（自建，不依賴 Django admin）

- `apps/backoffice/`：後台首頁與共用 view（`ManageListView`、`ManageCreateView`、`ManageUpdateView`、`ManageDeleteView`）與共用 template。
- 新增後台頁面：在 `apps/backoffice/menu.py` 的 `MENU` 加一筆，再寫繼承上述類別的 view（設定 `model`、`form_class`、`page_key`、`columns`…），可參考 `apps/personnel/views.py`。
- 執行測試（不需要 MySQL）：`$env:DB_ENGINE="sqlite"; python manage.py test`

## 專案結構

- `apps/`：所有功能模組（Django app）都放在這裡，新增 app 用 `python manage.py startapp 名稱 apps/名稱`；建立後把 `apps.py` 的 `name` 改成 `apps.名稱`，並加進 `INSTALLED_APPS`
  - `apps/accounts/`：使用者、部門、工位、頁面權限
  - `apps/backoffice/`：自建後台的首頁、選單與共用 view
  - `apps/personnel/`：人員資料、職務
  - `apps/attendance/`：每日到班登記、到班人數
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
