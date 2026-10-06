from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from config.env import ConfigError, require_llm_key
from extraction.claude import ClaudeExtractor
from extraction.services import RunAborted, extract_documents
from intake.models import Document, ProcessingRun


def add_extract_arguments(parser):
    parser.add_argument("--dry-run", action="store_true", help="Show counts and estimated cost without calling the API.")
    parser.add_argument("--force", action="store_true", help="Extract again even when a cached result exists.")
    parser.add_argument("--file", help="Only process documents whose file name contains this text.")


def run_extraction(command, options, processing_command="extract"):
    config = settings.APP
    documents = Document.objects.exclude(status=Document.Status.UNSUPPORTED)
    if options.get("file"):
        documents = documents.filter(file_name__icontains=options["file"])
    documents = list(documents)
    if not documents:
        command.stdout.write("No documents to process. Run ingest first.")
        return

    extractor = None
    if not options["dry_run"]:
        try:
            extractor = ClaudeExtractor(require_llm_key(config), config.claude_model)
        except ConfigError as exc:
            raise CommandError(str(exc)) from exc

    processing_run = ProcessingRun.objects.create(
        command=processing_command, dry_run=options["dry_run"], documents_seen=len(documents)
    )
    command.stdout.write(f"Model {config.claude_model}. {len(documents)} document(s) registered.")
    try:
        summary = extract_documents(
            documents,
            extractor,
            dry_run=options["dry_run"],
            force=options["force"],
            processing_run=processing_run,
            write=command.stdout.write,
        )
    except RunAborted as exc:
        raise CommandError(f"Run stopped. {exc}") from exc
    finally:
        processing_run.finished_at = timezone.now()
        processing_run.save()

    processing_run.documents_sent = summary.sent
    processing_run.estimated_cost_usd = summary.estimated if options["dry_run"] else summary.spent
    processing_run.notes = summary.stopped_reason
    processing_run.save()

    if summary.stopped_reason:
        command.stdout.write(command.style.WARNING(summary.stopped_reason))
    if options["dry_run"]:
        command.stdout.write(f"Dry run. {summary.sent} would be sent, estimated cost ${summary.estimated:.3f} (rough).")
    else:
        command.stdout.write(
            f"Done. {summary.extracted} invoice document(s), {summary.non_invoice} non-invoice, "
            f"{summary.failed} failed, {summary.cached} cached, {summary.blocked} blocked. "
            f"Estimated cost ${summary.spent:.3f}."
        )
    if summary.blocked:
        command.stdout.write(
            "Blocked files are real client files. Set ALLOW_REAL_INVOICES_TO_LLM=true in .env "
            "only once you are approved to send them to the Claude API."
        )
    command.stdout.write("Run python manage.py show to review the results.")


class Command(BaseCommand):
    help = "Run Claude extraction on ingested documents."

    def add_arguments(self, parser):
        add_extract_arguments(parser)

    def handle(self, *args, **options):
        run_extraction(self, options)
