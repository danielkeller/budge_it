# Generated by Django 4.2.3 on 2023-07-30 08:46

import budget.models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0008_account_m2m_account_category_m2m_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='recurrence',
            field=budget.models.RecurrenceRuleField(
                max_length=255, null=True, blank=True),
        ),
    ]