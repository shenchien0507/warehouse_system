# 資料庫關聯圖

> 這份文件由 `docs/generate_er_diagram.py` 從 Django models 自動產生，不要手動修改。
> 改了 models 之後執行 `DB_ENGINE=sqlite python docs/generate_er_diagram.py` 重新產生。

圖例：`||--o{` 一對多、`|o--o{` 一對多（可空）、`||--o|` 一對一、`}o--o{` 多對多。
欄位標記：PK 主鍵、FK 外鍵、UK 不可重複。

## 總覽

只列資料表和主要關聯；「建立人／修改人」這類記錄操作者的外鍵（欄位名 `*_by`）在總覽省略，分區圖裡才畫出來。

```mermaid
erDiagram
    accounts_level["職級"]
    accounts_levelrule["職級規則"]
    accounts_department["部門"]
    accounts_station["工位"]
    accounts_user["使用者"]
    accounts_pagepermission["頁面權限"]
    personnel_employee["人員"]
    attendance_attendance["到班紀錄"]
    attendance_attendanceevent["到班明細"]
    attendance_stationbatch["工位安排批次"]
    attendance_stationbatchentry["工位安排明細"]
    attendance_clocksetting["上下班時間"]
    attendance_stationeditlock["工位安排編輯鎖"]
    orders_mappingversion["欄位對應版本"]
    orders_columnmapping["欄位對應"]
    orders_importcategory["匯入分類"]
    orders_statrun["統計紀錄"]
    orders_importbatch["匯入批次"]
    orders_orderline["訂單商品列"]
    orders_groupversion["統計分組版本"]
    orders_statgroup["統計分組"]
    orders_statcondition["分組條件"]
    daily_dailybatch["當日匯入批次"]
    daily_dailyorder["當日訂單"]
    daily_dailyline["當日商品列"]
    daily_dailyhold["抽單紀錄"]
    worklog_workentry["作業登記"]
    worklog_worklogsetting["撿貨配貨設定"]
    records_record["登記紀錄"]
    accounts_level |o--o{ accounts_levelrule : "最低職級"
    accounts_level |o--o{ accounts_user : "職級"
    accounts_department |o--o{ accounts_user : "部門"
    accounts_level ||--o{ accounts_pagepermission : "最低職級"
    accounts_pagepermission }o--o{ accounts_department : "開放部門（多對多）"
    accounts_department |o--o{ personnel_employee : "部門"
    accounts_level |o--o{ personnel_employee : "職級"
    accounts_user ||--o| personnel_employee : "系統帳號"
    personnel_employee ||--o{ attendance_attendance : "人員"
    accounts_station |o--o{ attendance_attendance : "當日工位"
    attendance_attendance ||--o{ attendance_attendanceevent : "到班紀錄"
    attendance_stationbatch ||--o{ attendance_stationbatchentry : "批次"
    personnel_employee ||--o{ attendance_stationbatchentry : "人員"
    accounts_station |o--o{ attendance_stationbatchentry : "工位"
    accounts_user ||--o{ attendance_stationeditlock : "編輯人"
    orders_mappingversion ||--o{ orders_columnmapping : "版本"
    orders_statrun ||--o{ orders_importbatch : "統計紀錄"
    orders_importcategory |o--o{ orders_importbatch : "分類"
    orders_mappingversion ||--o{ orders_importbatch : "欄位對應版本"
    orders_groupversion |o--o{ orders_importbatch : "統計分組版本"
    orders_importbatch ||--o{ orders_orderline : "匯入批次"
    orders_groupversion ||--o{ orders_statgroup : "版本"
    orders_statgroup ||--o{ orders_statcondition : "分組"
    orders_mappingversion ||--o{ daily_dailybatch : "欄位對應版本"
    orders_groupversion ||--o{ daily_dailybatch : "統計分組版本"
    daily_dailybatch ||--o{ daily_dailyorder : "第一次出現的批次"
    daily_dailybatch ||--o{ daily_dailyline : "匯入批次"
    daily_dailyorder ||--o{ daily_dailyline : "當日訂單"
    daily_dailyorder ||--o{ daily_dailyhold : "當日訂單"
    daily_dailybatch |o--o{ daily_dailyhold : "出現在哪一批"
    personnel_employee ||--o{ worklog_workentry : "開始員工"
    personnel_employee |o--o{ worklog_workentry : "結束員工"
    worklog_worklogsetting }o--o{ accounts_station : "撿貨可登記的工位（多對多）"
    worklog_worklogsetting }o--o{ accounts_station : "配貨可登記的工位（多對多）"
```

## 沒有用外鍵、但用名稱對應的關係

- `records_record.kind`（種類）存的是統計分組 `orders_statgroup.name` 的文字，分組版本換了也不受影響。
- `worklog_workentry.number`（編號）存文字，登記當下比對：撿貨比對 `records_record.number`，配貨比對撿貨的編號。

## 帳號與組織

登入帳號、職級、部門、工位、頁面權限，以及人員資料。

```mermaid
erDiagram
    accounts_level["職級 accounts_level"] {
        bigint id PK "ID"
        varchar name UK "職級名稱"
        smallint rank UK "排序"
    }
    accounts_levelrule["職級規則 accounts_levelrule"] {
        bigint id PK "ID"
        slug code UK "規則代碼"
        int min_level_id FK "最低職級"
    }
    accounts_department["部門 accounts_department"] {
        bigint id PK "ID"
        varchar name UK "部門名稱"
    }
    accounts_station["工位 accounts_station"] {
        bigint id PK "ID"
        varchar name UK "工位名稱"
    }
    accounts_user["使用者 accounts_user"] {
        bigint id PK "ID"
        varchar password "密碼"
        datetime last_login "上次登入"
        bool is_superuser "超級使用者狀態"
        varchar username UK "使用者名稱"
        varchar email "電子郵件"
        bool is_staff "工作人員狀態"
        bool is_active "有效"
        datetime date_joined "加入日期"
        varchar name "姓名"
        varchar phone "聯絡資料"
        int level_id FK "職級"
        bool is_admin "管理員"
        int department_id FK "部門"
    }
    accounts_pagepermission["頁面權限 accounts_pagepermission"] {
        bigint id PK "ID"
        slug page_key UK "頁面代碼"
        varchar label "頁面名稱"
        int min_level_id FK "最低職級"
    }
    personnel_employee["人員 personnel_employee"] {
        bigint id PK "ID"
        varchar employee_no UK "工號"
        varchar name "姓名"
        int department_id FK "部門"
        int level_id FK "職級"
        varchar phone "聯絡資料"
        date hire_date "到職日"
        bool is_active "在職"
        int user_id FK,UK "系統帳號"
        text note "備註"
    }
    accounts_level |o--o{ accounts_levelrule : "最低職級"
    accounts_level |o--o{ accounts_user : "職級"
    accounts_department |o--o{ accounts_user : "部門"
    accounts_level ||--o{ accounts_pagepermission : "最低職級"
    accounts_pagepermission }o--o{ accounts_department : "開放部門（多對多）"
    accounts_department |o--o{ personnel_employee : "部門"
    accounts_level |o--o{ personnel_employee : "職級"
    accounts_user ||--o| personnel_employee : "系統帳號"
```

## 到班與工位安排

每天的到班紀錄、打卡事件、批次排工位。

```mermaid
erDiagram
    attendance_attendance["到班紀錄 attendance_attendance"] {
        bigint id PK "ID"
        int employee_id FK "人員"
        date date "日期"
        varchar status "狀態（選項）"
        time clock_in "第一次上班"
        time clock_out "最後離開"
        bool on_site "目前在場"
        int station_id FK "當日工位"
        int created_by_id FK "登記人"
        int updated_by_id FK "最後修改人"
        datetime created_at "登記時間"
        datetime updated_at "最後修改時間"
    }
    attendance_attendanceevent["到班明細 attendance_attendanceevent"] {
        bigint id PK "ID"
        int attendance_id FK "到班紀錄"
        varchar kind "類型（選項）"
        time time "時間"
        time end_time "結束時間"
        varchar note "原因／備註"
        int created_by_id FK "登記人"
        datetime created_at "登記時間"
        int voided_by_id FK "作廢人"
        datetime voided_at "作廢時間"
    }
    attendance_stationbatch["工位安排批次 attendance_stationbatch"] {
        bigint id PK "ID"
        date date "日期"
        int created_by_id FK "建立人"
        datetime created_at "建立時間"
    }
    attendance_stationbatchentry["工位安排明細 attendance_stationbatchentry"] {
        bigint id PK "ID"
        int batch_id FK "批次"
        int employee_id FK "人員"
        int station_id FK "工位"
    }
    attendance_clocksetting["上下班時間 attendance_clocksetting"] {
        bigint id PK "ID"
        time work_start "上班時間"
        smallint clock_in_early "上班：可提早（−分鐘）"
        smallint clock_in_late "上班：可延後（+分鐘）"
        time work_end "下班時間"
        smallint clock_out_early "下班：可提早（−分鐘）"
        smallint clock_out_late "下班：可延後（+分鐘）"
    }
    attendance_stationeditlock["工位安排編輯鎖 attendance_stationeditlock"] {
        bigint id PK "ID"
        int user_id FK "編輯人"
        date date "編輯的日期"
        datetime started_at "開始編輯"
        datetime touched_at "最後動作"
    }
    accounts_station["工位（其他區）"]
    accounts_user["使用者（其他區）"]
    personnel_employee["人員（其他區）"]
    personnel_employee ||--o{ attendance_attendance : "人員"
    accounts_station |o--o{ attendance_attendance : "當日工位"
    accounts_user ||--o{ attendance_attendance : "登記人"
    accounts_user ||--o{ attendance_attendance : "最後修改人"
    attendance_attendance ||--o{ attendance_attendanceevent : "到班紀錄"
    accounts_user ||--o{ attendance_attendanceevent : "登記人"
    accounts_user |o--o{ attendance_attendanceevent : "作廢人"
    accounts_user ||--o{ attendance_stationbatch : "建立人"
    attendance_stationbatch ||--o{ attendance_stationbatchentry : "批次"
    personnel_employee ||--o{ attendance_stationbatchentry : "人員"
    accounts_station |o--o{ attendance_stationbatchentry : "工位"
    accounts_user ||--o{ attendance_stationeditlock : "編輯人"
```

## 訂單匯入與統計

欄位對應版本、統計分組版本、匯入批次與訂單明細。

```mermaid
erDiagram
    orders_mappingversion["欄位對應版本 orders_mappingversion"] {
        bigint id PK "ID"
        int number UK "版本"
        smallint header_row "欄名在第幾列"
        varchar source_file_name "來源檔"
        json source_columns "來源檔的欄名"
        varchar note "備註"
        bool is_active "生效中"
        datetime activated_at "第一次生效時間"
        int created_by_id FK "建立人"
        datetime created_at "建立時間"
    }
    orders_columnmapping["欄位對應 orders_columnmapping"] {
        bigint id PK "ID"
        int version_id FK "版本"
        varchar field "系統欄位（選項）"
        varchar source_column "來源欄名"
    }
    orders_importcategory["匯入分類 orders_importcategory"] {
        bigint id PK "ID"
        varchar name UK "分類名稱"
        int sort_order "顯示順序"
        bool is_active "使用中"
    }
    orders_statrun["統計紀錄 orders_statrun"] {
        bigint id PK "ID"
        date work_date "作業日"
        datetime created_at "匯入時間"
        int created_by_id FK "匯入人"
    }
    orders_importbatch["匯入批次 orders_importbatch"] {
        bigint id PK "ID"
        int run_id FK "統計紀錄"
        int category_id FK "分類"
        varchar category_name "分類名稱"
        varchar file_name "檔名"
        datetime imported_at "匯入時間"
        date work_date "作業日"
        int imported_by_id FK "匯入人"
        int mapping_version_id FK "欄位對應版本"
        int group_version_id FK "統計分組版本"
        int line_count "商品列數"
        int order_count "訂單數"
    }
    orders_orderline["訂單商品列 orders_orderline"] {
        bigint id PK "ID"
        int batch_id FK "匯入批次"
        int row_no "來源檔第幾列"
        varchar order_no "訂單號"
        varchar platform_order_no "平台訂單編號"
        varchar platform "平台"
        varchar shop "店鋪"
        datetime order_time "下單時間"
        datetime ship_time "出貨時間"
        varchar ship_type "出貨方式"
        varchar shipment_no "出貨單號"
        varchar product_code "商品編號"
        varchar product_name "商品名稱"
        varchar product_spec "商品樣式"
        int quantity "數量"
    }
    orders_groupversion["統計分組版本 orders_groupversion"] {
        bigint id PK "ID"
        int number UK "版本"
        varchar note "備註"
        varchar source_file_name "來源檔"
        json source_combos "來源檔的平台／店鋪／出貨類型"
        bool is_active "生效中"
        datetime activated_at "第一次生效時間"
        int created_by_id FK "建立人"
        datetime created_at "建立時間"
    }
    orders_statgroup["統計分組 orders_statgroup"] {
        bigint id PK "ID"
        int version_id FK "版本"
        varchar name "分組名稱"
        int sort_order "顯示順序"
        time cutoff "切開時間"
        bool midnight_uses_import_time "下單時間是 00:00:00 時用匯入時間"
        bool carry_over "作業日之前的訂單算進前"
        bool split_by_day "沒切時間時一天一列"
        bool show_rows "另外列出非去重"
    }
    orders_statcondition["分組條件 orders_statcondition"] {
        bigint id PK "ID"
        int group_id FK "分組"
        json platforms "交易平台"
        json shops "交易店鋪"
        json ship_types "出貨類型"
    }
    accounts_user["使用者（其他區）"]
    accounts_user |o--o{ orders_mappingversion : "建立人"
    orders_mappingversion ||--o{ orders_columnmapping : "版本"
    accounts_user |o--o{ orders_statrun : "匯入人"
    orders_statrun ||--o{ orders_importbatch : "統計紀錄"
    orders_importcategory |o--o{ orders_importbatch : "分類"
    accounts_user |o--o{ orders_importbatch : "匯入人"
    orders_mappingversion ||--o{ orders_importbatch : "欄位對應版本"
    orders_groupversion |o--o{ orders_importbatch : "統計分組版本"
    orders_importbatch ||--o{ orders_orderline : "匯入批次"
    accounts_user |o--o{ orders_groupversion : "建立人"
    orders_groupversion ||--o{ orders_statgroup : "版本"
    orders_statgroup ||--o{ orders_statcondition : "分組"
```

## 當日統計

當天多次匯入的訂單、明細與保留（hold）。

```mermaid
erDiagram
    daily_dailybatch["當日匯入批次 daily_dailybatch"] {
        bigint id PK "ID"
        date work_date "作業日"
        int seq "第幾批"
        varchar file_name "檔名"
        varchar file_hash "檔案指紋"
        datetime imported_at "匯入時間"
        int imported_by_id FK "匯入人"
        int mapping_version_id FK "欄位對應版本"
        int group_version_id FK "統計分組版本"
        int line_count "商品列數"
        int order_count "訂單數"
        int new_order_count "新訂單數"
    }
    daily_dailyorder["當日訂單 daily_dailyorder"] {
        bigint id PK "ID"
        date work_date "作業日"
        varchar order_no "訂單號"
        int batch_id FK "第一次出現的批次"
    }
    daily_dailyline["當日商品列 daily_dailyline"] {
        bigint id PK "ID"
        int batch_id FK "匯入批次"
        int order_id FK "當日訂單"
        bool is_duplicate "重複"
        int row_no "來源檔第幾列"
        varchar order_no "訂單號"
        varchar platform_order_no "平台訂單編號"
        varchar platform "平台"
        varchar shop "店鋪"
        datetime order_time "下單時間"
        datetime ship_time "出貨時間"
        varchar ship_type "出貨方式"
        varchar shipment_no "出貨單號"
        varchar product_code "商品編號"
        varchar product_name "商品名稱"
        varchar product_spec "商品樣式"
        int quantity "數量"
    }
    daily_dailyhold["抽單紀錄 daily_dailyhold"] {
        bigint id PK "ID"
        int order_id FK "當日訂單"
        varchar reason "原因"
        varchar status "狀態（選項）"
        datetime held_at "抽起時間"
        int held_by_id FK "抽起人"
        datetime released_at "放回時間"
        int released_by_id FK "放回人"
        int released_batch_id FK "出現在哪一批"
    }
    accounts_user["使用者（其他區）"]
    orders_groupversion["統計分組版本（其他區）"]
    orders_mappingversion["欄位對應版本（其他區）"]
    accounts_user |o--o{ daily_dailybatch : "匯入人"
    orders_mappingversion ||--o{ daily_dailybatch : "欄位對應版本"
    orders_groupversion ||--o{ daily_dailybatch : "統計分組版本"
    daily_dailybatch ||--o{ daily_dailyorder : "第一次出現的批次"
    daily_dailybatch ||--o{ daily_dailyline : "匯入批次"
    daily_dailyorder ||--o{ daily_dailyline : "當日訂單"
    daily_dailyorder ||--o{ daily_dailyhold : "當日訂單"
    accounts_user |o--o{ daily_dailyhold : "抽起人"
    accounts_user |o--o{ daily_dailyhold : "放回人"
    daily_dailybatch |o--o{ daily_dailyhold : "出現在哪一批"
```

## 撿貨／配貨登記

撿貨、配貨的開始與結束人員，以及允許登記的工位設定。

```mermaid
erDiagram
    worklog_workentry["作業登記 worklog_workentry"] {
        bigint id PK "ID"
        varchar stage "階段（選項）"
        varchar number "編號"
        int start_employee_id FK "開始員工"
        datetime started_at "開始時間"
        int end_employee_id FK "結束員工"
        datetime ended_at "結束時間"
        bool anomaly "異常"
        int created_by_id FK "登記帳號"
        int updated_by_id FK "最後修改人"
        datetime updated_at "最後修改時間"
    }
    worklog_worklogsetting["撿貨配貨設定 worklog_worklogsetting"] {
        bigint id PK "ID"
        smallint rescan_seconds "重複刷的間隔（秒）"
    }
    accounts_station["工位（其他區）"]
    accounts_user["使用者（其他區）"]
    personnel_employee["人員（其他區）"]
    personnel_employee ||--o{ worklog_workentry : "開始員工"
    personnel_employee |o--o{ worklog_workentry : "結束員工"
    accounts_user |o--o{ worklog_workentry : "登記帳號"
    accounts_user |o--o{ worklog_workentry : "最後修改人"
    worklog_worklogsetting }o--o{ accounts_station : "撿貨可登記的工位（多對多）"
    worklog_worklogsetting }o--o{ accounts_station : "配貨可登記的工位（多對多）"
```

## 登記紀錄

獨立的登記表，除了操作人之外不用外鍵關聯。

```mermaid
erDiagram
    records_record["登記紀錄 records_record"] {
        bigint id PK "ID"
        varchar number UK "編號"
        varchar date_text "日期"
        varchar name "名稱"
        int quantity "數量"
        varchar kind "種類"
        int created_by_id FK "操作人"
        datetime created_at "登記時間"
        int updated_by_id FK "最後修改人"
        datetime updated_at "最後修改時間"
    }
    accounts_user["使用者（其他區）"]
    accounts_user |o--o{ records_record : "操作人"
    accounts_user |o--o{ records_record : "最後修改人"
```
