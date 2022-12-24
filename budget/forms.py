from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from django.forms import ValidationError

from .models import (Budget, Account, Category, Transaction)


class AccountChoiceField(forms.ModelChoiceField):
    def to_python(self, value: Any):
        if value in self.empty_values:
            return None
        try:
            return self.queryset.get(id=value)
        except (TypeError, ValueError, self.queryset.model.DoesNotExist):
            pass
        if (self.queryset.model == Category
                and value.startswith('[') and value.endswith(']')):
            value = value[1:-1]
        budget, _ = Budget.objects.get_or_create(name=value)
        return budget.get_hidden(self.queryset.model)


class TransactionPartForm(forms.Form):
    account = AccountChoiceField(
        required=False, queryset=None, empty_label='', widget=forms.HiddenInput)
    category = AccountChoiceField(
        required=False, queryset=None, empty_label='', widget=forms.HiddenInput)
    transferred = forms.DecimalField(
        required=False, widget=forms.TextInput(attrs={'size': 7}))
    moved = forms.DecimalField(
        required=False, widget=forms.TextInput(attrs={'size': 7}))


class BaseTransactionPartFormSet(forms.BaseFormSet):
    budget: Budget

    def __init__(self, budget: Budget, *args: Any,
                 instance: Transaction, **kwargs: Any):
        self.budget = budget
        if instance:
            initial = instance.tabular(budget.id)
            for row in initial:
                if row['account']:
                    row['transferred'] = row['amount']
                if row['category']:
                    row['moved'] = row['amount']
        else:
            initial = None
        super().__init__(*args, initial=initial, **kwargs)

    def add_fields(self, form: TransactionPartForm, index: int):
        super().add_fields(form, index)
        # queryset is ˚*･༓ magic ༓･*˚ so it has to be set second
        form.fields['account'].budget = self.budget
        form.fields['account'].queryset = Account.objects.all()
        form.fields['category'].budget = self.budget
        form.fields['category'].queryset = Category.objects.all()

    def clean(self):
        if any(self.errors):
            return
        category_total, account_total = 0, 0
        for form in self.forms:
            if form.cleaned_data.get('category'):
                category_total += (form.cleaned_data.get('moved') or 0)
            if form.cleaned_data.get('account'):
                account_total += (form.cleaned_data.get('transferred') or 0)
        if account_total or category_total:
            raise ValidationError("Amounts do not sum to zero")

    @transaction.atomic
    def save(self, *, instance: Transaction):
        accounts: dict[Account, int] = {}
        categories: dict[Category, int] = {}
        for form in self.forms:
            if (form.cleaned_data.get('account')
                    and form.cleaned_data.get('transferred')):
                accounts[form.cleaned_data['account']
                         ] = form.cleaned_data['transferred']
            if (form.cleaned_data.get('category')
                    and form.cleaned_data.get('moved')):
                categories[form.cleaned_data['category']
                           ] = form.cleaned_data['moved']
        instance.set_parts(self.budget.id, (accounts, categories))


TransactionPartFormSet = forms.formset_factory(
    TransactionPartForm, formset=BaseTransactionPartFormSet, extra=2)


class TransactionForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date', 'description')
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))


class AccountForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Account
        fields = ('name',)
    name = forms.CharField(required=True)


class CategoryForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Category
        fields = ('name',)
    name = forms.CharField(required=True)
