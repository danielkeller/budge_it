from dataclasses import dataclass
from collections import defaultdict
from typing import Any, Union, Mapping, Optional, Type, cast
from datetime import date
from itertools import chain

from django import forms
from django.utils.translation import gettext_lazy as _
from django.forms import ValidationError, BoundField
from django.db import transaction
from django.forms.models import model_to_dict

from .models import (Id, Budget, BaseAccount, Account, Category, Balance,
                     TransactionPart, Transaction, AccountLike, Row,
                     AccountT,
                     MultiTransaction,
                     budgeting_categories)
from .recurrence import RRule


class AccountChoiceField(forms.Field):
    user_id: Optional[int]
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
        return Budget.objects.get_or_create(
            name=value, payee_of_id=self.user_id)[0]


class EntryForm(forms.Form):
    account = AccountChoiceField(type=Account, required=False)
    category = AccountChoiceField(type=Category, required=False)
    transferred = forms.IntegerField(
        required=False, widget=forms.HiddenInput)
    moved = forms.IntegerField(
        required=False, widget=forms.HiddenInput)

    def __init__(self, *args: Any, initial: Optional[Row] = None,
                 **kwargs: Any):
        values: dict[str, Any] = {}
        self.row = initial
        if initial:
            values = {'account': initial.account, 'category': initial.category}
            if initial.account:
                values['transferred'] = initial.amount
            if initial.category:
                values['moved'] = initial.amount
        super().__init__(*args, initial=values, **kwargs)


class BaseEntryFormSet(forms.BaseFormSet):
    budget: Budget

    def __init__(self, budget: Budget,
                 initial: list[Row],
                 use_required_attribute: Any = None,
                 renderer: Any = None,
                 **kwargs: Any):
        self.budget = budget
        super().__init__(initial=initial, **kwargs)

    def add_fields(self, form: EntryForm, index: int):
        super().add_fields(form, index)
        if self.budget:
            form.fields['account'].user_id = self.budget.owner()
            form.fields['category'].user_id = self.budget.owner()


EntryFormSet = forms.formset_factory(
    EntryForm, formset=BaseEntryFormSet, extra=1, min_num=1, max_num=15)
MultiEntryFormSet = forms.formset_factory(
    EntryForm, formset=BaseEntryFormSet, extra=0, min_num=1, max_num=100)


class FormSetInline(forms.Form):
    """Form lifecycle boilerplate to hold a formset as a property."""
    formset: forms.BaseFormSet

    def is_valid(self):
        return super().is_valid() and self.formset.is_valid()

    def has_changed(self):
        return super().has_changed() or self.formset.has_changed()


def _to_account(cls: Type[AccountT], value: AccountT | Budget, currency: str):
    if isinstance(value, Budget):
        return value.get_inbox(cls, currency)
    return cast(cls, value)


class PartForm(FormSetInline):
    formset: BaseEntryFormSet
    budget: Budget
    instance: TransactionPart

    id = forms.ModelChoiceField(required=False,
                                queryset=TransactionPart.objects.none(),
                                widget=forms.HiddenInput)
    note = forms.CharField(required=False,
                           widget=forms.Textarea(attrs={'rows': 0}))
    currency = forms.ChoiceField(required=True, widget=forms.Select(
        attrs={'class': 'part-currency'}))

    def __init__(self, budget: Budget, *args: Any,
                 initial: Optional[TransactionPart] = None,
                 **kwargs: Any):
        self.budget = budget
        self.instance = initial or TransactionPart()
        values = model_to_dict(self.instance)
        values['currency'] = budget.get_initial_currency()
        entry = next(chain(*self.instance.entries()), None)
        if entry:
            values['currency'] = entry.currency
        super().__init__(*args, initial=values, **kwargs)
        self.formset = EntryFormSet(budget=budget,
                                    initial=self.instance.tabular(),
                                    prefix=kwargs.get('prefix'),
                                    data=kwargs.get('data'))
        if initial:
            self.fields['id'].queryset = (
                TransactionPart.objects.filter(pk=initial.pk))
        currencies = budget.currencies
        self.fields['currency'].choices = list(zip(currencies, currencies))
        if values['currency'] not in currencies:
            self.fields['currency'].choices += [
                (values['currency'], values['currency'])]

    def clean(self):
        if self.is_bound:
            self.instance.note = self.cleaned_data['note']

    def save(self, transaction: Transaction):
        self.instance.transaction = transaction
        self.instance.save()
        currency: str = self.cleaned_data['currency']
        accounts: dict[Account, int] = defaultdict(int)
        categories: dict[Category, int] = defaultdict(int)
        for form in self.formset.forms:
            data: dict[str, Any] = form.cleaned_data
            account = data.get('account')
            if account and data.get('transferred'):
                # Leave it a list of tuples and do later?
                account = _to_account(Account, account, currency)
                accounts[account] += data['transferred']
            category = data.get('category')
            if category and data.get('moved'):
                category = _to_account(Category, category, currency)
                categories[category] += data['moved']
        self.instance.set_entries(self.budget, accounts, categories)


class BasePartFormSet(forms.BaseFormSet):
    def __init__(self, budget: Budget,
                 instance: Optional[Transaction] = None,
                 **kwargs: Any):
        kwargs['initial'] = instance.visible_parts if instance else []
        form_kwargs = {'budget': budget}
        super().__init__(form_kwargs=form_kwargs, **kwargs)

    def save(self, transaction: Transaction):
        for form in self.forms:
            form.save(transaction)


PartFormSet = forms.formset_factory(
    form=PartForm, formset=BasePartFormSet,
    min_num=1, extra=0, max_num=15)


class TransactionForm(forms.ModelForm, FormSetInline):
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date', 'recurrence',)

    formset: BasePartFormSet
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'},
                                                  format='%Y-%m-%d'),
                           initial=date.today)

    repeat = forms.ChoiceField(choices=[('N', 'None'),
                                        ('R', 'Every'),
                                        ('C', 'Custom')])
    interval = forms.IntegerField(min_value=1, initial=1,
                                  widget=forms.NumberInput(attrs={'size': 5}))
    freq = forms.ChoiceField(choices=[('YEARLY', 'Year'),
                                      ('MONTHLY', 'Month'),
                                      ('WEEKLY', 'Week')])
    recurrence = forms.CharField(required=False)

    def __init__(self, *args: Any, instance: Optional[Transaction] = None,
                 budget: Budget,
                 **kwargs: Any):
        instance = instance or Transaction()
        initial = kwargs.setdefault('initial', {})
        if instance.recurrence:
            rrule = instance.recurrence
            if (self.base_fields['freq'].valid_value(rrule.freq)  # type: ignore
                    and rrule == RRule(freq=rrule.freq, interval=rrule.interval)):
                initial['freq'] = rrule.freq
                initial['interval'] = rrule.interval or 1
                initial['repeat'] = 'R'
            else:
                initial['repeat'] = 'C'
        else:
            initial['repeat'] = 'N'
            initial['freq'] = 'MONTHLY'
        super().__init__(*args, instance=instance, **kwargs)
        self.formset = PartFormSet(budget=budget, instance=instance, **kwargs)
        if instance.id and not instance.recurrence:
            self.fields['repeat'].disabled = True
        if not instance.id:
            self.fields['date'].widget.attrs['autofocus'] = ''

    def clean(self):
        if self.cleaned_data['repeat'] == 'N':
            self.cleaned_data['recurrence'] = None
        elif self.cleaned_data['repeat'] == 'R':
            self.cleaned_data['recurrence'] = RRule(
                freq=self.cleaned_data['freq'],
                interval=self.cleaned_data['interval'])
        return self.cleaned_data

    @transaction.atomic
    def save(self, commit: bool = True):
        instance: Transaction = super().save(commit)
        self.formset.save(instance)
        if not instance.parts.exists():
            instance.delete()
        return instance


class BaseMultiFormSet(forms.BaseFormSet):
    is_multi = True

    def __init__(self, budget: Budget, instance: MultiTransaction, **kwargs: Any):
        self.budget = budget
        self.instance = instance
        super().__init__(form_kwargs={'budget': budget},
                         initial=instance.parts(),
                         **kwargs)

    @transaction.atomic
    def save(self):
        changes = {}
        for form in chain(*self.forms):
            currency: str = form.row.currency
            for field in form.changed_data:
                type = Account if field == 'account' else Category
                before = _to_account(type, form.initial[field], currency)
                after = _to_account(type, form.cleaned_data[field], currency)
                changes[before] = after
        for transaction in self.instance.contents:
            for part in transaction.visible_parts:
                init_accounts, init_categories = part.entries()
                accounts: dict[Account, int] = defaultdict(int)
                for account, amount in init_accounts.items():
                    accounts[changes.get(account, account)] += amount
                categories: dict[Category, int] = defaultdict(int)
                for category, amount in init_categories.items():
                    categories[changes.get(category, category)] += amount
                part.set_entries(self.budget, accounts, categories)
        return self.instance


MultiFormSet = forms.formset_factory(
    MultiEntryFormSet, formset=BaseMultiFormSet, extra=0)


class BudgetingForm(forms.ModelForm):
    @dataclass
    class Row:
        category: Category
        field: BoundField

        @property
        def total(self):
            return self.category.balance + self.category.change

        @property
        def final(self):
            try:
                return self.total + int(self.field.value())
            except (ValueError, TypeError):
                return self.total

    class Meta:  # type: ignore
        model = Transaction
        fields = ('date',)

    instance: Transaction

    date = forms.DateField(widget=forms.HiddenInput)

    def __init__(self, budget: Budget, *args: Any,
                 instance: Transaction, **kwargs: Any):
        super().__init__(*args, instance=instance, **kwargs)
        self.categories = budgeting_categories(budget, instance)
        self.budget = budget
        for category in self.categories:
            self.fields[str(category.id)] = forms.IntegerField(
                required=False, widget=forms.HiddenInput(
                    attrs={'form': 'form'}))
        if instance.pk:
            for category, amount in instance.visible_parts[0].entries()[1].items():
                self.initial[str(category.id)] = amount
        self.rows = [BudgetingForm.Row(category, self[str(category.id)])
                     for category in self.categories]

    def clean(self):
        if any(self.errors):
            return self.cleaned_data
        total = 0
        for category in self.categories:
            total += self.cleaned_data[str(category.id)] or 0
        if total:
            raise ValidationError("Amounts do not sum to zero")
        return self.cleaned_data

    @transaction.atomic
    def save(self):
        self.instance.kind = Transaction.Kind.BUDGETING
        super().save(commit=True)
        entries = {}
        for category in self.categories:
            entries[category] = self.cleaned_data[str(category.id)] or 0
        part, _ = (TransactionPart.objects
                   .get_or_create(transaction=self.instance))
        # TODO: Factor this out with the transaction form
        part = part.set_entries(self.budget, {}, entries)
        if not part:
            self.instance.delete()
        return self.instance


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


class BaseAccountManagementForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = BaseAccount
        fields = ('name', 'currency', 'order', 'group', 'closed')
        widgets = {'name': forms.TextInput(attrs={'required': True,
                                                  'autofocus': ''}),
                   'group': forms.HiddenInput(attrs={'class': 'group'}),
                   'order': forms.HiddenInput(attrs={'class': 'order'})}
    currency = forms.ChoiceField()


class AccountManagementForm(BaseAccountManagementForm):
    class Meta:  # type: ignore
        model = Account
        fields = ('name', 'currency', 'order', 'clearable', 'closed')
        widgets = {'name': forms.TextInput(attrs={'required': True,
                                                  'autofocus': ''}),
                   'order': forms.HiddenInput(attrs={'class': 'order'})}


class BaseAccountManagementFormSet(forms.BaseInlineFormSet):
    def add_fields(self, form: forms.ModelForm, index: int):
        super().add_fields(form, index)
        currencies = self.instance.currencies
        form.fields['currency'].choices = list(zip(currencies, currencies))
        if not self.is_bound:  # Hack: Fake out is_changed
            form.initial['order'] = index
        if form.instance.pk:
            if form.instance.name == '' or form.instance.entries.exists():  # Optimize?
                form.fields['currency'].disabled = True
                form.fields['DELETE'].disabled = True
            if form.instance.currency not in currencies:
                form.fields['currency'].choices += [(
                    form.instance.currency, form.instance.currency)]
        else:
            form.initial['currency'] = self.instance.get_initial_currency()

    def save_existing(self, form: BaseAccountManagementForm,
                      instance: BaseAccount,
                      commit: bool = False) -> BaseAccount:
        instance = super().save_existing(form, instance, commit)
        if isinstance(instance, Account) and 'clearable' in form.changed_data:
            if instance.clearable:
                entries = (Transaction.objects
                           .filter(parts__accounts=instance)
                           .distinct())
                instance.cleared_transaction.set(entries)
            else:
                instance.cleared_transaction.clear()
        return instance


AccountManagementFormSet = forms.inlineformset_factory(
    Budget, Account, fk_name="budget",
    formset=BaseAccountManagementFormSet, form=AccountManagementForm,
    extra=0)

CategoryManagementFormSet = forms.inlineformset_factory(
    Budget, Category, fk_name='budget',
    formset=BaseAccountManagementFormSet, form=BaseAccountManagementForm,
    extra=0)


class BaseCurrencyManagementFormSet(forms.BaseInlineFormSet):
    def add_fields(self, form: forms.ModelForm, index: int):
        super().add_fields(form, index)
        if form.instance.pk:
            form.fields['currency'].disabled = True
            budget: Budget = form.instance.budget
            currency: str = form.instance.currency
            if (budget.account_set
                    .filter(currency=currency).exclude(name='')
                    .exists()
                or budget.category_set
                    .filter(currency=currency).exclude(name='')
                    .exists()
                or budget.get_inbox(Category, currency).entries.exists()
                    or budget.get_inbox(Account, currency).entries.exists()):
                form.fields['DELETE'].disabled = True


CurrencyManagementFormSet = forms.inlineformset_factory(
    Budget,
    Category,
    fk_name='budget',
    formset=BaseCurrencyManagementFormSet,
    fields=('currency',),
    widgets={'currency': forms.TextInput(attrs={'list': 'currencies',
                                                'size': 4,
                                                'required': True,
                                                'autofocus': ''})},
    extra=0)


def _get_budget(id: int):
    return Budget.objects.get(id=id)


class QuickAddForm(forms.Form):
    account: AccountLike
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'},
                                                  format='%Y-%m-%d'),
                           required=True,
                           initial=date.today)
    note = forms.CharField(required=False)
    amount = forms.IntegerField(widget=forms.HiddenInput)
    is_split = forms.BooleanField(required=False,
                                  widget=forms.CheckboxInput(attrs={'class': 'disclosure'}))
    split = forms.TypedMultipleChoiceField(required=False, choices=[],
                                           coerce=_get_budget,
                                           widget=forms.CheckboxSelectMultiple)

    def __init__(self, account: AccountLike, *args: Any, autofocus: bool = False, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.account = account
        budget = account.budget

        choices = (
            [(budget.id, cast(str, 'Yourself'))]
            + list(budget.friends.values_list('id', 'name')))

        initial_split = []
        if budget.initial_split:
            initial_split = list(map(int, budget.initial_split.split(',')))
        if isinstance(account, Balance):
            if account.other.id not in initial_split:
                initial_split.append(account.other.id)
            if not any(id == account.other.id for id, _ in choices):
                choices.append((account.other.id, account.other.name))

        self.fields['split'].choices = choices
        self.fields['split'].initial = initial_split
        self.fields['is_split'].initial = bool(initial_split)
        if autofocus:
            self.fields['date'].widget.attrs['autofocus'] = ''

    @transaction.atomic
    def save(self):
        transaction = Transaction(date=self.cleaned_data['date'])
        transaction.save()

        part = TransactionPart(transaction=transaction)
        if self.cleaned_data['note']:
            part.note = self.cleaned_data['note']
        part.save()

        budget = self.account.budget
        currency = self.account.currency

        if self.cleaned_data['is_split']:
            split: list[Budget] = self.cleaned_data['split']
            budget.initial_split = ','.join(str(friend.id) for friend in split)
        else:
            split = [budget]
            budget.initial_split = ''
        budget.save()

        amount = -self.cleaned_data['amount']
        payee = Budget.objects.get_or_create(
            name="Payee", payee_of_id=budget.owner())[0]

        own_category = budget.get_inbox(Category, currency)
        own_account = budget.get_inbox(Account, currency)

        if isinstance(self.account, Account):
            own_account = self.account
        elif isinstance(self.account, Category):
            own_category = self.account

        accounts = {own_account: amount,
                    payee.get_inbox(Account, currency): -amount}
        categories = {payee.get_inbox(Category, currency): -amount}

        from_categories = [
            friend.get_inbox(Category, currency)
            for friend in split
            if friend != budget]
        if budget in split or not from_categories:
            from_categories.append(own_category)

        div = amount // len(from_categories)
        rem = amount - div * len(from_categories)
        for i in range(len(from_categories)):
            categories[from_categories[i]] = div + (i < rem)

        part.set_entries(budget, accounts, categories)
        return transaction
