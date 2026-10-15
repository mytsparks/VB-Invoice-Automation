from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from config.ui import Prompter
from extraction.services import current_invoices
from intake.models import ProcessingRun
from matching.management.commands.match import tms_banner
from matching.models import MatchResult
from matching.render import render_match
from matching.services import override
from processing.services import ProcessAborted, WriteBudget, is_processed, process_match
from tms.base import TmsError
from tms.factory import get_tms_client


class Command(BaseCommand):
    help = "Send invoices marked ready to the TMS. This is the only command that writes to a TMS."

    def add_arguments(self, parser):
        parser.add_argument("--file", help="Only process invoices from files whose name contains this text.")
        parser.add_argument("--dry-run", action="store_true", help="Show every write that would be made without making any.")
        parser.add_argument("--yes", action="store_true", help="Process ready invoices without asking for each one. Held invoices are never processed this way.")
        parser.add_argument("--no-input", action="store_true", help="Never ask questions.")

    def handle(self, *args, **options):
        config = settings.APP
        try:
            client = get_tms_client(config)
            description = client.check()
        except (ValueError, TmsError) as exc:
            raise CommandError(str(exc)) from exc
        dry_run = options["dry_run"]
        self.stdout.write(f"[{tms_banner(client)}] {description}. " + ("DRY RUN, nothing will be written." if dry_run else "Writes are enabled."))

        matches = MatchResult.objects.filter(invoice__in=current_invoices()).select_related("invoice__document", "shipment")
        if options["file"]:
            matches = matches.filter(invoice__document__file_name__icontains=options["file"])
        matches = list(matches.order_by("invoice_id"))
        if not matches:
            self.stdout.write("No matched invoices. Run match first.")
            return

        prompter = Prompter(self.stdout.write, interactive=False if options["no_input"] else None)
        ready = [m for m in matches if m.can_process]
        held = [m for m in matches if not m.can_process]
        self.stdout.write(f"{len(ready)} invoice(s) ready, {len(held)} held for review.")
        if ready and not dry_run and not options["yes"] and not prompter.interactive:
            raise CommandError("Not running interactively. Add --yes to process ready invoices without prompts, or --dry-run to preview.")

        run = ProcessingRun.objects.create(command="process", dry_run=dry_run, documents_seen=len(matches))
        budget = WriteBudget(config.tms_max_writes_per_run)
        tally = Counter()
        try:
            self.process_ready(ready, client, budget, dry_run, run, prompter, options["yes"], tally)
            if held:
                self.handle_held(held, client, budget, dry_run, run, prompter, tally)
        except ProcessAborted as exc:
            raise CommandError(f"Run stopped. {exc}") from exc
        finally:
            run.finished_at = timezone.now()
            run.documents_sent = tally["processed"] + tally["discrepancy"]
            run.save()

        self.summary(tally, held, dry_run, budget, config)

    def process_ready(self, ready, client, budget, dry_run, run, prompter, auto_yes, tally):
        approve_all = auto_yes
        for index, match in enumerate(ready, start=1):
            self.stdout.write("-" * 78)
            if not dry_run and is_processed(match, client.mode):
                self.stdout.write(f"Invoice {match.invoice.invoice_number}: already written in an earlier run. Skipping.")
                tally["already_done"] += 1
                continue
            render_match(self.stdout.write, self.style, match.invoice, match, show_comparison=not approve_all)
            if not dry_run and not approve_all:
                answer = prompter.ask(f"[{index}/{len(ready)}] Send this invoice to the TMS?", {"y": "yes", "n": "no", "a": "yes to all remaining", "q": "quit"}, default="n")
                if answer == "q":
                    tally["declined"] += len(ready) - index + 1
                    self.stdout.write("Stopped by user.")
                    return
                if answer == "n":
                    tally["declined"] += 1
                    continue
                approve_all = answer == "a"
            self.run_one(match, client, budget, dry_run, run, tally)

    def handle_held(self, held, client, budget, dry_run, run, prompter, tally):
        self.stdout.write("=" * 78)
        self.stdout.write(f"{len(held)} invoice(s) are held for review and will not be sent unless a person approves them.")
        if dry_run or not prompter.interactive:
            for match in held:
                names = ", ".join(flag.flag_type.name for flag in match.flags.select_related("flag_type")) or "no shipment"
                self.stdout.write(f"  {match.invoice.invoice_number or '(no number)'} [{match.invoice.document.file_name}]: {names}")
            tally["held"] += len(held)
            return
        if prompter.ask("Walk through the held invoices now?", {"y": "yes", "n": "no"}, default="n") != "y":
            tally["held"] += len(held)
            return
        for index, match in enumerate(held, start=1):
            self.stdout.write("-" * 78)
            render_match(self.stdout.write, self.style, match.invoice, match)
            answer = prompter.ask(f"[{index}/{len(held)}] Override the flags and send anyway?", {"o": "override and send", "s": "skip", "q": "quit"}, default="s")
            if answer == "q":
                tally["held"] += len(held) - index + 1
                return
            if answer == "s":
                tally["held"] += 1
                continue
            note = prompter.ask_text("Why is it safe to send? A note is required")
            if not note:
                tally["held"] += 1
                continue
            override(match, note)
            tally["overridden"] += 1
            self.run_one(match, client, budget, dry_run, run, tally)

    def run_one(self, match, client, budget, dry_run, run, tally):
        result = process_match(match, client, budget, dry_run=dry_run, processing_run=run)
        tally[result.status] += 1
        style = {"processed": self.style.SUCCESS, "dry_run": self.style.SUCCESS, "already_done": str, "discrepancy": self.style.WARNING}.get(result.status, self.style.ERROR)
        self.stdout.write(style(f"  Result: {result.status.replace('_', ' ')}"))
        for message in result.messages:
            self.stdout.write(f"    {message}")

    def summary(self, tally, held, dry_run, budget, config):
        self.stdout.write("=" * 78)
        if dry_run:
            self.stdout.write(f"Dry run. {tally['dry_run']} invoice(s) would be written.")
        else:
            self.stdout.write(f"Done. {tally['processed']} invoice(s) processed.")
        parts = [
            ("with read back discrepancies", tally["discrepancy"]), ("failed", tally["failed"]), ("already written earlier", tally["already_done"]),
            ("declined by you", tally["declined"]), ("approved despite flags", tally["overridden"]), ("held for review", tally["held"]),
            ("stopped at the write cap", tally["stopped"]),
        ]
        for label, number in parts:
            if number:
                self.stdout.write(f"  {number} {label}")
        if not dry_run:
            self.stdout.write(f"  {config.tms_max_writes_per_run - budget.remaining} write(s) used of {config.tms_max_writes_per_run}.")
        if tally["failed"]:
            self.stdout.write("Failed invoices were recorded with the TMS error. Fix the cause and run process again, since finished writes are not repeated.")
