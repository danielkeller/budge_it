from django.contrib import admin

from .models import *

class AccountInline(admin.TabularInline): # type: ignore
    model = Account
class CategoryInline(admin.TabularInline): # type: ignore
    model = Category

class BudgetAdmin(admin.ModelAdmin): # type: ignore
    inlines = [
        AccountInline,
        CategoryInline,
    ]

admin.site.register(Budget, BudgetAdmin)
admin.site.register(Account)
admin.site.register(Category)

class TransactionAccountPartInline(admin.TabularInline): # type: ignore
    model = TransactionAccountPart
class TransactionCategoryPartInline(admin.TabularInline): # type: ignore
    model = TransactionCategoryPart

class TransactionAdmin(admin.ModelAdmin): # type: ignore
    inlines = [
        TransactionAccountPartInline,
        TransactionCategoryPartInline,
    ]

admin.site.register(Transaction, TransactionAdmin)
