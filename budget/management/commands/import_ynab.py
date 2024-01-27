from django.db import transaction
from django.db.models import F, Min, Max, Sum
from django.db.models.functions import Trunc
from django.core.management.base import BaseCommand
from budget.models import (User, Budget, Account, Category, Transaction, TransactionPart,
                           CategoryEntry, months_between)

from typing import Any, Iterable, TypeVar, Callable
from collections import defaultdict
from datetime import datetime, date, timedelta
import csv
import re
from dataclasses import dataclass
import functools

ynab_transfer_prefix = "Transfer : "
import_off_budget_prefix = "Off-budget: "


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
            budget=self.budget, name=name, currency=currency, defaults={'group': group})[0]


ynab_currency = "CHF"

T = TypeVar('T')
TransferKey = tuple[str, str, int]


class Command(BaseCommand):
    help = "Import a YNAB budget"

    def handle(self, *args: Any, **options: Any):
        register_filename = "YNAB Export - Swiss Budget as of 2024-01-07 12-04/Swiss Budget as of 2024-01-07 12-04 - Register.csv"
        self.process_csv(
            register_filename, RawTransactionPartRecord.from_row, self.process_transactions)

        budget_filename = "YNAB Export - Swiss Budget as of 2024-01-07 12-04/Swiss Budget as of 2024-01-07 12-04 - Budget.csv"
        self.process_csv(
            budget_filename, RawBudgetEventRecord.from_row, self.process_budget_events)

    def process_csv(self, filename: str,
                    from_row: Callable[[list[str]], T],
                    handler: Callable[[Iterable[T]], None]):
        with open(filename, newline='', encoding='utf-8-sig') as file:
            reader = csv.reader(file)
            next(reader)
            handler(map(from_row, reader))

    @transaction.atomic
    def process_transactions(self, reader: 'Iterable[RawTransactionPartRecord]'):
        user = User.objects.get(username="admin")
        target_budget = TargetBudget(Budget.objects.get_or_create(
            name="ynabimport", budget_of=user)[0])

        current_date = None
        day_transaction_parts: list[RawTransactionPartRecord] = []

        for raw_transaction_part in reader:
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
                    unmatched_transfers[transfer_key].pop()
                    self.save_transaction(target_budget, [part])
                else:  # Some kind of transfer
                    unmatched_transfers[expected_transfer_key(part)].append(ix)
            else:  # Non-split non-transfer
                self.save_transaction(target_budget, [part])
        # unmatched_transfers now contains the non-split sides of all the splits with transfers

        # For no apparent reason, split transactions are represented differently depending on whether
        # the main payee is a transfer ("split transfer"). If not, each part of the split has its own
        # entry for both accounts and the main memo is dropped. If so, there is only one entry for
        # the other account with everything lumped together, and the main memo is on that entry.

        # Regular split with transfer -------------------------------------------------------------
        # ZKB Current Acct   Holy Cow                      Quality of Life  a        Split (1/3)  x
        # ZKB Current Acct   Transfer: Dan Tracking        Category 1       b        Split (2/3)  y
        # ZKB Current Acct   Transfer: Dan Tracking        Category 2       c        Split (3/3)  z
        # Dan Tracking       Transfer: ZKB Current Acct         -           -b       y
        # Dan Tracking       Transfer: ZKB Current Acct         -           -c       z

        # Split transfer --------------------------------------------------------------------------
        # UZH Reimbursement  Transfer: ZKB Current Acct         -           - a - b  main
        # ZKB Current Acct   Transfer: UZH Reimbursement   Halbtax          a        Split (1/2)  y
        # ZKB Current Acct   Transfer: UZH Reimbursement   Reimbursements   b        Split (2/2)  z

        current_split: list[RawTransactionPartRecord] = []
        current_split_transfers: dict[tuple[str, str], int] = defaultdict(
            int)  # (to, from) => amount
        for ix, part in enumerate(day_transaction_parts):
            if not is_split(part):
                assert not current_split
                assert not current_split_transfers
                continue
            current_split.append(part)
            if is_transfer(part):
                transfer_key = get_transfer_key(part)
                if transfer_key in unmatched_transfers:
                    unmatched_transfers[transfer_key].pop()
                else:  # This is part of a split transfer
                    from_acc, to_acc, amount = transfer_key
                    current_split_transfers[(from_acc, to_acc)] += amount
            if is_last_part_in_split(part):
                # We have all the totals of split transfers, so we should be able to match them
                for (from_acc, to_acc), amount in current_split_transfers.items():
                    transfer_key = (from_acc, to_acc, amount)
                    unmatched_transfers[transfer_key].pop()
                current_split_transfers.clear()
                self.save_transaction(target_budget, current_split)  # DOING
                current_split = []
        assert not current_split
        assert not current_split_transfers
        assert not any(unmatched_transfers.values()), unmatched_transfers

    def save_transaction(self, target_budget: TargetBudget,
                         raw_transaction_parts: 'list[RawTransactionPartRecord]'):
        first_raw_transaction_part = raw_transaction_parts[0]
        date = YNAB_string_to_date(
            first_raw_transaction_part.Date)  # filter for past dates

        kind = Transaction.Kind.TRANSACTION
        transaction = Transaction(date=date, kind=kind)
        transaction.save()

        for memo in {cleaned_memo(part) for part in raw_transaction_parts}:
            account_entries: 'dict[Account, int]' = defaultdict(int)
            category_entries: 'dict[Category, int]' = defaultdict(int)
            for raw_transaction_part in raw_transaction_parts:
                if cleaned_memo(raw_transaction_part) != memo:
                    continue

                raw_transaction_part_inflow = raw_transaction_part.TotalInflow()
                raw_transaction_part_outflow = -raw_transaction_part_inflow

                raw_account = raw_transaction_part.Account.removesuffix(
                    " (Original)")
                account = target_budget.account(raw_account, ynab_currency)
                account_entries[account] += raw_transaction_part_inflow

                # Category unset if: Transfer between regular accts, payment from off-budget acct,
                # transfer between on- and off-budget (off budget side only). We deliberately ignore
                # the categories in the third case (that is, off-budget accounts are moved into the
                # budget).

                if is_transfer(raw_transaction_part):
                    # We only get one side of each transfer
                    other_side = raw_transaction_part.Payee.removeprefix(
                        ynab_transfer_prefix).removesuffix(" (Original)")
                    account = target_budget.account(other_side, ynab_currency)
                    account_entries[account] += raw_transaction_part_outflow

                else:  # Payment to external payee
                    raw_payee = raw_transaction_part.Payee

                    if not raw_payee:  # Interest charge on an off-budget debt account
                        raw_payee = f"Interest: {raw_transaction_part.Account}"
                    raw_category_group_category = raw_transaction_part.CategoryGroupCategory
                    if not raw_category_group_category:  # Payment from/to off-budget account
                        raw_category_group_category = f"Off-budget: {raw_account}"

                    payee = target_budget.payee(raw_payee)
                    payee_account = payee.get_inbox(
                        Account, currency=ynab_currency)
                    account_entries[payee_account] += raw_transaction_part_outflow

                    raw_category, raw_group = split_category_group_category(
                        raw_category_group_category)
                    category = target_budget.category(
                        raw_category, raw_group, ynab_currency)
                    category_entries[category] += raw_transaction_part_inflow
                    payee_category = payee.get_inbox(
                        Category, currency=ynab_currency)
                    category_entries[payee_category] += raw_transaction_part_outflow
                assert sum(category_entries.values()
                           ) == 0, raw_transaction_part
            assert sum(account_entries.values()) == 0, raw_transaction_parts[0]
            assert len(account_entries) > 0, raw_transaction_parts[0]
            transaction_part = TransactionPart(
                transaction=transaction, note=memo)
            transaction_part.save()
            transaction_part.set_entries(
                target_budget.budget, account_entries, category_entries)

    @transaction.atomic
    def process_budget_events(self, reader: 'Iterable[RawBudgetEventRecord]'):
        user = User.objects.get(username="admin")
        target_budget = TargetBudget(Budget.objects.get_or_create(
            name="ynabimport", budget_of=user)[0])
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
            if raw_budget_event.CategoryGroup == "Credit Card Payments":
                continue  # TODO this works for me as I have no credit card debt
            amount = raw_budget_event.TotalBudgeted()
            if not amount:
                continue
            month = datetime.strptime(raw_budget_event.Month, "%b %Y").date()
            raw_category_group_category = raw_budget_event.CategoryGroupCategory
            raw_category, raw_group = split_category_group_category(
                raw_category_group_category)
            category = target_budget.category(
                raw_category, raw_group, ynab_currency)
            month_budgets[month][category] = amount

        # form budgeting transactions
        category_month_activities = {  # cat -> month -> activity
            category: defaultdict(
                int,
                {
                    month:
                    activity
                    for month, activity in get_category_activity_iterable(category)}
            )
            for category in target_budget.budget.category_set.all()
        }
        running_sums: dict[Category, int] = defaultdict(int)  # cat -> sum

        range = (Transaction.objects
                 .filter(parts__categories__budget=target_budget.budget)
                 .aggregate(Max('date'), Min('date')))
        months = list(months_between(range['date__min'] or date.today(),
                                     range['date__max'] or date.today()))
        for month in months:
            category_entries: dict[Category, int] = {}
            for category in target_budget.budget.category_set.all():
                if category.name.startswith(import_off_budget_prefix):
                    continue  # this is a new category built by us
                budgeted = month_budgets[month][category]

                running_sums[category] += budgeted
                running_sums[category] += category_month_activities[category][month]

                # ynab doesn't let you roll negative categories over
                if running_sums[category] < 0:
                    budgeted += -running_sums[category]
                    running_sums[category] = 0
                category_entries[category] = budgeted

            total_budgeted = sum(category_entries.values())
            category_entries[inflow_budget_category] = - \
                total_budgeted

            transaction = Transaction(date=month, kind=kind)
            transaction.save()
            part = TransactionPart(transaction=transaction)
            part.save()
            part.set_entries(target_budget.budget,
                             accounts={}, categories=category_entries)


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


def get_last_day_of_month(month: date):
    return ((month + timedelta(days=31)).replace(day=1)
            - timedelta(days=1))


def get_category_activity_iterable(category: Category):
    return (CategoryEntry.objects
            .filter(sink=category)
            .values_list(Trunc(F('part__transaction__date'), 'month'))
            .annotate(total=Sum('amount'))
            .order_by('trunc1'))


def split_category_group_category(raw_category_group_category):
    return raw_category_group_category.split(": ")[::-1]
