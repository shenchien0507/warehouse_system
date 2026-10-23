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

- 登入帳號為工號，不開放自行註冊，由後台管理的「系統帳號」建立；必須先有「人員資料」，建立帳號時選人員，工號、姓名、聯絡資料、部門、職級都取自人員資料（之後到人員資料修改會同步）。人員資料列表上，還沒有帳號的人旁邊有「開帳號」按鈕。
- 職級由管理員在後台「職級」自訂（名稱、排序，排序只能填 1–100、不能重複，數字越大越高；預設員工 10、組長 20、主任 30、經理 40），決定能做多少；部門決定看得到哪些頁面。職級記在人員資料上。
- 「管理員」不是職級，是系統帳號上的身分（帳號編輯的「管理員」勾選，superuser 一定是管理員），只有管理員能設定，不受任何職級限制。
- 程式裡依職級判斷的操作（例如可登記全部部門、修改之前日期）門檻在後台「職級規則」設定，只有管理員能改；新增這類規則在 `apps/accounts/levels.py` 的 `RULES` 加一筆，用 `allows(user, "規則代碼")` 判斷。
- 頁面權限在後台的「頁面權限」設定（最低職級、開放部門），只有管理員能改。列表會列出所有頁面，沒設定過的顯示「未開放」，只有管理員能進，按「開放」設定。
- 非管理員管理帳號或人員資料時，只看得到、也只能設定比自己低的職級，也不能改自己的職級。
- 新功能頁用 `PageAccessMixin` 或 `page_access_required("頁面代碼")` 套用。

## 人員資料

- 人員資料和系統帳號分開：不是每個人都有帳號，需要操作系統的人才另外開帳號（在「系統帳號」選人員建立，不能憑空建立帳號）。
- 欄位：工號、姓名、職級、部門、聯絡資料、到職日、備註、在職。每天實際站的工位在到班的工位安排記錄。
- 離職請取消「在職」，不要刪除；有系統帳號的會一併停用（管理員帳號除外）。復職不會自動啟用帳號，要到「系統帳號」手動打開。
- 本機測試資料：`python manage.py seed_personnel` 產生 15 位假人員（工號 T001–T015，可加 `--count 數量`），只填工號、姓名、手機、到職日，不建立部門、工位，也不建立系統帳號；重複執行不會重複建立。

## 到班登記

- 網址 `/attendance/`：上方輸入工號查出人員（不用選部門、不列出全部人員），按「上班」「下班」記錄當下時間；按上班會自動把狀態設為到班。狀態、時間、備註也可以手動修改後按「儲存修改」（請假、缺勤、補登時使用；狀態清空會刪除當天登記；缺勤不記時間與工位，請假會保留，因為可能是上午有到、中途請假離開），儲存後回到搜尋畫面。
- 上班只能按一次、不會被覆蓋；下班要先有上班。上班、下班按鈕只在今天出現，其他日期請直接修改時間。
- 依「職級規則」：可登記全部部門的人（預設經理以上）登記所有人員；可登記自己部門的人（預設組長以上）只能登記自己部門；其他人不能使用。
- 當天的紀錄由登記人自己修改；之前日期的紀錄要符合「修改之前日期」規則（預設主任以上）才能新增或修改；不能登記未來日期。
- 到班人數併在同一頁下方（日期跟上方同一個日期欄）：各部門在職、到班、請假、缺勤、未登記人數，以及到班人員所在工位。可登記全部部門的人若有未設定部門的人員，會多一列「未設定部門」。每個數字都可以點進去看人員名單（`/attendance/list/`），名單裡按「登記」會回到上方的登記畫面直接帶出那個人。舊的 `/attendance/headcount/` 會導向到班登記。
- 工位安排 `/attendance/stations/`：進來先看當天已建立的「批次」列表，不會直接展開名單。每一批顯示建立時間、建立人、到班人數與各部門人數，點開可看每個人的詳細工位；最新一批標示「目前生效」。
- 按「建立安排」（`/attendance/stations/new/`）才列出當天「到班」的人員（上午有到、中途請假的人也會列出並標示，才能繼續調整他的工位）（符合「工位安排：安排全部部門」規則的人看全部，預設經理以上；其他人只看自己部門），手動安排當日工位（任何工位都可選，不限部門；系統不自動建議，也還沒有各工位需求人數）。改完會先列出「原工位 → 新工位」，按「確認修改」才儲存，並建立一筆批次紀錄；沒有變更就不建立批次。每個人當前的工位存在到班紀錄裡（到班人數、名單看的是它），批次是每次儲存時的快照。不鎖定：當天可隨時建立，之前日期依「修改之前日期」規則，不能安排未來日期。登記畫面的工位只顯示。
- 頁面權限只剩兩個頁面代碼：`attendance-register`（含到班人數與名單）、`attendance-stations`，要先在「頁面權限」開放。

## 後台管理（自建，不依賴 Django admin）

- 組織：職級、部門、工位三者各自獨立，工位不屬於任何部門。職級可新增、改名、調整排序；還有人員、帳號或設定在用的職級不能刪除。
- 後台頁面左側固定有後台選單，可直接切換頁面；版型在 `backoffice/base.html`（`manage_header`、`manage_content` 區塊）。
- `apps/backoffice/`：後台首頁與共用 view（`ManageListView`、`ManageCreateView`、`ManageUpdateView`、`ManageDeleteView`）與共用 template。
- 新增後台頁面：在 `apps/backoffice/menu.py` 的 `MENU` 加一筆，再寫繼承上述類別的 view（設定 `model`、`form_class`、`page_key`、`columns`…），可參考 `apps/personnel/views.py`。
- 執行測試（不需要 MySQL）：`$env:DB_ENGINE="sqlite"; python manage.py test`

## 專案結構

- `apps/`：所有功能模組（Django app）都放在這裡，新增 app 用 `python manage.py startapp 名稱 apps/名稱`；建立後把 `apps.py` 的 `name` 改成 `apps.名稱`，並加進 `INSTALLED_APPS`
  - `apps/accounts/`：使用者、部門、工位、頁面權限
  - `apps/backoffice/`：自建後台的首頁、選單與共用 view
  - `apps/personnel/`：人員資料
  - `apps/attendance/`：到班登記（含到班人數）、工位安排
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
