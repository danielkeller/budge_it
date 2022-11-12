from typing import Any, Optional

from django import forms
from django.utils.translation import gettext_lazy as _
from django.db import transaction

from .models import Budget, Account, Category, Transaction
from .models import Purchase


class PurchaseForm(forms.Form):
    budget: Budget
    date = forms.DateField()
    description = forms.CharField(max_length=1000, required=False,
                                  widget=forms.Textarea)
    from_account = forms.ModelChoiceField(queryset=None)
    to_account = forms.ModelChoiceField(queryset=None)
    from_category = forms.ModelChoiceField(queryset=None)
    amount = forms.DecimalField()

    def __init__(self, budget: Budget, *args: Any,
                 instance: Optional[Transaction] = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.budget = budget
        self.fields['amount'].decimal_places = 2  # TODO correctly
        self.fields['from_account'].queryset = Account.objects.all()
        self.fields['to_account'].queryset = Account.objects.all()
        self.fields['from_category'].queryset = Category.objects.all()

    @transaction.atomic
    def save(self, instance: Optional[Transaction] = None):
        if instance:
            instance.delete()
        transaction = Purchase()
        transaction.date = self.cleaned_data['date']
        transaction.description = self.cleaned_data['description']
        transaction.amount = self.cleaned_data['amount']
        transaction.from_account = self.cleaned_data['from_account']
        transaction.to_account = self.cleaned_data['to_account']
        transaction.from_category = self.cleaned_data['from_category']
        transaction.save()
