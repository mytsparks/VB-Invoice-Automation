"""Small helpers for command line interaction, so commands can be tested without a keyboard."""
import sys


class Prompter:
    def __init__(self, write, input_fn=None, interactive: bool | None = None):
        self.write = write
        self.input_fn = input_fn
        self.interactive = sys.stdin.isatty() if interactive is None else interactive

    def ask(self, question: str, choices: dict[str, str], default: str) -> str:
        """Ask for one of the choices. choices maps the key letter to its label. Returns the key.

        When not interactive, or when input ends, the default is returned without asking.
        """
        if not self.interactive:
            return default
        menu = ", ".join(f"{key}={label}" for key, label in choices.items())
        while True:
            try:
                answer = (self.input_fn or input)(f"{question} ({menu}; Enter={default}): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                self.write("")
                return default
            if not answer:
                return default
            if answer in choices:
                return answer
            self.write(f"  Please enter one of {', '.join(choices)}.")

    def ask_text(self, question: str, required: bool = True) -> str:
        if not self.interactive:
            return ""
        while True:
            try:
                answer = (self.input_fn or input)(f"{question}: ").strip()
            except (EOFError, KeyboardInterrupt):
                self.write("")
                return ""
            if answer or not required:
                return answer
            self.write("  A note is required.")
