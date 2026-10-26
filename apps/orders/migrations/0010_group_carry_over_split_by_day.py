from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("orders", "0009_batch_work_date")]

    operations = [
        migrations.AddField(
            model_name="statgroup", name="carry_over",
            field=models.BooleanField(
                "作業日之前的訂單算進前", default=True,
                help_text="有切開時間時：勾選後作業日之前的訂單不管幾點都算「前」（跨日累計）；不勾就每張照自己的下單時間分前後。",
            ),
        ),
        migrations.AddField(
            model_name="statgroup", name="split_by_day",
            field=models.BooleanField(
                "沒切時間時一天一列", default=True, help_text="沒有切開時間時：勾選後依下單日期一天一列；不勾就跨日合成一列。",
            ),
        ),
    ]
