from typing import Any, Union, Mapping, Optional, Type, Iterable
from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from django.forms import ValidationError

from .models import (Id, Budget, BaseAccount, Account, Category,
                     Transaction, budgeting_transactions)


class AccountChoiceField(forms.Field):
    user_id: int
    type: Type[BaseAccount]

    def __init__(self, *, type: Type[BaseAccount], **kwargs: Any):
        self.type = type
        super().__init__(**kwargs, widget=forms.HiddenInput)

    def prepare_value(self, value: Any):
        if isinstance(value, str):
            return value
        if (isinstance(value, self.type)
                and value.budget.budget_of_id != self.user_id):
            return value.budget_id
        return value and value.id

    def to_python(self, value: Any):
        if value == '':
            return None
        try:
            return self.type.objects.get(id=value)
        except (TypeError, ValueError, self.type.DoesNotExist):
            pass
        try:
            return Budget.objects.get(id=value)
        except (TypeError, ValueError, Id.DoesNotExist):
            pass
        if (self.type == Category
                and value.startswith('[') and value.endswith(']')):
            value = value[1:-1]
        return Budget.objects.get_or_create(name=value, payee_of=self.user_id)[0]


class TransactionPartForm(forms.Form):
    account = AccountChoiceField(type=Account, required=False)
    category = AccountChoiceField(type=Category, required=False)
    transferred = forms.DecimalField(
        required=False, widget=forms.HiddenInput)
    moved = forms.DecimalField(
        required=False, widget=forms.HiddenInput)
    transferred_currency = forms.CharField(
        required=False, widget=forms.HiddenInput)
    moved_currency = forms.CharField(
        required=False, widget=forms.HiddenInput)

    def clean(self):
        data = self.cleaned_data
        if isinstance(data.get('account'), Budget):
            currency = data.get('transferred_currency', '')
            data['account'] = data['account'].get_hidden(Account, currency)
        if isinstance(data.get('category'), Budget):
            currency = data.get('moved_currency', '')
            data['category'] = data['category'].get_hidden(Category, currency)
        return data


class BaseTransactionPartFormSet(forms.BaseFormSet):
    budget: Budget

    def __init__(self, budget: Budget, *args: Any,
                 instance: Transaction, **kwargs: Any):
        self.budget = budget
        if instance:
            initial = instance.tabular(budget)
            for row in initial:
                if row['account']:
                    row['transferred'] = row['amount']
                    row['transferred_currency'] = row['account'].currency
                if row['category']:
                    row['moved'] = row['amount']
                    row['moved_currency'] = row['category'].currency
        else:
            initial = None
        super().__init__(*args, initial=initial, **kwargs)

    def add_fields(self, form: TransactionPartForm, index: int):
        super().add_fields(form, index)
        form.fields['account'].user_id = self.budget.owner()
        form.fields['category'].user_id = self.budget.owner()

    @transaction.atomic
    def save(self, *, instance: Transaction):
        accounts: dict[Account, int] = {}
        categories: dict[Category, int] = {}
        for form in self.forms:
            account = form.cleaned_data.get('account')
            if account and form.cleaned_data.get('transferred'):
                accounts[account] = form.cleaned_data['transferred']
            category = form.cleaned_data.get('category')
            if category and form.cleaned_data.get('moved'):
                categories[category] = form.cleaned_data['moved']
        instance.set_parts(self.budget, accounts, categories)


TransactionPartFormSet = forms.formset_factory(
    TransactionPartForm, formset=BaseTransactionPartFormSet, extra=2)


class BudgetingForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date', 'description')
    date = forms.DateField(widget=forms.HiddenInput())

    def __init__(self, *args: Any,
                 budget: Budget, instance: Optional[Transaction] = None, **kwargs: Any):
        super().__init__(*args, instance=instance, **kwargs)
        self.budget = budget
        for category in budget.category_set.all():
            self.fields[str(category.id)] = forms.DecimalField(
                required=False, widget=forms.HiddenInput(
                    attrs={'form': 'form'}))
        if instance:
            for part in instance.category_parts.all():
                self.initial[str(part.to_id)] = part.amount

    def rows(self):
        for category in self.budget.category_set.order_by('name'):
            yield category.name, self[str(category.id)]

    def clean(self):
        if any(self.errors):
            return self.cleaned_data
        total = 0
        for category in self.budget.category_set.all():
            total += self.cleaned_data[str(category.id)] or 0
        if total:
            raise ValidationError("Amounts do not sum to zero")
        return self.cleaned_data

    def save(self, commit: bool = False):
        self.instance.kind = Transaction.Kind.BUDGETING
        super().save(commit=True)
        categories = {}
        for category in self.budget.category_set.all():
            categories[category] = self.cleaned_data[str(category.id)] or 0
        self.instance.set_parts(self.budget, {}, categories)


class BaseBudgetingFormSet(forms.BaseModelFormSet):
    forms_by_date: 'dict[date, BudgetingForm]'

    def __init__(self, budget: Budget, *args: Any,
                 dates: 'Iterable[date]' = [], **kwargs: Any):
        queryset = budgeting_transactions(budget.id)
        extras = set(dates) - {transaction.month for transaction in queryset}
        initial = [{'date': date} for date in sorted(extras)]
        self.extra = len(initial)
        super().__init__(*args, initial=initial, form_kwargs={'budget': budget},
                         queryset=queryset, **kwargs)
        self.forms_by_date = {
            form.instance.month or form.initial.get('date'): form
            for form in self.forms}

    @transaction.atomic
    def save(self, commit: bool = False):
        super().save(commit)


BudgetingFormSet: 'Type[BaseBudgetingFormSet]'
BudgetingFormSet = forms.modelformset_factory(  # type: ignore
    Transaction, BudgetingForm, formset=BaseBudgetingFormSet, extra=0)


class TransactionForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date', 'description')
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}),
                           initial=date.today)


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
