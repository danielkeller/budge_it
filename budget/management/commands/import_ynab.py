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
class Record:
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
    def from_row(row: 'list[str]') -> 'Record':
        return Record(*row)


class Command(BaseCommand):
    help = "Import a YNAB budget"

    def handle(self, *args: Any, **options: Any):
        register_filename = "Swiss Budget as of 2023-04-22 21-35 - Register.csv"
        with open(register_filename, newline='', encoding='utf-8-sig') as file:
            reader = csv.reader(file)
            header = next(reader)
            if len(header) != 11 or header[3] != 'Payee':
                raise ValueError('Wrong file type')
            self.process(map(Record.from_row, reader))

    @transaction.atomic
    def process(self, reader: 'Iterable[Record]'):
        user = User.objects.get(username="admin")
        target_budget, _ = Budget.objects.get_or_create(
            name="ynabimport", budget_of=user)

        raw_transaction_parts: 'list[Record]' = []
        for record in reader:
            raw_transaction_parts.append(record)
            if iscomplete(record):
                self.save(target_budget, raw_transaction_parts)
                raw_transaction_parts = []

    def save(self, target_budget: Budget, raw_transaction_parts: 'list[Record]'):
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
                name=raw_account
            )
            transaction_account_parts[account] += raw_transaction_part_inflow

            raw_payee = raw_transaction_part.Payee
            # Transfer between owned accounts
            if raw_payee.startswith(ynab_transfer_prefix):
                raw_transfer_account = raw_payee[len(
                    ynab_transfer_prefix):]
                if raw_account == raw_transfer_account:
                    raise Exception(
                        f'Account "{raw_account}" and Transfer Account "{raw_transfer_account}" are identical')
                # don't want to duplicate transfers: skip these ones (but this doesn't work when only one is an on-budget transaction and has extra information)
                elif raw_account < raw_transfer_account:
                    return None

                transfer_account, _ = Account.objects.get_or_create(
                    budget=target_budget,
                    name=raw_transfer_account
                )
                transaction_account_parts[transfer_account] += raw_transaction_part_outflow

            else:  # Payment to external payee
                payee, _ = Budget.objects.get_or_create(
                    name=raw_payee,
                    payee_of=target_budget.budget_of
                )
                payee_account = payee.get_hidden(Account, currency="")
                transaction_account_parts[payee_account] += raw_transaction_part_outflow

                category, _ = Category.objects.get_or_create(
                    budget=target_budget,
                    name=raw_transaction_part.CategoryGroupCategory
                )
                transaction_category_parts[category] += raw_transaction_part_inflow
                payee_category = payee.get_hidden(Category, currency="")
                transaction_category_parts[payee_category] += raw_transaction_part_outflow
            assert sum(transaction_category_parts.values()) == 0
            assert sum(transaction_account_parts.values()) == 0
        transaction.set_parts_raw(accounts=transaction_account_parts,
                                  categories=transaction_category_parts)
        return None


def YNAB_string_to_date(ynab_string: str):
    return datetime.date(*[int(i) for i in ynab_string.split('.')][::-1])


def iscomplete(record: Record):
    raw_memo = record.Memo
    return not (raw_memo.startswith("Split")) or raw_memo.startswith("Split (1/")


def join_memos(raw_transaction_parts: 'list[Record]'):
    return ", ".join([
        re.sub(r"Split \(.*\) ", "", x.Memo)
        for x in raw_transaction_parts])
