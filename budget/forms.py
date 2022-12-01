from typing import Any, Optional

from django import forms
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from django.forms import ValidationError

from .models import (Budget, Account, Category,
                     Transaction, Purchase, BaseAccount,
                     TransactionAccountPart, TransactionCategoryPart)


class AccountChoiceField(forms.ModelChoiceField):
    budget: Budget

    def label_from_instance(self, obj: BaseAccount):  # type: ignore
        return obj.name_in_budget(self.budget.id)


class TransactionPartForm(forms.Form):
    account = AccountChoiceField(required=False, queryset=None, empty_label='')
    category = AccountChoiceField(
        required=False, queryset=None, empty_label='')
    transferred = forms.DecimalField(
        required=False, widget=forms.TextInput(attrs={'size': 7}))
    moved = forms.DecimalField(
        required=False, widget=forms.TextInput(attrs={'size': 7}))

    def save(self, transaction: Transaction):
        if (self.cleaned_data.get('account')
                and self.cleaned_data.get('transferred')):
            TransactionAccountPart.objects.create(
                transaction=transaction, to=self.cleaned_data['account'],
                amount=self.cleaned_data['transferred']
            )
        if (self.cleaned_data.get('category')
                and self.cleaned_data.get('moved')):
            TransactionCategoryPart.objects.create(
                transaction=transaction, to=self.cleaned_data['category'],
                amount=self.cleaned_data['moved']
            )


class BaseTransactionPartFormSet(forms.BaseFormSet):
    budget: Budget
    instance: Transaction

    def __init__(self, budget: Budget, *args: Any,
                 instance: Transaction, **kwargs: Any):
        self.budget = budget
        self.instance = instance
        if instance:
            initial = instance.tabular()
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
    def save(self):
        self.instance.accounts.clear()
        self.instance.categories.clear()
        for form in self.forms:
            form.save(self.instance)


TransactionPartFormSet = forms.formset_factory(
    TransactionPartForm, formset=BaseTransactionPartFormSet)


class TransactionForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date', 'description')


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
