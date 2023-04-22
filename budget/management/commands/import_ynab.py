
from django.core.management.base import BaseCommand, CommandParser
from budget.models import *


class Command(BaseCommand):
    help = "Import a YNAB budget"

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("directory")

    def handle(self, *args: Any, directory: str, **options: Any):
        print(directory)
