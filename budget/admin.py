from django.contrib import admin
from django import forms

from .models import *


class AccountInline(admin.TabularInline):  # type: ignore
    model = Account
    fk_name = 'budget'
    formfield_overrides = {
        models.CharField: {"widget": forms.TextInput(attrs={'size': 20})},
    }


class CategoryInline(admin.TabularInline):  # type: ignore
    model = Category
    fk_name = 'budget'
    formfield_overrides = {
        models.CharField: {"widget": forms.TextInput(attrs={'size': 20})},
    }


class BudgetAdmin(admin.ModelAdmin):  # type: ignore
    inlines = [
        AccountInline,
        CategoryInline,
    ]
    search_fields = ['name']


admin.site.register(Budget, BudgetAdmin)
admin.site.register(BudgetFriends)
admin.site.register(Account)
admin.site.register(Category)


class AccountEntryInline(admin.TabularInline):  # type: ignore
    model = AccountEntry
    raw_id_fields = ['source', 'sink']


class CategoryEntryInline(admin.TabularInline):  # type: ignore
    model = CategoryEntry
    raw_id_fields = ['source', 'sink']


class TransactionPartAdmin(admin.ModelAdmin):  # type: ignore
    fields = ['note']
    inlines = [
        AccountEntryInline,
        CategoryEntryInline,
    ]


admin.site.register(TransactionPart, TransactionPartAdmin)


class TransactionPartInline(admin.TabularInline):  # type: ignore
    model = TransactionPart
    fields = ['note']
    show_change_link = True


class ClearedInline(admin.TabularInline):  # type: ignore
    model = Cleared
    raw_id_fields = ['account']


class TransactionAdmin(admin.ModelAdmin):  # type: ignore
    inlines = [ClearedInline, TransactionPartInline]


admin.site.register(Transaction, TransactionAdmin)
