from textual.app import App, ComposeResult
from textual.widgets import Input, RichLog, Static, Footer
from textual.containers import Vertical, Horizontal
from textual.reactive import reactive
from textual import work
from textual.timer import Timer
from rich.text import Text
from rich.markup import escape
import os

ASCII_LOGO = """
 ████████╗███████╗██████╗ ███╗   ███╗ █████╗  ██████╗ ███████╗███╗   ██╗████████╗
    ██╔══╝██╔════╝██╔══██╗████╗ ████║██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
    ██║   █████╗  ██████╔╝██╔████╔██║███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   
    ██║   ██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   
    ██║   ███████╗██║  ██║██║ ╚═╝ ██║██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   
    ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝  
"""

TAGLINE = "[ Natural Language → PowerShell  •  Groq  •  Windows Native ]"

# Braille spinner frames
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

CSS = """
Screen {
    background: #0a0e1a;
    layout: vertical;
}

#header {
    height: auto;
    padding: 1 2;
    background: #0a0e1a;
    border-bottom: tall #1a2040;
}

#logo {
    color: #00d4ff;
    text-style: bold;
    content-align: center middle;
}

#tagline {
    color: #3a5080;
    content-align: center middle;
    margin-top: 0;
}

#status-bar {
    height: 1;
    background: #0f1628;
    padding: 0 2;
    layout: horizontal;
}

#cwd-label {
    color: #00d4ff;
    width: auto;
}

#model-label {
    color: #2a4060;
    width: 1fr;
    content-align: right middle;
}

#output-log {
    background: #0a0e1a;
    border: none;
    padding: 1 2;
    scrollbar-color: #1a2040;
    scrollbar-background: #0a0e1a;
    height: 1fr;
}

#status-line {
    height: 1;
    padding: 0 4;
    background: #0a0e1a;
    color: #00d4ff;
}

#input-container {
    height: auto;
    padding: 0 2 1 2;
    background: #0a0e1a;
    border-top: tall #1a2040;
}

#prompt-label {
    color: #00d4ff;
    width: auto;
    padding: 1 0 0 0;
    text-style: bold;
}

#user-input {
    background: #0f1628;
    border: tall #1a3050;
    color: #e0f0ff;
    padding: 0 1;
    height: 3;
    width: 1fr;
}

#user-input:focus {
    border: tall #00d4ff;
}

Footer {
    background: #060810;
    color: #2a4060;
}
"""


class TermAgent(App):
    CSS = CSS
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear"),
    ]

    cwd = reactive(os.getcwd())

    def compose(self) -> ComposeResult:
        with Vertical(id="header"):
            yield Static(ASCII_LOGO, id="logo")
            yield Static(TAGLINE, id="tagline")

        with Horizontal(id="status-bar"):
            yield Static(id="cwd-label")
            yield Static("⬡  llama-3.3-70b-versatile  •  Groq Inference", id="model-label")

        yield RichLog(id="output-log", highlight=True, markup=True, wrap=True)

        # Status line — sits between log and input, shows spinner or result in place
        yield Static("", id="status-line")

        with Horizontal(id="input-container"):
            yield Static("❯", id="prompt-label")
            yield Input(placeholder="Ask me anything or describe what to do...", id="user-input")

        yield Footer()

    def on_mount(self) -> None:
        self._confirmation_handler = None
        self._spinner_timer: Timer | None = None
        self._spinner_frame = 0
        self.update_cwd_label()
        log = self.query_one("#output-log", RichLog)
        log.write(Text.from_markup(
            "[dim]Type a command in plain English or ask a question. Type [bold cyan]bye[/bold cyan] to exit.[/dim]\n"
        ))
        self.query_one("#user-input", Input).focus()

    def watch_cwd(self, new_cwd: str) -> None:
        self.update_cwd_label()

    def update_cwd_label(self) -> None:
        label = self.query_one("#cwd-label", Static)
        label.update(f"  {self.cwd}")

    # ── Spinner helpers ──────────────────────────────────────────────────────

    def _start_spinner(self) -> None:
        """Start animating the status line with a spinner."""
        self._spinner_frame = 0
        self._spinner_timer = self.set_interval(0.08, self._tick_spinner)

    def _tick_spinner(self) -> None:
        """Called every 80ms to advance the spinner frame."""
        frame = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
        self._spinner_frame += 1
        status = self.query_one("#status-line", Static)
        status.update(Text.from_markup(f"[cyan]{frame}[/cyan] [dim cyan]thinking...[/dim cyan]"))

    def _stop_spinner(self) -> None:
        """Stop the spinner timer."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _set_status(self, markup: str) -> None:
        """Replace status line content (called after spinner stops)."""
        status = self.query_one("#status-line", Static)
        status.update(Text.from_markup(markup))

    def _clear_status(self) -> None:
        status = self.query_one("#status-line", Static)
        status.update("")

    # ── Input handling ───────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Confirmation flow takes priority
        if self._confirmation_handler:
            self._confirmation_handler(event)
            return

        user_input = event.value.strip()
        if not user_input:
            return

        input_widget = self.query_one("#user-input", Input)
        input_widget.clear()

        if user_input.lower() == "bye":
            self.exit()
            return

        log = self.query_one("#output-log", RichLog)
        log.write(Text.from_markup(f"\n[bold cyan]❯[/bold cyan] [white]{user_input}[/white]"))
        self._start_spinner()
        self.process_input(user_input)

    # ── Agent worker ─────────────────────────────────────────────────────────

    @work(thread=True)
    def process_input(self, user_input: str) -> None:
        from termagent.agent.graph import app as agent_app
        import termagent.agent.nodes as nodes
        import threading

        outer_self = self

        def patched_confirm(state):
            cmd = state['cmd']
            result_holder = {}
            confirmed_event = threading.Event()

            def ask():
                outer_self._ask_confirmation(cmd, result_holder, confirmed_event)

            outer_self.call_from_thread(ask)
            confirmed_event.wait()
            return {"confirmation": result_holder.get("answer", "no")}

        nodes._confirm_fn = patched_confirm

        try:
            state = {"text": user_input, "cwd": self.cwd, "user_name": os.getenv("EMAIL_USERNAME")}
            result = agent_app.invoke(state)

            new_cwd = result.get("cwd", self.cwd)
            output = result.get("result", "Command cancelled.")
            intent = result.get("intent", "command")

            self.call_from_thread(self._update_output, output, intent, new_cwd)
        except Exception as e:
            self.call_from_thread(self._stop_spinner)
            self.call_from_thread(
                self._set_status,
                f"[bold red]✗ Error: {escape(str(e))}[/bold red]"
            )
        finally:
            nodes._confirm_fn = None

    # ── HITL confirmation ─────────────────────────────────────────────────────

    def _ask_confirmation(self, cmd: str, result_holder: dict, event) -> None:
        # Stop spinner while waiting for user
        self._stop_spinner()
        self._set_status("[bold yellow]⚠ Risky command — type yes or no[/bold yellow]")

        log = self.query_one("#output-log", RichLog)
        log.write(Text.from_markup(
            f"\n[bold yellow]  Risky command detected:[/bold yellow]\n"
            f"  [bold white]{escape(cmd)}[/bold white]\n"
            f"[dim yellow]  Type [bold]yes[/bold] to confirm or [bold]no[/bold] to cancel[/dim yellow]"
        ))

        input_widget = self.query_one("#user-input", Input)
        input_widget.placeholder = "yes / no"

        def on_confirm(submit_event: Input.Submitted):
            answer = submit_event.value.strip().lower()
            if answer in ["yes", "no"]:
                input_widget.clear()
                input_widget.placeholder = "Ask me anything or describe what to do..."
                result_holder["answer"] = answer
                log.write(Text.from_markup(
                    f"[dim]  → {'[green]Confirmed[/green]' if answer == 'yes' else '[red]Cancelled[/red]'}[/dim]"
                ))
                # Restart spinner while agent continues
                self._start_spinner()
                self._confirmation_handler = None
                event.set()
            else:
                log.write(Text.from_markup("[dim yellow]  Please type yes or no[/dim yellow]"))

        self._confirmation_handler = on_confirm

    # ── Output rendering ──────────────────────────────────────────────────────

    def _update_output(self, output: str, intent: str, new_cwd: str) -> None:
        self._stop_spinner()
        log = self.query_one("#output-log", RichLog)

        if intent == "chat":
            self._set_status("[dim cyan]◌ responded[/dim cyan]")
            log.write(Text.from_markup(f"  [white]{escape(output)}[/white]"))
        else:
            if output.startswith("Error:"):
                self._set_status("[bold red]✗ Error[/bold red]")
                log.write(Text.from_markup(f"[bold red]  ✗[/bold red] [red]{escape(output)}[/red]"))
            elif output == "Command cancelled by user.":
                self._set_status("[dim]✗ Cancelled[/dim]")
            else:
                self._set_status("[bold green]✓ Done[/bold green]")
                lines = output.strip().splitlines()
                if lines and output != "Command executed successfully.":
                    for line in lines:
                        log.write(Text.from_markup(f"  [dim]{escape(line)}[/dim]"))

        self.cwd = new_cwd

    def action_clear(self) -> None:
        self.query_one("#output-log", RichLog).clear()
        self._clear_status()

def main():
    from dotenv import load_dotenv
    load_dotenv()

    groq_key = os.getenv("GROQ_API_KEY")
    email_user = os.getenv("EMAIL_ADDRESS")
    email_pass = os.getenv("EMAIL_PASSWORD")
    
    if not email_user:
        print("Email credentials not found.")
        print("Email credentials will only be used when sending an email.")
        print("""
            Google doesn't allow regular passwords for SMTP. They need to generate an App Password:

            Go to Google Account → Security → 2-Step Verification → App Passwords
            Generate one for "Mail"
        """)
        email_user_name = input("Enter your name(used for email signatures): ")
        email_user = input("Enter your email address: ").strip()
        email_pass = input("Enter your email password/app password: ").strip()
        
        save = input("Save to .env for future use? (yes/no): ")
        if save.lower() == "yes":
            with open(".env", "a") as f:
                f.write(f"\nEMAIL_ADDRESS={email_user}")
                f.write(f"\nEMAIL_PASSWORD={email_pass}")
                f.write(f"\nEMAIL_USERNAME={email_user_name}")

        os.environ["EMAIL_ADDRESS"] = email_user
        os.environ["EMAIL_PASSWORD"] = email_pass
        os.environ["EMAIL_USERNAME"] = email_user_name
    
    if not groq_key:
        print("Groq API key not found.")
        groq_key = input("Enter your Groq API key: ").strip()

        save = input("Save to .env for future use? (yes/no): ")
        if save.lower() == "yes":
            with open(".env", "a") as f:
                f.write(f"\nGROQ_API_KEY={groq_key}")
            print("Saved!")

        os.environ["GROQ_API_KEY"] = groq_key

    app = TermAgent()
    app.run()

if __name__ == "__main__":
    main()