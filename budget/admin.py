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


class AccountPartInline(admin.TabularInline):  # type: ignore
    model = AccountPart
    raw_id_fields = ['source', 'sink']


class CategoryPartInline(admin.TabularInline):  # type: ignore
    model = CategoryPart
    raw_id_fields = ['source', 'sink']


class AccountNoteInline(admin.TabularInline):  # type: ignore
    model = AccountNote
    raw_id_fields = ['account']


class CategoryNoteInline(admin.TabularInline):  # type: ignore
    model = CategoryNote
    raw_id_fields = ['account']


class TransactionAdmin(admin.ModelAdmin):  # type: ignore
    inlines = [
        AccountPartInline,
        CategoryPartInline,
        AccountNoteInline,
        CategoryNoteInline,
    ]


admin.site.register(Transaction, TransactionAdmin)
