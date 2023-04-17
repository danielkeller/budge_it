from typing import Any, Union, Mapping, Optional, Type, Iterable
from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from django.forms import ValidationError
from django.contrib.auth.models import User

from .models import (Id, Budget, BaseAccount, Account, Category,
                     Transaction, budgeting_transactions)


class AccountChoiceField(forms.Field):
    user: User
    type: Type[BaseAccount]

    def __init__(self, *, type: Type[BaseAccount], **kwargs: Any):
        self.type = type
        super().__init__(**kwargs, widget=forms.HiddenInput)
    
    def prepare_value(self, value: Any):
        if isinstance(value, str):
            return value
        if (isinstance(value, self.type)
             and value.budget.budget_of != self.user):
            return value.budget_id
        return value and value.id

    def to_python(self, value: Any):
        if value == '':
            return None
        try:
            # TODO: permissions (?)
            return self.type.get(value)
        except (TypeError, ValueError, Id.DoesNotExist):
            pass
        if (self.type == Category
                and value.startswith('[') and value.endswith(']')):
            value = value[1:-1]
        return Budget.objects.get_or_create(name=value, payee_of=self.user)[0]


class TransactionPartForm(forms.Form):
    account = AccountChoiceField(type=Account, required=False)
    category = AccountChoiceField(type=Category, required=False)
    transferred = forms.DecimalField(
        required=False, widget=forms.TextInput(attrs={'class': 'number'}))
    moved = forms.DecimalField(
        required=False, widget=forms.TextInput(attrs={'class': 'number'}))
    # transferred_currency = forms.CharField(
    #     required=False, widget=forms.HiddenInput)
    # moved_currency = forms.CharField(
    #     required=False, widget=forms.HiddenInput)


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
                if row['category']:
                    row['moved'] = row['amount']
        else:
            initial = None
        super().__init__(*args, initial=initial, **kwargs)

    def add_fields(self, form: TransactionPartForm, index: int):
        super().add_fields(form, index)
        form.fields['account'].user = self.budget.owner()
        form.fields['category'].user = self.budget.owner()

    def clean(self):
        if any(self.errors):
            return
        category_total, account_total = 0, 0
        for form in self.forms:
            category = form.cleaned_data.get('category')
            if category:
                if isinstance(category, Budget):
                    form.cleaned_data['category'] = category.get_hidden(Category)
                category_total += form.cleaned_data.get('moved', 0)
            account = form.cleaned_data.get('account')
            if account:
                if isinstance(account, Budget):
                    form.cleaned_data['account'] = account.get_hidden(Account)
                account_total += form.cleaned_data.get('transferred', 0)
        if account_total or category_total:
            raise ValidationError("Amounts do not sum to zero")

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
                required=False, widget=forms.TextInput(
                    attrs={'class': 'number', 'form': 'form'}))
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
        self.instance.set_parts(self.budget.id, {}, categories)


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
