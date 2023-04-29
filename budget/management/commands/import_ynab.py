from django.db import transaction
from django.db.utils import IntegrityError
from django.core.management.base import BaseCommand
from budget.models import *

from typing import Iterable
from collections import defaultdict
import datetime
import csv
import re
from dataclasses import dataclass

ynab_transfer_prefix = "Transfer : "

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

ynab_currency = "CHF"

class Command(BaseCommand):
    help = "Import a YNAB budget"

    def handle(self, *args: Any, **options: Any):
        register_filename = "../Swiss Budget as of 2023-04-22 21-35 - Register.csv"
        self.process_csv(register_filename, RawTransactionPartRecord.from_row, self.process_transactions)

        budget_filename = "../Swiss Budget as of 2023-04-22 21-35 - Budget.csv"
        self.process_csv(budget_filename, RawBudgetEventRecord.from_row, self.process_budget_events)

    def process_csv(self, filename, from_row, handler):
        with open(filename, newline='', encoding='utf-8-sig') as file:
            reader = csv.reader(file)
            header = next(reader)
            handler(map(from_row, reader))

    @transaction.atomic
    def process_transactions(self, reader: 'Iterable[RawTransactionPartRecord]'):
        user = User.objects.get(username="admin")
        target_budget, _ = Budget.objects.get_or_create(
            name="ynabimport", budget_of=user)

        raw_transaction_parts: 'list[RawTransactionPartRecord]' = []

        current_date = None
        day_transaction_parts = []

        for raw_transaction_part in reader:
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

    def process_day(self, target_budget, day_transaction_parts):
        unmatched_transfers = defaultdict(list) # transfer_key -> [ix, ix]

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

        current_split = []
        current_split_transfers = defaultdict(int) #(to, from) => amount
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

    def save_transaction(self, target_budget: Budget, raw_transaction_parts: 'list[RawTransactionPartRecord]'):
        first_raw_transaction_part = raw_transaction_parts[0]
        date = YNAB_string_to_date(
            first_raw_transaction_part.Date)  # filter for past dates

        kind = Transaction.Kind.TRANSACTION
        description = join_memos(raw_transaction_parts)

        transaction = Transaction(
            date=date, kind=kind, description=description)
        transaction.save()

        transaction_account_parts: 'dict[Account, int]' = defaultdict(int)
        transaction_category_parts: 'dict[Category, int]' = defaultdict(int)
        for raw_transaction_part in raw_transaction_parts:
            raw_transaction_part_inflow = raw_transaction_part.TotalInflow()
            raw_transaction_part_outflow = -raw_transaction_part_inflow

            raw_account = raw_transaction_part.Account
            account, _ = Account.objects.get_or_create(
                budget=target_budget,
                name=raw_account,
                currency=ynab_currency,
            )
            transaction_account_parts[account] += raw_transaction_part_inflow

            raw_payee = raw_transaction_part.Payee

            if not is_transfer(raw_transaction_part):  # Payment to external payee
                payee, _ = Budget.objects.get_or_create(
                    name=raw_payee,
                    payee_of=target_budget.budget_of
                )
                payee_account = payee.get_hidden(Account, currency=ynab_currency)
                transaction_account_parts[payee_account] += raw_transaction_part_outflow

                category, _ = Category.objects.get_or_create(
                    budget=target_budget,
                    name=raw_transaction_part.CategoryGroupCategory,
                    currency=ynab_currency,
                )
                transaction_category_parts[category] += raw_transaction_part_inflow
                payee_category = payee.get_hidden(Category, currency=ynab_currency)
                transaction_category_parts[payee_category] += raw_transaction_part_outflow
            assert sum(transaction_category_parts.values()) == 0
        assert sum(transaction_account_parts.values()) == 0
        assert len(transaction_account_parts) > 0
        transaction.set_parts_raw(accounts=transaction_account_parts,
                                  categories=transaction_category_parts)
        return None

    @transaction.atomic
    def process_budget_events(self, reader: 'Iterable[RawBudgetEventRecord]'):
        user = User.objects.get(username="admin")
        target_budget, _ = Budget.objects.get_or_create(
            name="ynabimport", budget_of=user)
        inflow_budget_category = Category.objects.get_or_create(
                    budget=target_budget,
                    name="Inflow: Ready to Assign",
                    currency=ynab_currency,
                )

        for raw_budget_event in reader:
            self.save_budget_event(target_budget, inflow_budget_category, raw_budget_event)

    def save_budget_event(self, target_budget: Budget, inflow_budget_category: Category, raw_budget_event: 'RawBudgetEventRecord'):
        amount = raw_budget_event.TotalBudgeted()
        if not amount: return
        date = datetime.datetime.strptime(raw_budget_event.Month, "%b %Y")
        kind = Transaction.Kind.BUDGETING
        category = Category.objects.get_or_create(
                    budget=target_budget,
                    name=raw_budget_event.CategoryGroupCategory,
                    currency=ynab_currency,
                )

        transaction_category_parts: 'dict[Category, int]' = {category:amount, inflow_budget_category:-amount}

        transaction = Transaction(date=date, kind=kind)
        transaction.save()
        transaction.set_parts_raw(accounts={}, categories=transaction_category_parts)
        return None

def YNAB_string_to_date(ynab_string: str):
    return datetime.date(*[int(i) for i in ynab_string.split('.')][::-1])


def iscomplete(raw_transaction_part: RawTransactionPartRecord):
    return (not is_split(raw_transaction_part)) or is_last_part_in_split(raw_transaction_part)


def join_memos(raw_transaction_parts: 'list[RawTransactionPartRecord]'):
    return ", ".join([
        re.sub(r"Split \(.*\) ", "", x.Memo)
        for x in raw_transaction_parts])

def is_transfer(raw_transaction_part):
    return raw_transaction_part.Payee.startswith(ynab_transfer_prefix)

def is_split(raw_transaction_part):
    return raw_transaction_part.Memo.startswith("Split")

def is_last_part_in_split(raw_transaction_part):
    return re.match(r"Split \((\d+)/\1\)", raw_transaction_part.Memo)

def get_transfer_key(raw_transaction_part):
    acc = raw_transaction_part.Account
    other_acc = raw_transaction_part.Payee.removeprefix(ynab_transfer_prefix)
    total_inflow = raw_transaction_part.TotalInflow()

    transfer_key = (acc, other_acc, total_inflow)
    return transfer_key

def expected_transfer_key(raw_transaction_part):
    other_acc, acc, raw_amount = get_transfer_key(raw_transaction_part)
    amount = -raw_amount
    transfer_key = (acc, other_acc, amount)
    return transfer_key
