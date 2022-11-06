from django.contrib import admin

from .models import *

admin.site.register(Budget)
admin.site.register(Account)
admin.site.register(Category)

class TransactionPartInline(admin.TabularInline): # type: ignore
    model = TransactionPart

class TransactionAdmin(admin.ModelAdmin): # type: ignore
    inlines = [
        TransactionPartInline,
    ]

admin.site.register(Transaction, TransactionAdmin)
