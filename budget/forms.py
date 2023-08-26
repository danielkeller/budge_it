from collections import defaultdict
from typing import Any, Dict, Union, Mapping, Optional, Type, TypeVar, Iterable
from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _
from django.forms import ValidationError
from django.db import transaction

from .models import (Id, Budget, BaseAccount, Account, Category,
                     TransactionPart, Transaction)
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

    def __init__(self, *args: Any, initial: Optional[TransactionPart.Row] = None,
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
    instance: Optional[TransactionPart]
    currency: str

    def __init__(self, budget: Budget,
                 instance: Optional[TransactionPart] = None,
                 **kwargs: Any):
        self.budget = budget
        self.instance = instance
        if instance:
            kwargs['initial'] = instance.tabular()
        super().__init__(**kwargs)

    def add_fields(self, form: EntryForm, index: int):
        super().add_fields(form, index)
        if self.budget:
            form.fields['account'].user_id = self.budget.owner()
            form.fields['category'].user_id = self.budget.owner()

    def full_clean(self):
        super().full_clean()
        for data in self.cleaned_data:
            account = data.get('account')
            if account:
                if isinstance(account, Budget):
                    data['account'] = account.get_inbox(Account, self.currency)
                elif account.currency != self.currency:
                    raise ValidationError(
                        f'Account currency {account.currency} does not match '
                        + self.currency)
            category = data.get('category')
            if category:
                if isinstance(category, Budget):
                    data['category'] = category.get_inbox(
                        Category, self.currency)
                elif category.currency != self.currency:
                    raise ValidationError(
                        f'Category currency {category.currency} does not match '
                        + self.currency)


EntryFormSet = forms.formset_factory(
    EntryForm, formset=BaseEntryFormSet, extra=1, min_num=1, max_num=15)


FormSetT = TypeVar('FormSetT', bound=forms.BaseInlineFormSet)


def FormSetInline(formset: Type[FormSetT]):
    """Form lifecycle boilerplate to hold a formset as a property."""
    class FormSetInlineImpl(forms.ModelForm):
        formset: FormSetT

        def __init__(self,
                     budget: Budget,
                     renderer: Any = None,
                     use_required_attribute: Optional[bool] = None,
                     empty_permitted: bool = False,
                     initial: Optional[dict[str, Any]] = None,
                     **kwargs: Any):
            super().__init__(**kwargs, initial=initial, renderer=renderer,
                             empty_permitted=empty_permitted,
                             use_required_attribute=use_required_attribute)
            self.formset = formset(budget, **kwargs)

        def is_valid(self):
            return super().is_valid() and self.formset.is_valid()

        def has_changed(self):
            return super().has_changed() or self.formset.has_changed()

    return FormSetInlineImpl


class BasePartFormSet(forms.BaseInlineFormSet):
    budget: Budget

    def __init__(self, budget: Budget,
                 instance: Optional[Transaction] = None,
                 **kwargs: Any):
        self.budget = budget
        super().__init__(instance=instance, **kwargs)
        # BaseInlineFormSet breaks the prefetches so unbreak it here
        if instance:
            self.queryset = instance.parts.all()
        else:
            self.queryset = self.model.objects.none()

    def get_form_kwargs(self, index: Any) -> Any:
        return {'budget': self.budget}


class PartForm(FormSetInline(EntryFormSet)):
    class Meta:  # type: ignore
        model = TransactionPart
        fields = ('note',)

    budget: Budget
    note = forms.CharField(required=False,
                           widget=forms.Textarea(attrs={'rows': 0}))
    currency = forms.ChoiceField(required=False)

    def __init__(self, budget: Budget, *args: Any,
                 instance: Optional[TransactionPart] = None,
                 initial: dict[str, Any] = {},
                 **kwargs: Any):
        self.budget = budget
        initial['currency'] = budget.get_initial_currency()
        if instance:
            entry = (instance.accountentry_set.first()
                     or instance.categoryentry_set.first())
            if entry:
                initial['currency'] = entry.sink.currency
        super().__init__(budget, *args, instance=instance, initial=initial,
                         **kwargs)
        currencies = budget.currencies
        self.fields['currency'].choices = list(zip(currencies, currencies))
        if initial['currency'] not in currencies:
            self.fields['currency'].choices += [
                (initial['currency'], initial['currency'])]

    def full_clean(self):
        super().full_clean()
        # Kind of a hack
        self.formset.currency = self.cleaned_data.get(
            'currency')  # type: ignore

    def save(self, commit: bool = True) -> Optional[TransactionPart]:
        instance: TransactionPart = super().save(commit)
        accounts: dict[Account, int] = defaultdict(int)
        categories: dict[Category, int] = defaultdict(int)
        for form in self.formset.forms:
            data: dict[str, Any] = form.cleaned_data
            account = data.get('account')
            if account and data.get('transferred'):
                # Leave it a list of tuples and do later?
                accounts[account] += data['transferred']
            category = data.get('category')
            if category and data.get('moved'):
                categories[category] += data['moved']
        return instance.set_entries(self.budget, accounts, categories)


PartFormSet = forms.inlineformset_factory(
    Transaction, TransactionPart,
    form=PartForm, formset=BasePartFormSet,
    min_num=1, extra=0, max_num=5)


class TransactionForm(FormSetInline(PartFormSet)):
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date', 'recurrence',)
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date',
                                                         'autofocus': ''},
                                                  format='%Y-%m-%d'),
                           initial=date.today)

    repeat = forms.ChoiceField(choices=[('N', "Don't repeat"),
                                        ('R', 'Repeat every'),
                                        ('C', 'Custom repeat')])
    interval = forms.IntegerField(min_value=1, initial=1,
                                  widget=forms.NumberInput(attrs={'size': 5}))
    freq = forms.ChoiceField(choices=[('YEARLY', 'Year'),
                                      ('MONTHLY', 'Month'),
                                      ('WEEKLY', 'Week')])
    recurrence = forms.CharField(required=False)

    def __init__(self, *args: Any, instance: Optional[Transaction] = None,
                 **kwargs: Any):
        initial = kwargs.setdefault('initial', {})
        if instance and instance.recurrence:
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
        if instance and not instance.recurrence:
            self.fields['repeat'].disabled = True

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
        instance = super().save(commit)
        self.formset.instance = instance
        children = self.formset.save()
        if all(not part or not part.pk for part in children):
            instance.delete()
        return instance


class BudgetingForm(forms.ModelForm):
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date',)

    instance: Transaction

    date = forms.DateField(widget=forms.HiddenInput)

    def __init__(self, *args: Any,
                 categories: Iterable[Category],
                 instance: Optional[Transaction] = None, **kwargs: Any):
        super().__init__(*args, instance=instance, **kwargs)
        self.categories = categories
        for category in categories:
            self.fields[str(category.id)] = forms.IntegerField(
                required=False, widget=forms.HiddenInput(
                    attrs={'form': 'form'}))
        if instance:
            for category, amount in (instance.parts.get()
                                     .categoryentry_set.entries().items()):
                self.initial[str(category.id)] = amount

    def clean(self):
        if any(self.errors):
            return self.cleaned_data
        total = 0
        for category in self.categories:
            total += self.cleaned_data[str(category.id)] or 0
        if total:
            raise ValidationError("Amounts do not sum to zero")
        return self.cleaned_data

    def save_entries(self, budget: Budget):
        self.instance.kind = Transaction.Kind.BUDGETING
        super().save(commit=True)
        entries = {}
        for category in self.categories:
            entries[category] = self.cleaned_data[str(category.id)] or 0
        part, _ = (TransactionPart.objects
                   .get_or_create(transaction=self.instance))
        part.set_entries(budget, {}, entries)


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
        fields = ('name', 'currency', 'closed')
        widgets = {'name': forms.TextInput(attrs={'required': True,
                                                  'autofocus': ''})}
    currency = forms.ChoiceField()


class AccountManagementForm(BaseAccountManagementForm):
    class Meta:  # type: ignore
        model = Account
        fields = ('name', 'currency', 'clearable', 'closed')
        widgets = {'name': forms.TextInput(attrs={'required': True,
                                                  'autofocus': ''})}


class BaseAccountManagementFormSet(forms.BaseInlineFormSet):
    def add_fields(self, form: forms.ModelForm, index: int):
        super().add_fields(form, index)
        currencies = self.instance.currencies
        form.fields['currency'].choices = list(zip(currencies, currencies))
        if form.instance.pk:
            if form.instance.entries.exists():  # Optimize?
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
                instance.cleared.set(entries)
            else:
                instance.cleared.clear()
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

    def save_new(self, form: forms.ModelForm, commit: bool = True) -> Category:
        try:
            form.instance = Category.objects.get(
                budget=self.instance, name='', currency=form.instance.currency)
        except Category.DoesNotExist:
            pass
        form.instance.closed = False
        return super().save_new(form, commit)

    def delete_existing(self, obj: Category, commit: bool = True):
        obj.closed = True
        if commit:
            obj.save()


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


class OnTheGoForm(forms.Form):
    budget: Budget
    amount = forms.IntegerField(widget=forms.HiddenInput)
    note = forms.CharField(required=False)
    currency = forms.ChoiceField()
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'},
                                                  format='%Y-%m-%d'),
                           required=True,
                           initial=date.today)
    split = forms.TypedMultipleChoiceField(required=False, choices=[],
                                           coerce=_get_budget,
                                           widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args: Any, budget: Budget, **kwargs: Any):
        self.budget = budget
        initial = {'currency': budget.get_initial_currency()}
        super().__init__(*args, initial=initial, **kwargs)
        self.fields['split'].choices = (
            [(budget.id, 'Yourself')]
            + list(budget.friends.values_list('id', 'name')))
        if budget.initial_split:
            self.fields['split'].initial = budget.initial_split.split(',')
        else:
            self.fields['split'].initial = [budget.id]
        currencies = budget.currencies
        self.fields['currency'].choices = list(zip(currencies, currencies))

    @transaction.atomic
    def save(self):
        transaction = Transaction(date=self.cleaned_data['date'])
        transaction.save()

        part = TransactionPart(transaction=transaction)
        if self.cleaned_data['note']:
            part.note = self.cleaned_data['note']
        part.save()

        currency = self.cleaned_data['currency']
        split = self.cleaned_data['split']
        self.budget.initial_currency = currency
        self.budget.initial_split = ','.join(
            str(friend.id) for friend in split)
        self.budget.save()

        amount = self.cleaned_data['amount']
        payee = Budget.objects.get_or_create(
            name="Payee", payee_of_id=self.budget.owner())[0]

        accounts = {self.budget.get_inbox(Account, currency): -amount,
                    payee.get_inbox(Account, currency): amount}
        categories = {payee.get_inbox(Category, currency): amount}

        from_categories: list[Category] = [
            budget.get_inbox(Category, currency)
            for budget in split
        ] or [self.budget.get_inbox(Category, currency)]

        div = amount // len(from_categories)
        rem = amount - div * len(from_categories)
        for i in range(len(from_categories)):
            categories[from_categories[i]] = -div - (i < rem)

        part.set_entries(self.budget, accounts, categories)
        return transaction
