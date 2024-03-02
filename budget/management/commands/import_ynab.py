from django.db import transaction
from django.db.models import Q, F, Min, Max, Sum
from django.db.models.functions import Trunc
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandParser, CommandError
from budget.models import (User, Budget, Account, Category, Transaction, TransactionPart,
                           BaseAccount, AccountT, CategoryEntry, months_between)

from typing import Any, Iterable, TypeVar, Callable
from collections import defaultdict
from datetime import datetime, date, timedelta
import csv
import re
import copy
from glob import glob

from dataclasses import dataclass
import functools

ynab_transfer_prefix = "Transfer : "
ynab_debt_payments_prefix = "Debt Payments:  "

import_off_budget_prefix = "Off-budget: "
import_off_budget_prefix_nocolon = "Off-budget"
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
    off_budget: bool = False

    def TotalInflow(self):
        return (int(self.Inflow.replace('.', ''))
                - int(self.Outflow.replace('.', '')))

    @staticmethod
    def from_row(row: 'list[str]') -> 'RawTransactionPartRecord':
        return RawTransactionPartRecord(*row, off_budget=False)

    def __str__(self):
        return f"{self.Date}: {self.Account} - {self.Memo}"


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
        # ynab doesn't let you roll negative categories over
        budget = int(self.Budgeted.replace('.', ''))
        overspent = -int(self.Available.replace('.', ''))
        return budget + max(overspent, 0)

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
            budget=self.budget, name=name, currency=currency,
            defaults={'group': group, 'order': 999})[0]


ynab_currency = "CHF"

T = TypeVar('T')
TransferKey = tuple[str, str, int]


class Command(BaseCommand):
    help = "Import a YNAB budget"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("directory", nargs=1, type=str)

    @transaction.atomic
    def handle(self, *args: Any, directory: str, **options: Any):
        filenames = glob(f"{directory[0]}/*Register.csv")
        if len(filenames) == 1:
            register_filename = filenames[0]
        else:
            raise CommandError(f"No single register file in {directory[0]}")
        filenames = glob(f"{directory[0]}/*Budget.csv")
        if len(filenames) == 1:
            budget_filename = filenames[0]
        else:
            raise CommandError(f"No single budget file in {directory[0]}")

        user = User.objects.get(username="admin")
        target_budget = TargetBudget(Budget.objects.get_or_create(
            name="ynabimport", budget_of=user)[0])

        self.process_transactions(
            target_budget, Command.csv_rows(register_filename, RawTransactionPartRecord.from_row))

        self.process_budget_events(
            target_budget, Command.csv_rows(budget_filename, RawBudgetEventRecord.from_row))

        move_to_payee(target_budget, target_budget.account(
            "Flat splitwise", "CHF"))
        merge_accounts(target_budget,
                       target_budget.category("Splitwise", "", "CHF"),
                       target_budget.category("🌐 Flat splitwise", "", "CHF"))

        # delete any accounts with no transactions
        for account in Account.objects.filter(Q(budget__payee_of=user) | Q(budget__budget_of=user), entries=None):
            account.delete()

        # TODO order categories?

        # assert not AccountNote.objects.exclude(transaction__accounts = F('account'))
        # assert not CategoryNote.objects.exclude(transaction__categories = F('account'))

    @staticmethod
    def csv_rows(filename: str, from_row: Callable[[list[str]], T]) -> Iterable[T]:
        with open(filename, newline='', encoding='utf-8-sig') as file:
            reader = csv.reader(file)
            next(reader)
            for row in reader:
                yield from_row(row)

    def process_transactions(self, target_budget: TargetBudget, reader: 'Iterable[RawTransactionPartRecord]'):
        current_date = None
        day_transaction_parts: list[RawTransactionPartRecord] = []

        for raw_transaction_part in reader:
            # FIXME
            # process_transaction_renames(raw_transaction_part)

            if not current_date:
                current_date = raw_transaction_part.Date
                day_transaction_parts.append(raw_transaction_part)
                print(current_date)
            else:
                if raw_transaction_part.Date == current_date:
                    day_transaction_parts.append(raw_transaction_part)
                else:
                    self.process_day(target_budget, day_transaction_parts)

                    day_transaction_parts.clear()
                    current_date = raw_transaction_part.Date
                    if current_date.startswith("01"):
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
                if transfer_key in unmatched_transfers:  # Non-split transfer
                    other_part_ix = unmatched_transfers[transfer_key].pop()
                    other_part = day_transaction_parts[other_part_ix]
                    determine_off_budget(part, other_part)
                    self.save_transaction(target_budget, [part, other_part])
                else:  # Some other kind of transfer
                    unmatched_transfers[expected_transfer_key(part)].append(ix)
            else:   # Non-split non-transfer
                self.save_transaction(target_budget, [part])
        # unmatched_transfers now contains the non-split sides of all the splits with transfers

        # For no apparent reason, split transactions are represented differently depending on whether
        # the main payee is a transfer ("split transfer"). If not, each part of the split has its own
        # entry for both accounts and the main memo is dropped. If so, there is only one entry for
        # the other account with everything lumped together, and the main memo is on that entry.

        # Regular split with transfer -------------------------------------------------------------
        # ZKB Current Acct   Holy Cow                      Quality of Life  c        Split (1/3)  x
        # ZKB Current Acct   Transfer: Dan Tracking        Category 1       a        Split (2/3)  y
        # ZKB Current Acct   Transfer: Dan Tracking        Category 2       b        Split (3/3)  z
        # Dan Tracking       Transfer: ZKB Current Acct         -           -a       y
        # Dan Tracking       Transfer: ZKB Current Acct         -           -b       z

        # Split transfer --------------------------------------------------------------------------
        # ZKB Current Acct   Transfer: UZH Reimbursement   Halbtax          a        Split (1/2)  y
        # ZKB Current Acct   Transfer: UZH Reimbursement   Reimbursements   b        Split (2/2)  z
        # UZH Reimbursement  Transfer: ZKB Current Acct         -           - a - b  main

        current_split: list[RawTransactionPartRecord] = []
        other_sides: list[RawTransactionPartRecord] = []
        current_split_transfers: dict[tuple[str, str], int] = defaultdict(
            int)  # (to, from) => amount
        for ix, part in enumerate(day_transaction_parts):
            if not is_split(part):
                assert not current_split
                assert not other_sides
                assert not current_split_transfers
                continue
            current_split.append(part)
            if is_transfer(part):
                transfer_key = get_transfer_key(part)
                if transfer_key in unmatched_transfers:
                    other_part_ix = unmatched_transfers[transfer_key].pop()
                    other_part = day_transaction_parts[other_part_ix]
                    determine_off_budget(part, other_part)
                    current_split.append(other_part)
                else:  # This is part of a split transfer
                    from_acc, to_acc, amount = transfer_key
                    current_split_transfers[(from_acc, to_acc)] += amount
                    # Make a fake one so that the notes match.
                    other_part = copy.copy(part)
                    other_part.CategoryGroupCategory = ''  # Is this right?
                    other_part.Account = to_acc
                    other_part.Inflow, other_part.Outflow = part.Outflow, part.Inflow
                    determine_off_budget(part, other_part)
                    current_split.append(other_part)
            if is_last_part_in_split(part):
                # We have all the totals of split transfers, so we should be able to match them
                for (from_acc, to_acc), amount in current_split_transfers.items():
                    transfer_key = (from_acc, to_acc, amount)
                    other_part_ix = unmatched_transfers[transfer_key].pop()
                    # We add a fake part instead.
                    # other_part = day_transaction_parts[other_part_ix]
                    # current_split.append(other_part)
                current_split_transfers.clear()
                self.save_transaction(target_budget, current_split)  # DOING
                current_split = []
                other_sides = []
        assert not current_split
        assert not current_split_transfers
        assert not other_sides
        assert not any(unmatched_transfers.values()), unmatched_transfers

    def save_transaction(self, target_budget: TargetBudget,
                         raw_transaction_parts: 'list[RawTransactionPartRecord]'):
        first_raw_transaction_part = raw_transaction_parts[0]
        date = YNAB_string_to_date(
            first_raw_transaction_part.Date)  # filter for past dates

        kind = Transaction.Kind.TRANSACTION
        transaction = Transaction(date=date, kind=kind)
        transaction.save()

        grouped_parts: dict[str, list[RawTransactionPartRecord]] = {}
        for raw_part in raw_transaction_parts:
            grouped_parts.setdefault(
                cleaned_memo(raw_part), []).append(raw_part)

        for memo, raw_parts in grouped_parts.items():
            transaction_part = TransactionPart(
                transaction=transaction, note=memo)
            transaction_part.save()

            account_entries, category_entries = parts_to_entries(
                raw_parts, target_budget)
            transaction_part.set_entries(
                target_budget.budget, account_entries, category_entries)

    def process_budget_events(self, target_budget: TargetBudget,
                              reader: 'Iterable[RawBudgetEventRecord]'):
        raw_category_group_category = "Inflow: Ready to Assign"
        raw_category, raw_group = split_category_group_category(
            raw_category_group_category)
        inflow_budget_category = target_budget.category(
            raw_category, raw_group, ynab_currency)
        kind = Transaction.Kind.BUDGETING

        month_budgets: dict[date, dict[Category, int]] = defaultdict(
            lambda: defaultdict(int))  # month -> cat -> budgeted_amount

        # parse csv
        for raw_budget_event in reader:
            # FIXME
            # process_budget_renames(raw_budget_event)

            # FIXME: Is this correct?
            if raw_budget_event.CategoryGroup == "Credit Card Payments":
                continue  # TODO this works for me as I have no credit card debt
            month = datetime.strptime(raw_budget_event.Month, "%b %Y").date()
            raw_category_group_category = raw_budget_event.CategoryGroupCategory
            raw_category, raw_group = split_category_group_category(
                raw_category_group_category)
            category = target_budget.category(
                raw_category, raw_group, ynab_currency)
            month_budgets[month][category] = raw_budget_event.TotalBudgeted()

        for month, categories in month_budgets.items():
            categories[inflow_budget_category] = -sum(categories.values())

            transaction = Transaction(date=month, kind=kind)
            transaction.save()
            part = TransactionPart(transaction=transaction)
            part.save()
            part.set_entries(target_budget.budget,
                             accounts={}, categories=categories)

        for order, category in enumerate(list(month_budgets.values())[-1]):
            category.order = order
            category.save()


def determine_off_budget(a: RawTransactionPartRecord, b: RawTransactionPartRecord):
    a.off_budget = bool(
        b.CategoryGroupCategory and not a.CategoryGroupCategory)
    b.off_budget = bool(
        a.CategoryGroupCategory and not b.CategoryGroupCategory)


def YNAB_string_to_date(ynab_string: str):
    return date(*[int(i) for i in ynab_string.split('.')][::-1])


def iscomplete(raw_transaction_part: RawTransactionPartRecord):
    return (not is_split(raw_transaction_part)) or is_last_part_in_split(raw_transaction_part)


def join_memos(raw_transaction_parts: 'list[RawTransactionPartRecord]'):
    parts = (re.sub(r"Split \(.*\) ", "", x.Memo)
             for x in raw_transaction_parts)
    return ", ".join({part for part in parts if part})


def cleaned_memo(part: RawTransactionPartRecord):
    return re.sub(r"^Split \(\d+/\d+\) ", "", part.Memo)


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


def split_category_group_category(raw_category_group_category):
    return [x.strip() for x in raw_category_group_category.split(": ")[::-1]]


def parts_to_entries(raw_transaction_parts: 'list[RawTransactionPartRecord]',
                     target_budget: TargetBudget):
    """
    Convert ynab format RawTransactionPartRecords into budge-it double entry transaction parts and category/account notes and assert that everything adds up.
    """
    account_entries: 'dict[Account, int]' = defaultdict(int)
    category_entries: 'dict[Category, int]' = defaultdict(int)

    for raw_transaction_part in raw_transaction_parts:
        raw_transaction_part_inflow = raw_transaction_part.TotalInflow()

        raw_account = raw_transaction_part.Account.removesuffix(" (Original)")
        account = target_budget.account(raw_account, ynab_currency)
        account_entries[account] += raw_transaction_part_inflow

        raw_payee = raw_transaction_part.Payee
        raw_category_group_category = raw_transaction_part.CategoryGroupCategory

        if not is_transfer(raw_transaction_part):  # Payment to external payee
            if not raw_payee:   # Interest charge on an off-budget debt account
                raw_payee = f"{interest_prefix}{raw_transaction_part.Account}"
            if not raw_category_group_category:  # Payment from/to off-budget account
                raw_category_group_category = f"{import_off_budget_prefix}🌐 {raw_account}"

            payee = target_budget.payee(raw_payee)
            payee_account = payee.get_inbox(Account, currency=ynab_currency)
            account_entries[payee_account] += -raw_transaction_part_inflow

            raw_category, raw_group = split_category_group_category(
                raw_category_group_category)
            category = target_budget.category(
                raw_category, raw_group, ynab_currency)

            payee_category = payee.get_inbox(Category, currency=ynab_currency)

            category_entries[category] += raw_transaction_part_inflow
            category_entries[payee_category] -= raw_transaction_part_inflow
        else:
            raw_category_group_category = raw_transaction_part.CategoryGroupCategory
            if raw_category_group_category.startswith(ynab_debt_payments_prefix):
                debt_account = raw_category_group_category.removeprefix(
                    ynab_debt_payments_prefix)

                _, group = split_category_group_category(
                    ynab_debt_payments_prefix)
                payments_category = target_budget.category(
                    debt_account, group, ynab_currency)

                _, group = split_category_group_category(
                    import_off_budget_prefix)
                debt_category = target_budget.category(
                    debt_account, group, ynab_currency)

                category_entries[debt_category] -= raw_transaction_part_inflow
                category_entries[payments_category] += raw_transaction_part_inflow
            else:
                if raw_transaction_part.off_budget:  # Transfer from/to off-budget account
                    raw_category_group_category = f"{import_off_budget_prefix}🌐 {raw_account}"

                if raw_category_group_category:
                    raw_category, raw_group = split_category_group_category(
                        raw_category_group_category)
                    category = target_budget.category(
                        raw_category, raw_group, ynab_currency)
                    category_entries[category] += raw_transaction_part_inflow

    assert sum(account_entries.values()) == 0, raw_transaction_parts[0]
    assert sum(category_entries.values()) == 0, raw_transaction_parts[0]
    assert len(account_entries) > 0
    return account_entries, category_entries


renames = {"Not My Money: Splitwise": f"{import_off_budget_prefix}Flat splitwise",
           "Hidden Categories: Dan tracking": f"{import_off_budget_prefix}Dan tracking"}


def process_transaction_renames(raw_transaction_part: RawTransactionPartRecord):
    raw_category_group_category = raw_transaction_part.CategoryGroupCategory
    if raw_category_group_category in renames.keys():
        raw_transaction_part.CategoryGroupCategory = renames[raw_category_group_category]


def process_budget_renames(raw_budget_event: RawBudgetEventRecord):
    raw_category_group_category = raw_budget_event.CategoryGroupCategory
    if raw_category_group_category in renames.keys():
        raw_budget_event.CategoryGroupCategory = renames[raw_category_group_category]


def move_to_payee(target_budget: TargetBudget, account: BaseAccount):
    account.budget = target_budget.payee(account.name)
    account.name = ''
    account.save()
    for entry in account.entries.all():
        accounts, categories = entry.part.entries()
        entry.part.set_entries(target_budget.budget, accounts, categories)


def merge_accounts(target_budget: TargetBudget, a: AccountT, b: AccountT):
    assert a.budget == b.budget
    entries = a.entries.all()
    a.entries.update(sink=b)
    a.source_entries.update(source=b)
    a.delete()
    for entry in entries:
        accounts, categories = entry.part.entries()
        entry.part.set_entries(target_budget.budget, accounts, categories)
