# Generated by Django 4.1.3 on 2023-01-01 14:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0002_alter_category_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='kind',
            field=models.CharField(choices=[('T', 'Transaction'), ('B', 'Budgeting')], default='T', max_length=1),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='description',
            field=models.CharField(blank=True, max_length=1000),
        ),
    ]
