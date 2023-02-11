from typing import Any, Union, Mapping

from django import forms
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from django.forms import ValidationError

from .models import (Budget, BaseAccount, Account, Category, Transaction)


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
        instance.set_parts(self.budget.id, accounts, categories)


TransactionPartFormSet = forms.formset_factory(
    TransactionPartForm, formset=BaseTransactionPartFormSet, extra=2)


class BudgetingForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date', 'description')
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, budget: Budget, *args: Any,
                 instance: Transaction, **kwargs: Any):
        super().__init__(*args, instance=instance, **kwargs)
        self.budget = budget
        for category in budget.category_set.all():
            self.fields[str(category.id)] = forms.DecimalField(
                required=False, widget=forms.TextInput(attrs={'size': 7}))
        if instance:
            for part in instance.category_parts.all():
                self.initial[str(part.to_id)] = part.amount

    def rows(self):
        for category in self.budget.category_set.all():
            yield category.name, self[str(category.id)]

    def clean(self):
        if any(self.errors):
            return
        total = 0
        for category in self.budget.category_set.all():
            total += self.cleaned_data[str(category.id)] or 0
        if total:
            raise ValidationError("Amounts do not sum to zero")

    @transaction.atomic
    def save(self, commit: bool = False):
        super().save(commit=True)
        categories = {}
        for category in self.budget.category_set.all():
            categories[category] = self.cleaned_data[str(category.id)] or 0
        self.instance.set_parts(self.budget.id, {}, categories)


class TransactionForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date', 'description')
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))


class BudgetForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Budget
        fields = ('name',)
    name = forms.CharField(required=True)


class AccountForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = BaseAccount
        fields = ('name',)
    name = forms.CharField(required=True)


def rename_form(*, instance: BaseAccount,
                data: Union[Mapping[str, Any], None] = None) -> forms.ModelForm:
    if instance.ishidden():
        return BudgetForm(instance=instance.budget, data=data)
    return AccountForm(instance=instance, data=data)
