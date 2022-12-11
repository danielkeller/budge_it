from typing import Any, Optional

from django import forms
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from django.forms import ValidationError

from .models import (Budget, Account, Category,
                     Transaction, BaseAccount,
                     TransactionAccountPart, TransactionCategoryPart)


class Datalist(forms.Select):
    template_name = "budget/widgets/datalist.html"

    def format_value(self, value: str):
        return value


class AccountChoiceField(forms.ModelChoiceField):
    budget: Budget

    def label_from_instance(self, obj: Optional[BaseAccount]):  # type: ignore
        if obj == None:
            return ""
        return obj.name_in_budget(self.budget.id)

    def prepare_value(self, value: BaseAccount):
        if isinstance(value, str):
            return value
        return self.label_from_instance(value)

    def to_python(self, value: Optional[Any]):
        try:
            choice = next(choice for choice,
                          label in self.choices if label == value)
        except StopIteration:
            raise ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
                params={"value": value},
            )
        if choice == '':
            return None
        return choice.instance


class TransactionPartForm(forms.Form):
    account = AccountChoiceField(
        required=False, queryset=None, empty_label='', widget=Datalist)
    category = AccountChoiceField(
        required=False, queryset=None, empty_label='', widget=Datalist)
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

    def __init__(self, budget: Budget, *args: Any,
                 instance: Transaction, **kwargs: Any):
        self.budget = budget
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
    def save(self, *, instance: Transaction):
        instance.accounts.clear()
        instance.categories.clear()
        for form in self.forms:
            form.save(instance)


TransactionPartFormSet = forms.formset_factory(
    TransactionPartForm, formset=BaseTransactionPartFormSet, extra=2)


class TransactionForm(forms.ModelForm):
    # TODO: Date validation doesn't work
    class Meta:  # type: ignore
        model = Transaction
        fields = ('date', 'description')
