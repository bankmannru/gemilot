import os
import subprocess
import time
import sys
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
import concurrent.futures
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QTextEdit, QLineEdit, QPushButton, 
                            QLabel, QTabWidget, QSplitter, QFrame, QScrollArea)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QIcon, QTextCursor, QColor, QPalette, QSyntaxHighlighter, QTextCharFormat

# Initialize Rich console
console = Console()

# Load environment variables
load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))

class BatchSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        # Command format
        command_format = QTextCharFormat()
        command_format.setForeground(QColor("#569CD6"))  # Blue
        self.highlighting_rules.append((
            r'\b(start|echo|cd|mkdir|rmdir|del|copy|move|ren|type|cls|exit|pause|rem|@echo)\b',
            command_format
        ))

        # Path format
        path_format = QTextCharFormat()
        path_format.setForeground(QColor("#CE9178"))  # Orange
        self.highlighting_rules.append((
            r'[A-Za-z]:\\[\\\S|*\S]?.*',
            path_format
        ))

        # Comment format
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6A9955"))  # Green
        self.highlighting_rules.append((
            r'rem.*$',
            comment_format
        ))

    def highlightBlock(self, text):
        import re
        for pattern, format in self.highlighting_rules:
            expression = re.compile(pattern, re.IGNORECASE)
            for match in expression.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), format)

class GeminiWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, prompt):
        super().__init__()
        self.prompt = prompt
        self.max_retries = 3
        self.retry_delay = 2  # seconds
        
    def run(self):
        retries = 0
        last_error = None
        
        while retries < self.max_retries:
            try:
                model = genai.GenerativeModel('gemini-2.0-flash')
                response = model.generate_content(self.prompt)
                self.finished.emit(response.text)
                return
            except Exception as e:
                last_error = str(e)
                retries += 1
                if retries < self.max_retries:
                    # Wait before retrying
                    time.sleep(self.retry_delay)
                else:
                    # If all retries failed, emit the error
                    error_message = f"Connection error after {retries} attempts: {last_error}"
                    self.error.emit(error_message)

class CommandHistoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        
        self.history_list = QTextEdit()
        self.history_list.setReadOnly(True)
        self.history_list.setFont(QFont("Consolas", 10))
        
        layout.addWidget(QLabel("Command History"))
        layout.addWidget(self.history_list)
        
        self.setLayout(layout)
        
    def add_command(self, command):
        cursor = self.history_list.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(f"{command}\n")
        self.history_list.setTextCursor(cursor)
        self.history_list.ensureCursorVisible()

class HelpWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        
        help_text = """
        <h2>Gemilot Help</h2>
        
        <h3>Basic Usage:</h3>
        <ol>
            <li>Type your command in the input field</li>
            <li>Press Enter or click the Send button</li>
            <li>The command will be executed automatically</li>
        </ol>
        
        <h3>Command Examples:</h3>
        <ul>
            <li>"Open Notepad"</li>
            <li>"Open Chrome and go to google.com"</li>
            <li>"Create a new folder called test"</li>
            <li>"Type 'Hello World' in Notepad"</li>
            <li>"Close Chrome"</li>
        </ul>
        
        <h3>Tips:</h3>
        <ul>
            <li>Be specific in your commands</li>
            <li>Use natural language</li>
            <li>Check the command preview before execution</li>
        </ul>
        """
        
        help_label = QLabel(help_text)
        help_label.setWordWrap(True)
        help_label.setTextFormat(Qt.TextFormat.RichText)
        
        scroll = QScrollArea()
        scroll.setWidget(help_label)
        scroll.setWidgetResizable(True)
        
        layout.addWidget(scroll)
        self.setLayout(layout)

class GemilotGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gemilot")
        # Set window flags for frameless, always on top, and tool window
        self.setWindowFlags(
            Qt.WindowType.Window | 
            Qt.WindowType.Tool | 
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Get screen geometry and set window size
        screen = QApplication.primaryScreen().geometry()
        self.panel_width = 400
        self.setGeometry(screen.width() - self.panel_width, 0, self.panel_width, screen.height())
        
        # Create main widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # Create and set the main layout
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create the panel container
        panel_container = QFrame()
        panel_container.setObjectName("panelContainer")
        panel_layout = QVBoxLayout(panel_container)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        
        # Header with logo and collapse button
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(40)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 10, 0)
        
        # Logo and title
        logo_label = QLabel("🤖")
        logo_label.setObjectName("logo")
        title_label = QLabel("Gemilot")
        title_label.setObjectName("title")
        
        # Collapse button
        self.collapse_button = QPushButton("→")
        self.collapse_button.setObjectName("collapseButton")
        self.collapse_button.clicked.connect(self.toggle_collapse)
        
        header_layout.addWidget(logo_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.collapse_button)
        
        # Chat area
        chat_area = QFrame()
        chat_area.setObjectName("chatArea")
        chat_layout = QVBoxLayout(chat_area)
        chat_layout.setContentsMargins(10, 10, 10, 10)
        chat_layout.setSpacing(10)
        
        # Create scroll area for chat
        scroll = QScrollArea()
        scroll.setObjectName("chatScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Create widget to hold messages
        self.messages_widget = QWidget()
        self.messages_widget.setObjectName("messagesWidget")
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(5, 5, 5, 5)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch()
        
        scroll.setWidget(self.messages_widget)
        chat_layout.addWidget(scroll)
        
        # Input area at the bottom
        input_container = QFrame()
        input_container.setObjectName("inputContainer")
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(10, 10, 10, 10)
        
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Ask me anything...")
        self.command_input.returnPressed.connect(self.process_command)
        input_layout.addWidget(self.command_input)
        
        # Add widgets to panel layout
        panel_layout.addWidget(header)
        panel_layout.addWidget(chat_area)
        panel_layout.addWidget(input_container)
        
        # Add panel container to main layout
        main_layout.addWidget(panel_container)
        
        # Initialize state
        self.is_collapsed = False
        self.screen_width = screen.width()
        
        # Set stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background: transparent;
            }
            #panelContainer {
                background-color: #1E1E1E;
                border-left: 1px solid #3C3C3C;
            }
            #header {
                background-color: #252526;
                border-bottom: 1px solid #3C3C3C;
            }
            #logo {
                font-size: 20px;
            }
            #title {
                color: #D4D4D4;
                font-size: 14px;
                font-weight: bold;
            }
            #collapseButton {
                background: transparent;
                color: #D4D4D4;
                border: none;
                font-size: 16px;
                padding: 5px 10px;
            }
            #collapseButton:hover {
                background-color: #3C3C3C;
                border-radius: 4px;
            }
            #chatArea {
                background-color: #1E1E1E;
            }
            #chatScroll {
                background: transparent;
                border: none;
            }
            #chatScroll QScrollBar:vertical {
                background: #1E1E1E;
                width: 8px;
                margin: 0;
            }
            #chatScroll QScrollBar::handle:vertical {
                background: #3C3C3C;
                min-height: 20px;
                border-radius: 4px;
            }
            #chatScroll QScrollBar::add-line:vertical,
            #chatScroll QScrollBar::sub-line:vertical {
                height: 0;
            }
            #messagesWidget {
                background: transparent;
            }
            #inputContainer {
                background-color: #1E1E1E;
                border-top: 1px solid #3C3C3C;
            }
            QLineEdit {
                background-color: #252526;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #007ACC;
            }
            QLabel[cssClass="userMessage"] {
                background-color: #007ACC;
                color: white;
                padding: 8px 12px;
                border-radius: 12px;
                border-bottom-right-radius: 4px;
                font-size: 13px;
            }
            QLabel[cssClass="botMessage"] {
                background-color: #2D2D2D;
                color: #D4D4D4;
                padding: 8px 12px;
                border-radius: 12px;
                border-bottom-left-radius: 4px;
                font-size: 13px;
            }
        """)
    
    def add_message(self, text, is_user=True):
        """Add a message bubble to the chat area."""
        # Create message container
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create message label
        message = QLabel(text)
        message.setWordWrap(True)
        message.setProperty("cssClass", "userMessage" if is_user else "botMessage")
        message.setMinimumWidth(50)
        message.setMaximumWidth(300)
        
        # Add message to the appropriate side
        if is_user:
            container_layout.addStretch()
            container_layout.addWidget(message)
        else:
            container_layout.addWidget(message)
            container_layout.addStretch()
        
        # Remove the stretch at the end if it exists
        while self.messages_layout.count() > 0 and self.messages_layout.itemAt(self.messages_layout.count() - 1).spacerItem():
            item = self.messages_layout.takeAt(self.messages_layout.count() - 1)
            if item.spacerItem():
                del item
        
        # Add the new message
        self.messages_layout.addWidget(container)
        
        # Add stretch at the end
        self.messages_layout.addStretch()
        
        # Scroll to bottom
        QApplication.processEvents()
        scroll_area = container.parent().parent()
        if isinstance(scroll_area, QScrollArea):
            vsb = scroll_area.verticalScrollBar()
            vsb.setValue(vsb.maximum())
    
    def process_command(self):
        command = self.command_input.text().strip()
        if not command:
            return
            
        # Add user message
        self.add_message(command, is_user=True)
        
        # Clear input
        self.command_input.clear()
        
        # Create prompt for Gemini
        prompt = f"""Convert the following request into Windows batch commands. 
        Only output the batch commands, nothing else. Each command should be on a new line.
        If the request is not possible or unsafe, respond with 'ERROR: [reason]'
        
        Request: {command}"""
        
        # Start Gemini worker
        self.worker = GeminiWorker(prompt)
        self.worker.finished.connect(self.handle_gemini_response)
        self.worker.error.connect(self.handle_gemini_error)
        self.worker.start()
    
    def handle_gemini_response(self, response):
        if response.startswith("ERROR:"):
            self.add_message(response[6:], is_user=False)
            return
            
        # Clean up the response
        cleaned_response = self.clean_gemini_response(response)
        
        # Add bot message showing the commands
        self.add_message("Executing commands:\n" + cleaned_response, is_user=False)
        
        try:
            # Execute commands
            self.execute_commands(cleaned_response.split('\n'))
            self.add_message("Commands executed successfully!", is_user=False)
        except Exception as e:
            self.add_message(f"Error executing commands: {str(e)}", is_user=False)
    
    def handle_gemini_error(self, error_message):
        self.add_message(f"Error: {error_message}", is_user=False)
    
    def clean_gemini_response(self, response):
        """Clean up Gemini response by removing Markdown code block syntax."""
        lines = response.strip().split('\n')
        
        if len(lines) >= 2:
            if lines[0].startswith('```'):
                lines = lines[1:]
            if lines[-1].strip() == '```':
                lines = lines[:-1]
        
        return '\n'.join(lines)
    
    def execute_commands(self, commands):
        try:
            # Filter out empty lines and strip whitespace
            commands = [cmd.strip() for cmd in commands if cmd.strip()]
            
            # Create batch content with proper encoding
            batch_content = "@echo off\r\n"
            batch_content += "\r\n".join(commands)
            
            # Write file with UTF-8 encoding
            with open("temp_commands.bat", "w", encoding='utf-8', newline='\r\n') as f:
                f.write(batch_content)
            
            # Execute batch file
            process = subprocess.Popen(
                ["cmd.exe", "/c", "temp_commands.bat"],
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
            )
            
            stdout, stderr = process.communicate()
            
            # Clean up
            if os.path.exists("temp_commands.bat"):
                os.remove("temp_commands.bat")
                
            if stderr:
                raise Exception(stderr)
                
        except Exception as e:
            if os.path.exists("temp_commands.bat"):
                os.remove("temp_commands.bat")
            raise Exception(str(e))
    
    def toggle_collapse(self):
        if self.is_collapsed:
            # Expand - slide in from right
            self.setGeometry(self.screen_width - self.panel_width, 0, self.panel_width, self.height())
            self.collapse_button.setText("→")
        else:
            # Collapse - slide out to right
            self.setGeometry(self.screen_width - 40, 0, self.panel_width, self.height())
            self.collapse_button.setText("←")
        
        self.is_collapsed = not self.is_collapsed
    
    # Override mouse events to prevent dragging
    def mousePressEvent(self, event):
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

class GemilotCLI:
    def __init__(self):
        self.console = Console()
        self.command_history = []
        self.start_time = datetime.now()

    def create_batch_file(self, commands):
        """Create a temporary batch file with the given commands."""
        try:
            # Filter out empty lines and strip whitespace
            commands = [cmd.strip() for cmd in commands if cmd.strip()]
            
            # Create batch content with proper encoding
            batch_content = "@echo off\r\n"
            batch_content += "\r\n".join(commands)
            
            # Write file with UTF-8 encoding
            with open("temp_commands.bat", "w", encoding='utf-8', newline='\r\n') as f:
                f.write(batch_content)
                
        except Exception as e:
            raise Exception(f"Error creating batch file: {str(e)}")

    def execute_batch_file(self):
        """Execute the temporary batch file."""
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
            ) as progress:
                progress.add_task(description="Executing commands...", total=None)
                
                # Use explicit cmd.exe call with proper encoding
                process = subprocess.Popen(
                    ["cmd.exe", "/c", "temp_commands.bat"],
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8'
                )
                
                stdout, stderr = process.communicate()
                
                # Clean up
                if os.path.exists("temp_commands.bat"):
                    os.remove("temp_commands.bat")
                    
                if stderr:
                    raise Exception(stderr)
                    
                return stdout
                
        except Exception as e:
            if os.path.exists("temp_commands.bat"):
                os.remove("temp_commands.bat")
            raise Exception(f"Error executing batch file: {str(e)}")

    def get_gemini_response(self, prompt):
        """Get response from Gemini model with timeout and retry logic."""
        max_retries = 3
        retry_delay = 2  # seconds
        
        for retry in range(max_retries):
            try:
                model = genai.GenerativeModel('gemini-2.0-flash')
                
                # Create a function to generate content
                def generate():
                    response = model.generate_content(prompt)
                    return response.text

                # Use ThreadPoolExecutor with timeout
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(generate)
                    try:
                        response = future.result(timeout=30)  # 30 second timeout
                        return response
                    except concurrent.futures.TimeoutError:
                        raise TimeoutError("The request took too long to complete. Please try again.")
                    except Exception as e:
                        raise Exception(f"Error getting response from Gemini: {str(e)}")
                        
            except Exception as e:
                if retry < max_retries - 1:
                    console.print(f"[yellow]Connection error, retrying in {retry_delay} seconds... (Attempt {retry+1}/{max_retries})[/yellow]")
                    time.sleep(retry_delay)
                else:
                    raise Exception(f"Failed to get response after {max_retries} attempts: {str(e)}")

    def show_welcome_message(self):
        """Display welcome message and help information."""
        welcome_text = """
        # 🚀 Welcome to Gemilot! 🚀
        
        Your AI-powered OS assistant powered by Gemini.
        
        ## Available Commands:
        - Type any natural language command
        - Type 'help' for more information
        - Type 'history' to see command history
        - Type 'exit' to quit
        
        ## Examples:
        - "Open Notepad"
        - "Open Chrome and go to google.com"
        - "Create a new folder called test"
        - "Type 'Hello World' in Notepad"
        """
        
        console.print(Panel(Markdown(welcome_text), title="Gemilot", border_style="blue"))

    def show_help(self):
        """Display help information."""
        help_text = """
        # 📚 Gemilot Help
        
        ## Basic Usage:
        1. Simply type your command in natural language
        2. Gemilot will convert it to system commands
        3. The commands will be executed automatically
        
        ## Command Examples:
        - "Open Notepad"
        - "Open Chrome and go to google.com"
        - "Create a new folder called test"
        - "Type 'Hello World' in Notepad"
        - "Close Chrome"
        
        ## Special Commands:
        - 'help': Show this help message
        - 'history': Show command history
        - 'exit': Quit the application
        """
        
        console.print(Panel(Markdown(help_text), title="Help", border_style="green"))

    def show_history(self):
        """Display command history."""
        if not self.command_history:
            console.print("[yellow]No commands in history yet.[/yellow]")
            return

        history_text = "\n".join(f"{i+1}. {cmd}" for i, cmd in enumerate(self.command_history))
        console.print(Panel(history_text, title="Command History", border_style="yellow"))

    def show_command_preview(self, commands):
        """Show a preview of the commands that will be executed."""
        syntax = Syntax("\n".join(commands), "batch", theme="monokai")
        console.print(Panel(syntax, title="Command Preview", border_style="cyan"))

    def run(self):
        """Main application loop."""
        self.show_welcome_message()
        
        while True:
            try:
                user_input = Prompt.ask("\n[bold blue]You[/bold blue]").strip()
                
                if user_input.lower() == 'exit':
                    console.print("[bold green]Goodbye! 👋[/bold green]")
                    break
                elif user_input.lower() == 'help':
                    self.show_help()
                    continue
                elif user_input.lower() == 'history':
                    self.show_history()
                    continue
                elif user_input.lower().startswith('local:'):
                    # Handle local commands
                    local_command = user_input[6:].strip()
                    self.execute_local_command(local_command)
                    continue
                
                # Add command to history
                self.command_history.append(user_input)
                
                # Create a prompt that instructs Gemini to generate batch commands
                prompt = f"""Convert the following request into Windows batch commands. 
                Only output the batch commands, nothing else. Each command should be on a new line.
                If the request is not possible or unsafe, respond with 'ERROR: [reason]'
                
                Request: {user_input}"""
                
                try:
                    with console.status("[bold green]Thinking...[/bold green]"):
                        response = self.get_gemini_response(prompt)
                    
                    if response.startswith("ERROR:"):
                        console.print(f"[bold red]Error:[/bold red] {response[6:]}")
                        self.offer_fallback()
                        continue
                    
                    # Clean up the response
                    cleaned_response = self.clean_gemini_response(response)
                    
                    # Show command preview
                    commands = cleaned_response.split('\n')
                    self.show_command_preview(commands)
                    
                    # Create and execute batch file
                    self.create_batch_file(commands)
                    self.execute_batch_file()
                    console.print("[bold green]Commands executed successfully![/bold green]")
                
                except TimeoutError as e:
                    console.print(f"[bold red]Timeout Error:[/bold red] {str(e)}")
                    self.offer_fallback()
                except Exception as e:
                    console.print(f"[bold red]Error:[/bold red] {str(e)}")
                    self.offer_fallback()
                
            except Exception as e:
                console.print(f"[bold red]An error occurred:[/bold red] {str(e)}")

    def execute_local_command(self, command):
        """Execute a command locally without using Gemini."""
        try:
            # Create batch file with proper encoding
            batch_content = "@echo off\r\n"
            batch_content += command.strip()
            
            with open("temp_commands.bat", "w", encoding='utf-8', newline='\r\n') as f:
                f.write(batch_content)
                
            # Execute batch file
            self.output_area.append(f"<span style='color: #4EC9B0;'>Executing local command: {command}</span>")
            
            process = subprocess.Popen(
                ["cmd.exe", "/c", "temp_commands.bat"],
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
            )
            
            stdout, stderr = process.communicate()
            
            # Clean up
            if os.path.exists("temp_commands.bat"):
                os.remove("temp_commands.bat")
                
            # Show output
            if stdout:
                self.output_area.append("<span style='color: #DCDCAA;'>Output:</span>")
                self.output_area.append(stdout)
                
            if stderr:
                self.output_area.append("<span style='color: #F14C4C;'>Errors:</span>")
                self.output_area.append(stderr)
                
            self.output_area.append("<span style='color: #4EC9B0;'>Command executed successfully!</span>")
            self.statusBar().showMessage("Ready")
            
        except Exception as e:
            self.output_area.append(f"<span style='color: #F14C4C;'>Error executing command: {str(e)}</span>")
            self.statusBar().showMessage("Error occurred")
    
    def offer_fallback(self):
        """Offer fallback options for common commands when Gemini API fails."""
        console.print("\n[bold cyan]Would you like to try a local fallback for common commands?[/bold cyan]")
        console.print("Common commands that can be handled locally:")
        console.print("- Open applications (notepad, chrome, etc.)")
        console.print("- Create folders")
        console.print("- Basic file operations")
        console.print("\nTry these commands:")
        console.print("- Type 'local: open notepad' to open Notepad")
        console.print("- Type 'local: open chrome' to open Chrome")
        console.print("- Type 'local: mkdir test_folder' to create a test folder")

def main():
    # Check if GUI mode is requested
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        app = QApplication(sys.argv)
        window = GemilotGUI()
        window.show()
        sys.exit(app.exec())
    else:
        # Run in CLI mode
        gemilot = GemilotCLI()
        gemilot.run()

if __name__ == "__main__":
    main() 