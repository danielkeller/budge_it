from django.contrib import admin

from .models import *


class AccountInline(admin.TabularInline):  # type: ignore
    model = Account
    fk_name = 'budget'


class CategoryInline(admin.TabularInline):  # type: ignore
    model = Category
    fk_name = 'budget'


class BudgetAdmin(admin.ModelAdmin):  # type: ignore
    inlines = [
        AccountInline,
        CategoryInline,
    ]
    search_fields = ['name']


admin.site.register(Budget, BudgetAdmin)
admin.site.register(Account)
admin.site.register(Category)


class TransactionAccountPartInline(admin.TabularInline):  # type: ignore
    model = TransactionAccountPart
    raw_id_fields = ['to']


class TransactionCategoryPartInline(admin.TabularInline):  # type: ignore
    model = TransactionCategoryPart
    raw_id_fields = ['to']


class TransactionAdmin(admin.ModelAdmin):  # type: ignore
    inlines = [
        TransactionAccountPartInline,
        TransactionCategoryPartInline,
    ]


admin.site.register(Transaction, TransactionAdmin)
