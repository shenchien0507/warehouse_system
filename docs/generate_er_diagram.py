"""從 Django models 產生資料庫關聯圖（Mermaid erDiagram），輸出到 docs/database-er.md。

改了 models 之後重跑一次即可：
    DB_ENGINE=sqlite python docs/generate_er_diagram.py
只讀 model 定義，不連資料庫。
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.db import models  # noqa: E402

OUTPUT = BASE_DIR / "docs" / "database-er.md"

# 依功能分區（標題、說明、包含的 app）
SECTIONS = [
    ("帳號與組織", "登入帳號、職級、部門、工位、頁面權限，以及人員資料。", ["accounts", "personnel"]),
    ("到班與工位安排", "每天的到班紀錄、打卡事件、批次排工位。", ["attendance"]),
    ("訂單匯入與統計", "欄位對應版本、統計分組版本、匯入批次與訂單明細。", ["orders"]),
    ("當日統計", "當天多次匯入的訂單、明細與保留（hold）。", ["daily"]),
    ("撿貨／配貨登記", "撿貨、配貨的開始與結束人員，以及允許登記的工位設定。", ["worklog"]),
    ("登記紀錄", "獨立的登記表，除了操作人之外不用外鍵關聯。", ["records"]),
]
PROJECT_APPS = [label for _, _, labels in SECTIONS for label in labels]
USER_MODEL = apps.get_model(settings.AUTH_USER_MODEL)

# 這些欄位只是記「誰建立／誰修改」，在總覽圖省略，避免所有表都連到使用者
AUDIT_SUFFIXES = ("_by",)


def entity(model):
    return model._meta.db_table


def label(model):
    return f"{model._meta.verbose_name}"


def field_type(field):
    internal = field.get_internal_type()
    mapping = {
        "AutoField": "int", "BigAutoField": "bigint", "IntegerField": "int", "BigIntegerField": "bigint",
        "PositiveIntegerField": "int", "PositiveSmallIntegerField": "smallint", "SmallIntegerField": "smallint",
        "CharField": "varchar", "TextField": "text", "BooleanField": "bool", "DateField": "date",
        "DateTimeField": "datetime", "TimeField": "time", "JSONField": "json", "DecimalField": "decimal",
        "ForeignKey": "int", "OneToOneField": "int", "EmailField": "varchar", "DurationField": "duration",
    }
    return mapping.get(internal, internal.replace("Field", "").lower())


def is_audit(field):
    return field.related_model is USER_MODEL and field.name.endswith(AUDIT_SUFFIXES)


def attributes(model):
    lines = []
    for field in model._meta.concrete_fields:
        keys = []
        if field.primary_key:
            keys.append("PK")
        if field.is_relation:
            keys.append("FK")
        if field.unique and not field.primary_key:
            keys.append("UK")
        name = field.column
        comment = str(field.verbose_name).replace('"', "'")
        if field.choices and not field.is_relation:
            comment += "（選項）"
        lines.append(f'        {field_type(field)} {name} {",".join(keys)} "{comment}"'.replace("  \"", " \""))
    return lines


def relations(model, include_audit=True):
    """回傳 (左表, 右表, 關係符號, 說明)。左邊是「一」，右邊是「多」。"""
    out = []
    for field in model._meta.concrete_fields:
        if not field.is_relation:
            continue
        if not include_audit and is_audit(field):
            continue
        target = field.related_model
        if field.one_to_one:
            card = "||--o|"
        else:
            card = ("|o--o{" if field.null else "||--o{")
        out.append((entity(target), entity(model), card, str(field.verbose_name)))
    for field in model._meta.local_many_to_many:
        if field.related_model._meta.app_label not in PROJECT_APPS:
            continue  # Django 內建的群組、權限表，這個系統沒用到
        out.append((entity(model), entity(field.related_model), "}o--o{", f"{field.verbose_name}（多對多）"))
    return out


def models_of(labels):
    return [m for label_ in labels for m in apps.get_app_config(label_).get_models()]


def diagram(section_models, include_fields=True, include_audit=True):
    names = {entity(m) for m in section_models}
    rels, externals = [], set()
    for model in section_models:
        for left, right, card, text in relations(model, include_audit):
            rels.append(f'    {left} {card} {right} : "{text}"')
            externals.update({left, right} - names)
    lines = ["```mermaid", "erDiagram"]
    for model in section_models:
        if include_fields:
            lines.append(f'    {entity(model)}["{label(model)} {entity(model)}"] {{')
            lines += attributes(model)
            lines.append("    }")
        else:
            lines.append(f'    {entity(model)}["{label(model)}"]')
    all_models = {entity(m): m for m in apps.get_models()}
    for ext in sorted(externals):
        model = all_models[ext]
        lines.append(f'    {ext}["{label(model)}（其他區）"]')
    lines += sorted(set(rels), key=rels.index)
    lines.append("```")
    return "\n".join(lines)


def build():
    parts = [
        "# 資料庫關聯圖",
        "",
        "> 這份文件由 `docs/generate_er_diagram.py` 從 Django models 自動產生，不要手動修改。",
        "> 改了 models 之後執行 `DB_ENGINE=sqlite python docs/generate_er_diagram.py` 重新產生。",
        "",
        "圖例：`||--o{` 一對多、`|o--o{` 一對多（可空）、`||--o|` 一對一、`}o--o{` 多對多。",
        "欄位標記：PK 主鍵、FK 外鍵、UK 不可重複。",
        "",
        "## 總覽",
        "",
        "只列資料表和主要關聯；「建立人／修改人」這類記錄操作者的外鍵（欄位名 `*_by`）在總覽省略，分區圖裡才畫出來。",
        "",
        diagram(models_of(PROJECT_APPS), include_fields=False, include_audit=False),
        "",
        "## 沒有用外鍵、但用名稱對應的關係",
        "",
        "- `records_record.kind`（種類）存的是統計分組 `orders_statgroup.name` 的文字，分組版本換了也不受影響。",
        "- `worklog_workentry.number`（編號）存文字，登記當下比對：撿貨比對 `records_record.number`，配貨比對撿貨的編號。",
        "",
    ]
    for title, desc, labels in SECTIONS:
        parts += [f"## {title}", "", desc, "", diagram(models_of(labels)), ""]
    return "\n".join(parts)


if __name__ == "__main__":
    OUTPUT.write_text(build(), encoding="utf-8")
    print(f"已寫入 {OUTPUT.relative_to(BASE_DIR)}")
