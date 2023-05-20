from django.db import transaction
from django.db.models import Q, F, Min, Max, Sum
from django.db.models.functions import Trunc
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from budget.models import (Budget, Account, Category, Transaction,
                           CategoryPart, months_between, double_entrify, CategoryNote, AccountNote)

from typing import Any, Iterable, TypeVar, Callable
from collections import defaultdict
from datetime import datetime, date, timedelta
import csv
import re
from dataclasses import dataclass
import functools

ynab_transfer_prefix = "Transfer : "

import_off_budget_prefix = "Off-budget: "
interest_prefix = "Interest: "

@dataclass
class RawTransactionPartRecord:
    Account: str
    Flag: str
    Date: str
    Payee: str
    CategoryGroupCategory: str
    CategoryGroup: str
    Category: str
    Memo: str
    Outflow: str
    Inflow: str
    Cleared: str

    def TotalInflow(self):
        return (int(self.Inflow.replace('.', ''))
                - int(self.Outflow.replace('.', '')))

    @staticmethod
    def from_row(row: 'list[str]') -> 'RawTransactionPartRecord':
        return RawTransactionPartRecord(*row)

@dataclass
class RawBudgetEventRecord:
    Month: str
    CategoryGroupCategory: str
    CategoryGroup: str
    Category: str
    Budgeted: str
    Activity: str
    Available: str

    def TotalBudgeted(self):
        return int(self.Budgeted.replace('.', ''))

    @staticmethod
    def from_row(row: 'list[str]') -> 'RawBudgetEventRecord':
        return RawBudgetEventRecord(*row)

@dataclass(eq=True, frozen=True)
class TargetBudget:
    budget: Budget

    @functools.cache
    def payee(self, name: str):
        assert name
        return Budget.objects.get_or_create(
            name=name, payee_of=self.budget.budget_of)[0]
    
    @functools.cache
    def account(self, name: str, currency: str):
        assert name
        return Account.objects.get_or_create(
                budget=self.budget, name=name, currency=currency)[0]
    
    @functools.cache
    def category(self, name: str, group: str, currency: str):
        assert name
        return Category.objects.get_or_create(
                budget=self.budget, name=name, group=group, currency=currency)[0]

ynab_currency = "CHF"

T = TypeVar('T')
TransferKey = tuple[str, str, int]

class Command(BaseCommand):
    help = "Import a YNAB budget"

    def handle(self, *args: Any, **options: Any):
        user = User.objects.get(username="admin")
        target_budget = TargetBudget(Budget.objects.get_or_create(
            name="ynabimport", budget_of=user)[0])

        register_filename = "../Swiss Budget as of 2023-05-01 20-59 - Register.csv"
        self.process_csv(target_budget, register_filename, RawTransactionPartRecord.from_row, self.process_transactions)

        fix_splitwise_transactions(target_budget)

        #delete duplicate notes
        AccountNote.objects.filter(transaction__categorynotes__note = F('note')).delete()

        budget_filename = "../Swiss Budget as of 2023-05-01 20-59 - Budget.csv"
        self.process_csv(target_budget, budget_filename, RawBudgetEventRecord.from_row, self.process_budget_events)

        #delete any accounts with no transactions
        for account in Account.objects.filter(Q(budget__payee_of=user)|Q(budget__budget_of=user), entries = None):
            account.delete()

        #TODO delete (or don't create??) any orphan notes
        assert not AccountNote.objects.filter(transaction__accounts = None)
        # assert not CategoryNote.objects.filter(transaction__categories = None)

    def process_csv(self, 
                    target_budget: TargetBudget,
                    filename: str,
                    from_row: Callable[[list[str]], T],
                    handler: Callable[[TargetBudget, Iterable[T]], None]):
        with open(filename, newline='', encoding='utf-8-sig') as file:
            reader = csv.reader(file)
            next(reader)
            handler(target_budget, map(from_row, reader))

    @transaction.atomic
    def process_transactions(self, target_budget: TargetBudget, reader: 'Iterable[RawTransactionPartRecord]'):
        current_date = None
        day_transaction_parts: list[RawTransactionPartRecord] = []

        for raw_transaction_part in reader:
            process_transaction_renames(raw_transaction_part)

            if not current_date:
                current_date = raw_transaction_part.Date
                print(current_date)
                day_transaction_parts.append(raw_transaction_part)
            else:
                if raw_transaction_part.Date == current_date:
                    day_transaction_parts.append(raw_transaction_part)
                else:
                    self.process_day(target_budget, day_transaction_parts)

                    day_transaction_parts.clear()
                    current_date = raw_transaction_part.Date
                    print(current_date)
                    day_transaction_parts.append(raw_transaction_part)
        self.process_day(target_budget, day_transaction_parts)

    def process_day(self, target_budget: TargetBudget,
                    day_transaction_parts: list[RawTransactionPartRecord]):
        unmatched_transfers: dict[TransferKey, list[int]] = defaultdict(list)

        for ix, part in enumerate(day_transaction_parts):
            if is_split(part):
                pass
            elif is_transfer(part):
                transfer_key = get_transfer_key(part)
                if transfer_key in unmatched_transfers:
                    other_part_ix = unmatched_transfers[transfer_key].pop()
                    other_part = day_transaction_parts[other_part_ix]
                    self.save_transaction(target_budget, [part, other_part])
                else:
                    unmatched_transfers[expected_transfer_key(part)].append(ix)
            else: #is_singleton(part):
                self.save_transaction(target_budget, [part])

        current_split: list[RawTransactionPartRecord] = []
        current_split_transfers: dict[tuple[str, str], int] = defaultdict(int) # (to, from) => amount
        for ix, part in enumerate(day_transaction_parts):
            if not is_split(part):
                assert not current_split
                assert not current_split_transfers
                continue
            current_split.append(part)
            if is_transfer(part):
                transfer_key = get_transfer_key(part)
                if transfer_key in unmatched_transfers:
                    other_part_ix = unmatched_transfers[transfer_key].pop()
                    other_part = day_transaction_parts[other_part_ix]
                    current_split.append(other_part)
                else:
                    from_acc, to_acc, amount  = transfer_key
                    current_split_transfers[(from_acc, to_acc)] += amount
                pass
            if is_last_part_in_split(part):
                for (from_acc, to_acc), amount in current_split_transfers.items():
                    transfer_key = (from_acc, to_acc, amount)
                    other_part_ix = unmatched_transfers[transfer_key].pop()
                    other_part = day_transaction_parts[other_part_ix]
                    current_split.append(other_part)
                current_split_transfers.clear()
                self.save_transaction(target_budget, current_split)# DOING
                current_split = []
        assert not current_split
        assert not current_split_transfers
        for l in unmatched_transfers.values():
            assert not l

    def save_transaction(self, target_budget: TargetBudget,
                         raw_transaction_parts: 'list[RawTransactionPartRecord]'):
        first_raw_transaction_part = raw_transaction_parts[0]
        date = YNAB_string_to_date(
            first_raw_transaction_part.Date)  # filter for past dates

        kind = Transaction.Kind.TRANSACTION

        transaction = Transaction(date=date, kind=kind)
        transaction.save()

        transaction_account_parts, transaction_category_parts, transaction_category_notes, transaction_account_notes = get_transaction_parts_notes(raw_transaction_parts, target_budget)
        transaction.set_parts_raw(accounts=transaction_account_parts,
                                  categories=transaction_category_parts)

        for (category, note) in transaction_category_notes.items():
            cn = CategoryNote.objects.create(user=target_budget.budget.budget_of, transaction=transaction, account=category, note=note)
            cn.save()
        for (account, note) in transaction_account_notes.items():
            an = AccountNote.objects.create(user=target_budget.budget.budget_of, transaction=transaction, account=account, note=note)
            an.save()

        return None

    @transaction.atomic
    def process_budget_events(self, target_budget: TargetBudget, reader: 'Iterable[RawBudgetEventRecord]'):
        raw_category_group_category = "Inflow: Ready to Assign"
        raw_category, raw_group = split_category_group_category(raw_category_group_category)
        inflow_budget_category = target_budget.category(
            raw_category, raw_group, ynab_currency)
        kind = Transaction.Kind.BUDGETING

        month_budgets: dict[date, dict[Category, int]] = defaultdict(
            lambda: defaultdict(int)) #month -> cat -> budgeted_amount

        #parse csv
        for raw_budget_event in reader:
            process_budget_renames(raw_budget_event)

            if raw_budget_event.CategoryGroup == "Credit Card Payments": continue #TODO this works for me as I have no credit card debt
            amount = raw_budget_event.TotalBudgeted()
            if not amount: continue
            month = datetime.strptime(raw_budget_event.Month, "%b %Y").date()
            raw_category_group_category = raw_budget_event.CategoryGroupCategory
            raw_category, raw_group = split_category_group_category(raw_category_group_category)
            category = target_budget.category(raw_category, raw_group, ynab_currency)
            month_budgets[month][category] = amount

        #form budgeting transactions
        category_month_activities = { #cat -> month -> activity
                category: defaultdict(
                    int, 
                    {
                        month: 
                        activity 
                        for month, activity in get_category_activity_iterable(category)}
                    ) 
                for category in target_budget.budget.category_set.all()
                }

        #if there are no transactions in a category, and the total budgeted amount sums to zero, do not create those budgeting events
        zeroed_categories = [category for (category, month_activities) in category_month_activities.items() if sum(month_activities.values()) == 0]
        for category in zeroed_categories:
            if CategoryPart.objects.filter(sink=category).count() == 0:
                del category_month_activities[category]
                category.delete()

        running_sums: dict[Category, int] = defaultdict(int) #cat -> sum

        range = (Transaction.objects
                 .filter(categories__budget=target_budget.budget)
                 .aggregate(Max('date'), Min('date')))
        months = list(months_between(range['date__min'] or date.today(),
                                     range['date__max'] or date.today()))
        for month in months:
            transaction_category_parts: dict[tuple[Category, Category], int] = {}
            for category in target_budget.budget.category_set.all():
                if category.name.startswith(import_off_budget_prefix): continue # this is a new category built by us
                budgeted = month_budgets[month][category]

                running_sums[category] += budgeted
                running_sums[category] += category_month_activities[category][month]

                if running_sums[category] < 0: #ynab doesn't let you roll negative categories over
                    budgeted += -running_sums[category]
                    running_sums[category] = 0
                transaction_category_parts[(inflow_budget_category, category)] = budgeted

            transaction = Transaction(date=month, kind=kind)
            transaction.save()
            transaction.set_parts_raw(accounts = {}, categories = transaction_category_parts)

def YNAB_string_to_date(ynab_string: str):
    return date(*[int(i) for i in ynab_string.split('.')][::-1])


def iscomplete(raw_transaction_part: RawTransactionPartRecord):
    return (not is_split(raw_transaction_part)) or is_last_part_in_split(raw_transaction_part)


def join_memos(raw_transaction_parts: 'list[RawTransactionPartRecord]'):
    parts = (re.sub(r"Split \(.*\) ", "", x.Memo)
             for x in raw_transaction_parts)
    return ", ".join({part for part in parts if part})

def is_transfer(raw_transaction_part: RawTransactionPartRecord):
    return raw_transaction_part.Payee.startswith(ynab_transfer_prefix)

def is_split(raw_transaction_part: RawTransactionPartRecord):
    return raw_transaction_part.Memo.startswith("Split")

def is_last_part_in_split(raw_transaction_part: RawTransactionPartRecord):
    return re.match(r"Split \((\d+)/\1\)", raw_transaction_part.Memo)

def get_transfer_key(raw_transaction_part: RawTransactionPartRecord):
    acc = raw_transaction_part.Account
    other_acc = raw_transaction_part.Payee.removeprefix(ynab_transfer_prefix)
    total_inflow = raw_transaction_part.TotalInflow()

    transfer_key = (acc, other_acc, total_inflow)
    return transfer_key

def expected_transfer_key(raw_transaction_part: RawTransactionPartRecord):
    other_acc, acc, raw_amount = get_transfer_key(raw_transaction_part)
    amount = -raw_amount
    transfer_key = (acc, other_acc, amount)
    return transfer_key

def get_last_day_of_month(month: date):
    return ((month + timedelta(days = 31)).replace(day = 1)
            - timedelta(days=1))

def get_category_activity_iterable(category: Category):
    return (CategoryPart.objects
            .filter(sink=category)
            .values_list(Trunc(F('transaction__date'), 'month'))
            .annotate(total=Sum('amount'))
            .order_by('trunc1'))

def split_category_group_category(raw_category_group_category):
    return raw_category_group_category.split(": ")[::-1]

"""
Convert ynab format RawTransactionPartRecords into budge-it double entry transaction parts and category/account notes
"""
def get_transaction_parts_notes(raw_transaction_parts: 'list[RawTransactionPartRecord]', target_budget: TargetBudget):
    single_entry_transaction_account_parts: 'dict[Account, int]' = defaultdict(int)
    transaction_category_parts: 'dict[tuple[Category, Category], int]' = defaultdict(int)
    category_notes: 'dict[Category, str]' = dict()
    account_notes: 'dict[Account, str]' = dict()

    for raw_transaction_part in raw_transaction_parts:
        raw_transaction_part_inflow = raw_transaction_part.TotalInflow()

        raw_account = raw_transaction_part.Account.removesuffix(" (Original)")
        account = target_budget.account(raw_account, ynab_currency)
        single_entry_transaction_account_parts[account] += raw_transaction_part_inflow

        raw_payee = raw_transaction_part.Payee

        memo = re.sub(r"Split \(.*\) ", "", raw_transaction_part.Memo) if raw_transaction_part.Memo else ""

        if not is_transfer(raw_transaction_part):  # Payment to external payee
            if not raw_payee: # payment to an off-budget debt account")
                raw_payee = f"{interest_prefix}{raw_transaction_part.Account}"
            raw_category_group_category = raw_transaction_part.CategoryGroupCategory
            if not raw_category_group_category: # off-budget account")
                raw_category_group_category = f"{import_off_budget_prefix}{raw_account}"

            payee = target_budget.payee(raw_payee)
            payee_account = payee.get_inbox(Account, currency=ynab_currency)
            single_entry_transaction_account_parts[payee_account] += -raw_transaction_part_inflow

            raw_category, raw_group = split_category_group_category(raw_category_group_category)
            category = target_budget.category(raw_category, raw_group, ynab_currency)

            if memo:
                category_notes[category] = memo

            payee_category = payee.get_inbox(Category, currency=ynab_currency)

            transaction_category_parts[(payee_category, category)] += raw_transaction_part_inflow
        else:
            if memo: 
                account_notes[account] = memo
    assert sum(single_entry_transaction_account_parts.values()) == 0
    assert len(single_entry_transaction_account_parts) > 0

    transaction_account_parts = double_entrify(
        target_budget.budget, Account, single_entry_transaction_account_parts)

    return transaction_account_parts, transaction_category_parts, category_notes, account_notes

renames = {"Not My Money: Splitwise": f"{import_off_budget_prefix}Flat splitwise",  "Hidden Categories: Dan tracking": f"{import_off_budget_prefix}Dan tracking"}
def process_transaction_renames(raw_transaction_part: RawTransactionPartRecord):
    raw_category_group_category = raw_transaction_part.CategoryGroupCategory
    if raw_category_group_category in renames.keys():
        raw_transaction_part.CategoryGroupCategory = renames[raw_category_group_category]
    return
def process_budget_renames(raw_budget_event: RawBudgetEventRecord):
    raw_category_group_category = raw_budget_event.CategoryGroupCategory
    if raw_category_group_category in renames.keys():
        raw_budget_event.CategoryGroupCategory = renames[raw_category_group_category]
    return

#magic *(*) algorithm
def fix_splitwise_transactions(target_budget):
    splitwise_transactions = Transaction.objects.filter(accounts__name = "Flat splitwise")
    ynab_splitwise_account = target_budget.account("Flat splitwise", "CHF")

    splitwise_payee = target_budget.payee("Flat splitwise")
    for splitwise_transaction in splitwise_transactions:
        account_parts, category_parts = splitwise_transaction.entries()

        external_payee_accs = [k for k in account_parts.keys() if k.budget.get_inbox(Category, "CHF") in category_parts.keys()]
        if len(external_payee_accs) == 1:
            external_payee = external_payee_accs[0].budget
            alpha = account_parts.pop(ynab_splitwise_account)
            account_parts[external_payee.get_inbox(Account, "CHF")] += alpha

            category_parts[splitwise_payee.get_inbox(Category, "CHF")] = -alpha
            category_parts[external_payee.get_inbox(Category, "CHF")] += alpha

        elif len(external_payee_accs) == 0:
            assert not category_parts
            account_parts[splitwise_payee.get_inbox(Account, "CHF")] = account_parts.pop(ynab_splitwise_account)

        double_account_parts = double_entrify(target_budget.budget, Account, account_parts)
        double_category_parts = double_entrify(target_budget.budget, Category, category_parts)
        splitwise_transaction.set_parts_raw(accounts=double_account_parts,
                                  categories=double_category_parts)
    account_notes = AccountNote.objects.filter(account=ynab_splitwise_account)
    for account_note in account_notes:
        if account_note.transaction.categories:
            cn = CategoryNote.objects.create(user=account_note.user, transaction=account_note.transaction, account=splitwise_payee.get_inbox(Category, "CHF"), note=account_note.note)
            cn.save()
            account_note.delete()
        else:
            account_note.account = splitwise_payee.get_inbox(Account, "CHF")
            account_note.save()

    return 
