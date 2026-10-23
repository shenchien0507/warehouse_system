import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_custom_levels"),
    ]

    operations = [
        migrations.AlterField(
            model_name="level",
            name="rank",
            field=models.PositiveSmallIntegerField(
                help_text="1–100，數字越大職級越高，例如員工 10、組長 20",
                unique=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="排序",
            ),
        ),
        migrations.AddConstraint(
            model_name="level",
            constraint=models.CheckConstraint(
                condition=models.Q(("rank__gte", 1), ("rank__lte", 100)),
                name="level_rank_range",
            ),
        ),
    ]
