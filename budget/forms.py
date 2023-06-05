from collections import defaultdict
from typing import Any, Union, Mapping, Optional, Type
from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _
from django.forms import ValidationError

from .models import (Id, Budget, BaseAccount, Account, Category,
                     Transaction)


class AccountChoiceField(forms.Field):
    user_id: int
    type: Type[Id]

    def __init__(self, *, type: Type[Id], **kwargs: Any):
        self.type = type
        super().__init__(**kwargs, widget=forms.HiddenInput)

    def prepare_value(self, value: Any):
        if isinstance(value, str):
            return value
        if isinstance(value, BaseAccount) and value.is_inbox():
            return value.budget_id
        return value and value.id

    def to_python(self, value: Any):
        if not value:
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
        return Budget.objects.get_or_create(
            name=value, payee_of_id=self.user_id)[0]


class TransactionPartForm(forms.Form):
    account = AccountChoiceField(type=Account, required=False)
    category = AccountChoiceField(type=Category, required=False)
    transferred = forms.IntegerField(
        required=False, widget=forms.HiddenInput)
    moved = forms.IntegerField(
        required=False, widget=forms.HiddenInput)
    transferred_currency = forms.CharField(
        required=False, widget=forms.HiddenInput)
    moved_currency = forms.CharField(
        required=False, widget=forms.HiddenInput)
    note = forms.CharField(required=False)

    def __init__(self, *args: Any, initial: Optional[Transaction.Row] = None,
                 **kwargs: Any):
        values: dict[str, Any] = {}
        if initial:
            values = {'note': initial.note,
                      'account': initial.account, 'category': initial.category}
            if initial.account:
                values['transferred'] = initial.amount
                values['transferred_currency'] = initial.account.currency
            if initial.category:
                values['moved'] = initial.amount
                values['moved_currency'] = initial.category.currency
        super().__init__(*args, initial=values, **kwargs)

    def clean(self):
        data = self.cleaned_data
        if isinstance(data.get('account'), Budget):
            currency = data.get('transferred_currency', '')
            data['account'] = data['account'].get_inbox(Account, currency)
        if isinstance(data.get('category'), Budget):
            currency = data.get('moved_currency', '')
            data['category'] = data['category'].get_inbox(Category, currency)
        return data


class BaseTransactionPartFormSet(forms.BaseFormSet):
    budget: Budget

    def __init__(self, budget: Budget, *args: Any,
                 instance: Transaction, **kwargs: Any):
        self.budget = budget
        initial = instance and instance.tabular()
        super().__init__(*args, initial=initial, **kwargs)

    def add_fields(self, form: TransactionPartForm, index: int):
        super().add_fields(form, index)
        form.fields['account'].user_id = self.budget.owner()
        form.fields['category'].user_id = self.budget.owner()

    def save(self, *, instance: Transaction):
        # Make these one dict?
        accounts: dict[Account, int] = defaultdict(int)
        categories: dict[Category, int] = defaultdict(int)
        account_notes: dict[Account, str] = {}
        category_notes: dict[Category, str] = {}
        for form in self.forms:
            data: dict[str, Any] = form.cleaned_data
            account = data.get('account')
            if account and data.get('transferred'):
                # Leave it a list of tuples and do later?
                accounts[account] += data['transferred']
            category = data.get('category')
            if category and data.get('moved'):
                categories[category] += data['moved']
            if category and data.get('note'):
                category_notes[category] = data['note']
            elif account and data.get('note'):
                account_notes[account] = data['note']
        instance.set_parts(self.budget, accounts, categories)
        instance.accountnotes.set_notes(self.budget, account_notes)
        instance.categorynotes.set_notes(self.budget, category_notes)


TransactionPartFormSet = forms.formset_factory(
    TransactionPartForm, formset=BaseTransactionPartFormSet, extra=2)


class BudgetingForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Transaction
        fields = ()

    def __init__(self, *args: Any,
                 budget: Budget, instance: Optional[Transaction] = None, **kwargs: Any):
        super().__init__(*args, instance=instance, **kwargs)
        self.budget = budget
        for category in budget.category_set.all():
            self.fields[str(category.id)] = forms.IntegerField(
                required=False, widget=forms.HiddenInput(
                    attrs={'form': 'form'}))
        if instance:
            for category, amount in instance.categoryparts.entries().items():
                self.initial[str(category.id)] = amount

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


class TransactionForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date',)
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}),
                           initial=date.today)


class BudgetForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Budget
        fields = ('name',)
    name = forms.CharField()


class AccountForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = BaseAccount
        fields = ('name',)
    name = forms.CharField()


def rename_form(*, instance: BaseAccount,
                data: Union[Mapping[str, Any], None] = None
                ) -> Optional[forms.ModelForm]:
    if instance.is_inbox() and instance.budget.budget_of_id:
        return None
    elif instance.is_inbox():
        return BudgetForm(instance=instance.budget, data=data)
    return AccountForm(instance=instance, data=data)


ReorderingFormSet = forms.modelformset_factory(
    Category,
    fields=('group', 'order',),
    widgets={'group': forms.HiddenInput, 'order': forms.HiddenInput,
             'id_ptr': forms.HiddenInput},
    extra=0)


class AccountManagementForm(forms.ModelForm):
    def __init__(self, *args: Any, instance: BaseAccount, **kwargs: Any):
        super().__init__(*args, instance=instance, **kwargs)
        if instance.entries.exists():  # Optimize?
            self.fields['currency'].disabled = True


AccountManagementFormSet = forms.modelformset_factory(
    Account,
    form=AccountManagementForm,
    fields=('name', 'currency', 'closed'),
    widgets={'name': forms.TextInput(attrs={'required': True}),
             'currency': forms.TextInput(attrs={"list": "currencies",
                                                "size": 4})},
    extra=0)

CategoryManagementFormSet = forms.modelformset_factory(
    Category,
    form=AccountManagementForm,
    fields=('name', 'currency', 'closed'),
    widgets={'name': forms.TextInput(attrs={'required': True}),
             'currency': forms.TextInput(attrs={"list": "currencies",
                                                "size": 4})},
    extra=0)


class OnTheGoForm(forms.Form):
    budget: Budget
    amount = forms.IntegerField(widget=forms.HiddenInput)
    note = forms.CharField(required=False)
    currency = forms.CharField(widget=forms.TextInput(
        attrs={"list": "currencies"}))

    def __init__(self, *args: Any, budget: Budget, **kwargs: Any):
        self.budget = budget
        if budget.initial_currency:
            currency = budget.initial_currency
        else:
            category = budget.category_set.first()
            if category:
                currency = category.currency
            else:
                currency = 'CHF'
        initial = {'currency': currency}
        super().__init__(*args, initial=initial, **kwargs)

    def save(self):
        transaction = Transaction(date=date.today())
        transaction.save()
        currency = self.cleaned_data['currency']
        self.budget.initial_currency = currency
        self.budget.save()
        amount = self.cleaned_data['amount']
        payee = Budget.objects.get_or_create(
            name="Payee", payee_of_id=self.budget.owner())[0]
        accounts = {self.budget.get_inbox(Account, currency): -amount,
                    payee.get_inbox(Account, currency): amount}
        categories = {self.budget.get_inbox(Category, currency): -amount,
                      payee.get_inbox(Category, currency): amount}
        transaction.set_parts(self.budget, accounts, categories)
        if self.cleaned_data['note']:
            notes = {self.budget.get_inbox(Category, currency):
                     self.cleaned_data['note']}
            transaction.categorynotes.set_notes(self.budget, notes)
