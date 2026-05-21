import json
import base64
import os
import platform
import re
import mimetypes
import requests
import shlex
import signal
import subprocess
import sys
import select
import shutil
import termios
import time
import traceback
import tty
import pty
import string

from dotenv import load_dotenv
from threading import Event
from typing import Dict, List, Optional, Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

# TODO: allow manual specification of reasoning intensity or allowed tokens. resets on model change
# TODO: allow models to call other models such as gemini/claude 

MODELS = {
    # Claude
    'opus46':   {'name': 'anthropic/claude-opus-4.6', 'provider': 'openrouter', 'reasoning': 'medium'},
    'opus45':   {'name': 'anthropic/claude-opus-4.5', 'provider': 'openrouter', 'reasoning': 'medium'},
    'sonnet45': {'name': 'anthropic/claude-sonnet-4.5', 'provider': 'openrouter', 'reasoning': 32768},
    'sonnet46': {'name': 'anthropic/claude-sonnet-4.6', 'provider': 'openrouter', 'reasoning': 32768},
    'haiku':    {'name': 'anthropic/claude-haiku-4.5', 'provider': 'openrouter', 'reasoning': 32768},

    # GPT
    'gpt54':      {'name': 'openai/gpt-5.4', 'provider': 'openrouter', 'reasoning': 'medium'},
    'gpt54mini':  {'name': 'openai/gpt-5.4-mini', 'provider': 'openrouter', 'reasoning': 'high'},
    'gpt53codex': {'name': 'openai/gpt-5.3-codex', 'provider': 'openrouter', 'reasoning': 'medium'},
    'oss':        {'name': 'openai/gpt-oss-120b', 'provider': 'openrouter', 'reasoning': 'high'},

    # Gemini
    '25pro':  {'name': 'google/gemini-2.5-pro', 'provider': 'openrouter', 'reasoning': 16384},
    '25flash':{'name': 'google/gemini-2.5-flash-preview-09-2025', 'provider': 'openrouter', 'reasoning': 24576},
    '3pro':   {'name': 'google/gemini-3-pro-preview', 'provider': 'openrouter', 'reasoning': 'medium'},
    '31pro':  {'name': 'google/gemini-3.1-pro-preview', 'provider': 'openrouter', 'reasoning': 'medium'},
    '3flash': {'name': 'google/gemini-3-flash-preview', 'provider': 'openrouter', 'reasoning': 'high'},

    # GLM
    'glm5': {'name': 'z-ai/glm-5.1', 'provider': 'openrouter', 'reasoning': 32768},

    # Kimi
    'k25': {'name': 'moonshotai/kimi-k2.5', 'provider': 'openrouter', 'reasoning': 'high'},
    'k26': {'name': 'moonshotai/kimi-k2.6', 'provider': 'openrouter', 'reasoning': 'high'},

    # Minimax
    'm25': {'name': 'minimax/minimax-m2.5', 'provider': 'openrouter', 'reasoning': 'high'},
    'm27': {'name': 'minimax/minimax-m2.7', 'provider': 'openrouter', 'reasoning': 'high'},

    # Gemma4
    'gemma431': {'name': 'google/gemma-4-31b-it', 'provider': 'openrouter', 'reasoning': 'high'},
    'gemma426': {'name': 'google/gemma-4-26b-a4b-it', 'provider': 'openrouter', 'reasoning': 'high'},

    # Qwen
    'qwen36': {'name': 'qwen/qwen3.6-plus', 'provider': 'openrouter', 'reasoning': 'high'},

    # Ollama (local)
    'qwen3.6:35b':     {'name': 'qwen3.6:35b', 'provider': 'ollama'},
    'gemma4:31b':      {'name': 'gemma4:31b', 'provider': 'ollama'},
    'qwen3.5:35b':     {'name': 'qwen3.5:35b', 'provider': 'ollama'},
    'gemma4:26b':      {'name': 'gemma4:26b', 'provider': 'ollama'},
    'gpt-oss:20b':     {'name': 'gpt-oss:20b', 'provider': 'ollama'},
    'gemma4:latest':   {'name': 'gemma4:latest', 'provider': 'ollama'},
    'qwen3-coder:30b': {'name': 'qwen3-coder:30b', 'provider': 'ollama'},
}

# ANSI color codes
class Colors:
    GREEN = '\033[92m'
    BLUE = '\033[94m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    GREY = '\033[90m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

load_dotenv()

# Read-only command lists for security checks
TEXTRO = ('cat', 'cut', 'diff', 'echo', 'fmt', 'grep', 'head', 'nl', 'paste', 'printf', 'rev', 'rg', 'sort', 'tail', 'tr', 'uniq', 'wc', 'sed', 'awk', 'jq')
FSRO = ('cd', 'basename', 'cmp', 'comm', 'df', 'dirname', 'du', 'file', 'ls', 'pwd', 'realpath', 'stat', 'tree', 'find')
SYSRO = ('cal', 'date', 'dmesg', 'history', 'hostname', 'id', 'lsof', 'man', 'ps', 'uname', 'uptime', 'who', 'whoami')
NETRO = ('dig', 'host', 'netstat', 'ping', 'traceroute', 'curl')
MISCRO = ('clear', 'false', 'less', 'more', 'seq', 'sleep', 'test', 'true', 'whereis', 'which', 'yes', 'ffprobe')
MACOSRO = ('jq',) # 'open', 'xargs' unsafe
ROLIST = TEXTRO + FSRO + SYSRO + NETRO + MISCRO + MACOSRO

def get_single_key():
    """Get a single key press without requiring Enter."""
    try:
        # Unix/Linux/macOS
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
            # Handle escape sequences
            if ord(ch) == 27:  # ESC key
                return 'escape'
            elif ord(ch) == 13 or ord(ch) == 10:  # Enter/Return
                return 'enter'
            else:
                return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except (ImportError, AttributeError, termios.error):
        # Fallback for Windows or if termios is not available
        try:
            import msvcrt
            ch = msvcrt.getch()
            if isinstance(ch, bytes):
                ch = ch.decode('utf-8')
            if ord(ch) == 27:
                return 'escape'
            elif ord(ch) == 13:
                return 'enter'
            else:
                return ch.lower()
        except ImportError:
            # Ultimate fallback - use input()
            return input().lower()

def _tokenize_shell_command(command: str) -> Optional[List[str]]:
    """Tokenizes a shell command using shlex, preserving operators and merging '&&'/'||'."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';|&')
        lexer.whitespace_split = True
        raw_tokens = list(lexer)

        # Merge && and || back together
        tokens = []
        i = 0
        while i < len(raw_tokens):
            tok = raw_tokens[i]
            if i + 1 < len(raw_tokens) and raw_tokens[i + 1] == tok and tok in {'&', '|'}:
                tokens.append(tok * 2)  # '&&' or '||'
                i += 2
            else:
                tokens.append(tok)
                i += 1
        return tokens
    except ValueError:
        return None

def command_is_readonly(command: str) -> bool:
    """Check if a shell command is likely to be read-only."""
    if not (command := command.strip()):
        return True

    tokens = _tokenize_shell_command(command)
    if tokens is None:
        return False

    if not tokens:
        return True

    unsafe_operators = ['>', '>>', '<<', '<<<', '>&', '<&', '2>', '2>>']
    if any(op in tokens for op in unsafe_operators):
        return False

    commands = [[]]
    for token in tokens:
        if token in ['|', '&&', '||', ';']:
            commands.append([])
        else:
            commands[-1].append(token)

    for cmd_tokens in commands:
        if not cmd_tokens:
            continue
        base_command = cmd_tokens[0]
        if base_command == 'git' and len(cmd_tokens) > 1 and cmd_tokens[1] not in {
              'status', 'diff', 'ls-files', 'ls-tree', 'log', 'show', 'blame', 'cat-file', 'ls-remote'
            }: return False
        elif base_command == 'curl' and any(flag in cmd_tokens for flag in {'-X', '-d', '--data', '-F', '--form', '-T', '--upload-file', '-o', '--output'}):
            return False
        elif base_command in ('awk', 'sed') and any(flag in cmd_tokens for flag in {'-i', '--in-place'}):
            return False
        elif base_command == 'find' and any(action in cmd_tokens for action in {'-delete'}):
            return False
        elif base_command == 'find' and '-exec' in cmd_tokens:
            # Analyze the command being executed by find -exec
            exec_index = cmd_tokens.index('-exec')
            # Find the command after -exec (skip -exec itself)
            if exec_index + 1 < len(cmd_tokens):
                exec_command = cmd_tokens[exec_index + 1]
                # Check if the executed command is read-only
                if exec_command not in ROLIST:
                    return False
                # Also check if the exec command has any unsafe flags
                exec_cmd_tokens = cmd_tokens[exec_index + 1:]
                if ';' in exec_cmd_tokens:
                    semicolon_index = exec_cmd_tokens.index(';')
                    exec_cmd_tokens = exec_cmd_tokens[:semicolon_index]
                
                # Check the executed command for safety
                if exec_command == 'grep' and any(flag in exec_cmd_tokens for flag in {'-l', '-n', '-c', '-i', '-v', '-E', '-F'}):
                    # grep with read-only flags is safe
                    continue
                elif exec_command in TEXTRO + FSRO + SYSRO + NETRO + MISCRO + MACOSRO:
                    # Safe commands executed via -exec
                    continue
                else:
                    return False
        elif base_command not in ROLIST:
            return False
    return True

def _sanitize_tool_id(tool_id: str) -> str:
    """Sanitize a tool call ID to conform to ^[a-zA-Z0-9_-]+$ pattern required by some providers."""
    # Check if the tool ID is already in the valid format
    # This preserves Anthropic's tool call IDs like: toolu_01TwhwfVhevX2qfM5cpk3e2i
    if re.match(r'^[a-zA-Z0-9_-]+$', str(tool_id)):
        return str(tool_id)

    # Replace any disallowed character with an underscore
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', str(tool_id))
    # Collapse consecutive underscores that may have been introduced
    sanitized = re.sub(r'__+', '_', sanitized)
    # Strip leading/trailing underscores to keep things neat
    return sanitized.strip('_') or 'toolcall'

def _content_to_text(content) -> str:
    """Best-effort: extract text from either a plain string or an OpenAI-style multimodal content array."""
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: List[str] = []
        for part in content:
            if isinstance(part, dict) and part.get('type') == 'text':
                txt = part.get('text')
                if isinstance(txt, str) and txt:
                    texts.append(txt)
        return '\n'.join(texts)
    return str(content)

def _is_url_like(s: str) -> bool:
    s = (s or '').strip().lower()
    return s.startswith('http://') or s.startswith('https://') or s.startswith('data:')

def _image_ref_to_image_url(ref: str) -> str:
    """Convert a user-provided image ref (URL or local file path) into an image_url.url value."""
    ref = (ref or '').strip()
    if not ref:
        raise ValueError("empty image ref")

    if _is_url_like(ref):
        return ref

    path = os.path.expanduser(os.path.expandvars(ref))
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"not a file: {path}")

    size = os.path.getsize(path)
    if size > 15 * 1024 * 1024:
        raise ValueError(f"file too large ({size} bytes): {path}")

    mime, _ = mimetypes.guess_type(path)
    if not mime or not mime.startswith('image/'):
        raise ValueError(f"not an image file (unrecognized type): {path}")

    with open(path, 'rb') as f:
        data = f.read()
    b64 = base64.b64encode(data).decode('ascii')
    return f"data:{mime};base64,{b64}"

def _parse_inline_tool_calls(content: str) -> List[Dict]:
    """Parse inline tool calls from content using executeshell({"command": "command_goes_here"}) format."""
    tool_calls = []
    # Pattern for the original executeshell({...}) format
    original_pattern = r'executeshell\s*\(\s*(\{.*?\})\s*\)'

    # Pattern for the new <｜tool calls begin｜>...<｜tool calls end｜> format
    # Accept both regular spaces and the U+2581 "▁" separator used by some wrappers
    new_wrapper_pattern = r'<｜tool[\s▁]calls[\s▁]begin｜>(.*?)<｜tool[\s▁]calls[\s▁]end｜>'
    # The specific tool call pattern inside the wrapper
    new_tool_call_pattern = r'<｜tool[\s▁]call[\s▁]begin｜>\s*executeshell<｜tool[\s▁]sep｜>(\{.*?\})\s*<｜tool[\s▁]call[\s▁]end｜>'

    # First, find and process the new wrapper format
    wrapper_matches = re.finditer(new_wrapper_pattern, content, re.MULTILINE | re.DOTALL)
    for i, wrapper_match in enumerate(wrapper_matches):
        wrapped_content = wrapper_match.group(1)

        tool_call_matches = re.finditer(new_tool_call_pattern, wrapped_content, re.MULTILINE | re.DOTALL)
        for j, tc_match in enumerate(tool_call_matches):
            args_str = tc_match.group(1).strip()
            try:
                args = json.loads(args_str)
                command = args.get('command')
                if command:
                    tool_call = {
                        'id': f'inline_new_{int(time.time())}_{i}_{j}',
                        'name': 'executeshell',
                        'args': {
                            'command': command,
                        }
                    }
                    tool_calls.append(tool_call)
                else:
                    print(f"{Colors.RED}Error: Tool call missing 'command' argument in new format: {args_str}{Colors.RESET}")
            except json.JSONDecodeError:
                print(f"Warning: Could not parse tool call JSON from new format: {args_str}")
                continue

    # Then, find and process the original executeshell({...}) format
    original_matches = re.finditer(original_pattern, content, re.MULTILINE | re.DOTALL)
    for i, match in enumerate(original_matches):
        args_str = match.group(1).strip()
        
        try:
            # Parse the JSON to handle proper escaping
            args = json.loads(args_str)
            command = args.get('command')
            if command:
                tool_call = {
                    'id': f'inline_old_{int(time.time())}_{i}',
                    'name': 'executeshell',
                    'args': {
                        'command': command,
                    }
                }
                tool_calls.append(tool_call)
            else:
                print(f"{Colors.RED}Error: Tool call missing 'command' argument in original format: {args_str}{Colors.RESET}")
        except json.JSONDecodeError:
            # Skip malformed JSON
            print(f"Warning: Could not parse tool call JSON: {args_str}")
            continue
            
    # As a fallback, check for a markdown code block at the very end of the response,
    # but only if it is preceded by a colon.
    markdown_pattern = r':\s*(```(?:bash|shell|sh)\s*\n(?:.*?)\n```\s*)$'
    
    # We search on the stripped content to correctly find the end
    match = re.search(markdown_pattern, content.strip(), re.DOTALL)
    if match:
        # The command is inside the matched block
        block_content = match.group(1)
        inner_match = re.search(r'```(?:bash|shell|sh)\s*\n(.*?)\n```', block_content, re.DOTALL)
        if inner_match:
            command = inner_match.group(1).strip()
            if command:
                tool_calls.append({
                    'id': f'inline_md_{int(time.time())}',
                    'name': 'executeshell',
                    'args': {'command': command}
                })
            else:
                print(f"{Colors.RED}Error: Tool call missing command in markdown format{Colors.RESET}")
    return tool_calls

def _remove_inline_tool_calls(content: str) -> str:
    """Remove inline tool call syntax from content for display."""
    cleaned_content = content
    
    # --- First, remove the specific markdown block if it exists ---
    # This pattern finds a block at the end of the string preceded by a colon,
    # and the replacement removes the block but keeps the colon.
    markdown_pattern = r'(:\s*)```(?:bash|shell|sh)\s*\n(?:.*?)\n```\s*$'
    # We use re.subn to see if a substitution was made.
    cleaned_content, num_subs = re.subn(markdown_pattern, r'\1', cleaned_content.rstrip(), count=1, flags=re.DOTALL)
    if num_subs > 0:
        return cleaned_content # Return early if we found and removed a markdown tool
    
    # --- If no markdown tool was found, clean up other formats ---
    pattern_original = r'executeshell\s*\(\s*\{.*?\}\s*\)'
    pattern_new_wrapper = r'<｜tool[\s ]calls[\s ]begin｜>.*?<｜tool[\s ]calls[\s ]end｜>'
    
    # Combine patterns with OR for general cleanup
    combined_pattern = f'{pattern_new_wrapper}|{pattern_original}'
    
    return re.sub(combined_pattern, '', content, flags=re.MULTILINE | re.DOTALL)
class CommandLineAIChat:
    """A command-line AI chat application using the OpenRouter library for various models."""

    def __init__(self):
        self.client = None
        self.conversation_history: List[Dict[str, str]] = []
        self.needs_prefix_reminder = False
        self.last_bot_name = 'sonnet46'
        self.retry_delays = [1.5]
        self.interrupt_event = Event()
        self.bot_running = False
        self.always_approve = False
        self.usage_history = []
        self.session_cost = 0.0
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.session_total_tokens = 0
        self.session_reasoning_tokens = 0
        self.session_cached_tokens = 0
        self.previous_cwd = os.getcwd()
        self.prompt_session = PromptSession(history=FileHistory(os.path.expanduser('~/.consai_history')))
        self.prefill_shell_mode = False
        self.last_request_payload: Optional[Dict] = None
        self.last_response_events: Optional[List[Dict]] = None
        self._has_shown_user_label_once = False
        self.pending_image_urls: List[str] = []

        self.shell_tool_definition = {
            'type': 'function',
            'function': {
                'name': 'executeshell',
                'description': 'Executes a shell command and returns its output.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'command': {'type': 'string', 'description': 'The shell command to execute.'},
                    },
                    'required': ['command']
                }
            }
        }
        self._initialize_client()
        self._setup_signal_handlers()

    def _initialize_client(self):
        """Initializes OpenRouter and Ollama REST configuration."""
        self.openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
        self.api_url = 'https://openrouter.ai/api/v1/chat/completions'
        self.ollama_base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1/chat/completions')

    def _setup_signal_handlers(self):
        """Sets up signal handlers for ctrl-c and ctrl-d behavior."""
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _play_completion_beep(self):
        """Play completion beep if available and not interrupted."""
        if not self.interrupt_event.is_set() and shutil.which('afplay'):
            # Run beep asynchronously to avoid interrupting UI flow
            try:
                subprocess.Popen(
                    ['afplay', '/System/Library/Sounds/Glass.aiff'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                # Silently fail if beep cannot be played
                pass

    def _handle_sigint(self, signum, frame):
        """Handles SIGINT (ctrl-c) based on current state."""
        if self.bot_running:
            # ctrl-c while bot is running: drop control back to user
            print(f"\n{Colors.YELLOW}[Bot interrupted by user]{Colors.RESET}")
            self.interrupt_event.set()
            self.bot_running = False
        else:
            # ctrl-c when user is in control: show help message
            print(f"\n{Colors.GREY}Type 'exit' or ctrl-d to quit{Colors.RESET}")
            print(f'{Colors.GREEN}User{Colors.RESET}:\n', end='', flush=True)

    def _format_context_for_gemini(self, max_messages: int = 5) -> str:
        """Format recent conversation history as context for Gemini CLI calls.
        
        Returns a string suitable for inclusion in a Gemini query.
        """
        if not self.conversation_history:
            return "No prior context."
        
        # Get last N messages
        recent = self.conversation_history[-max_messages:]
        context_lines = []
        
        for msg in recent:
            role = msg.get('role', 'unknown')
            content = _content_to_text(msg.get('content')).strip()
            
            # Skip empty messages
            if not content:
                continue
            
            # Truncate very long messages
            if len(content) > 200:
                content = content[:200] + "..."
            
            # Format based on role
            if role == 'user':
                context_lines.append(f"User: {content}")
            elif role == 'assistant':
                bot_id = msg.get('bot_id', 'assistant')
                context_lines.append(f"{bot_id.upper()}: {content}")
            elif role == 'tool':
                # Summarize tool output
                context_lines.append(f"[Tool executed, output truncated]")
        
        return "\n".join(context_lines) if context_lines else "No relevant context."

    def _get_system_prompt(self, bot_name: str, ask_mode: bool = False) -> str:
        assistantname = bot_name.upper()
        if ask_mode:
            return f"You are {assistantname}, a helpful AI assistant. Use your executeshell tool if needed."
        
        otherbotsinfo = ", ".join([f"{name.upper()}" for name, _ in MODELS.items() if name != bot_name])
        
        googleapikey = os.getenv('GOOGLE_SEARCH_API_KEY')
        googlecseid = os.getenv('GOOGLE_CSE_ID')

        welcome = f'''You are {assistantname}, a helpful AI assistant.
You are in a chatroom with User and OTHER helpful AI assistants: {otherbotsinfo}.'''
        tempdir = '%TEMP%' if platform.system() == 'Windows' else '/tmp'

        agentrules = ""
        for filepath in [os.path.expanduser('~/src/AGENTS.md'), './AGENTS.md']:
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r') as f:
                        agentrules += f"\n\nFollow these rules from {filepath}:\n{f.read()}"
                except Exception:
                    pass

        toolinstructions = f'''Your executeshell tool is powerful. Use it when needed.
Try your best to run shell commands in non-interactive mode e.g. `echo "command to run" | script`
Think creatively about how to chain simple shell commands to solve any problem. Long command chains are BEST.
Break complex tasks down into multiple tool calls if needed.

Use google to search the web:
`curl "https://www.googleapis.com/customsearch/v1?key={googleapikey}&cx={googlecseid}&q=YOUR_QUERY" | jq '[.items[] | {{title, link, snippet}}]'`

All backup files or temporary scripts should go into {tempdir}.
Open and read files before mentioning them. Never guess what they contain. Always read them.
Directory: {os.getcwd()} | Date: {time.strftime('%Y-%m-%d')} | OS: {platform.system()}
{APPLYPATCH}
''' if bot_name not in ("gpt5c",) else 'You do not have any tools. Ask user for help instead.\n'

        conclusion = '''
        if you see the <[:~MODELNAME said~:]> prefix in an assistant message, it means that the model MODELNAME said it.
        if you see <[:~@MODELNAME:]> in a user message, it means the user addressed the message to the model MODELNAME.
        Never add <[:~MODELNAME said~:]> or <[:~@MODELNAME:]> to your responses.
        '''
        r= f'{welcome}\n\n{toolinstructions}\n\n{agentrules}\n\n{conclusion}'
        return r

    def _get_user_input(self):
        """Gets input from the user using prompt_toolkit for a better experience."""
        try:
            # Print the "User:" label on its own line first
            print(f'\n{Colors.GREEN}User:{Colors.RESET}')
            # Beep on user turn except the very first time
            if self._has_shown_user_label_once:
                self._play_completion_beep()
            else:
                self._has_shown_user_label_once = True
            
            # Determine the default text for the prompt
            default_text = '>' if self.prefill_shell_mode else ''

            # Get user input using the session with an empty message string
            user_text = self.prompt_session.prompt('', default=default_text)

            # Handle multi-line input using a simple check
            if user_text.strip() == 'BEGIN':
                print(f'{Colors.GREY}[Multi-line mode - type END to finish]{Colors.RESET}')
                lines = []
                while True:
                    try:
                        line = self.prompt_session.prompt('') # No prompt for subsequent lines
                        if line.strip() == 'END':
                            break
                        lines.append(line)
                    except (EOFError, KeyboardInterrupt):
                        print("\nGoodbye!")
                        sys.exit(0)
                return '\n'.join(lines)
            
            return user_text

        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            sys.exit(0)
            return None

    def _parse_input(self, user_text):
        """Parses user input for commands and text."""
        ask_mode = '/ask' in user_text
        user_text = user_text.replace('/ask', '').strip()

        bot_commands = []
        for bot in MODELS:
            # Match /bot followed by end of string, whitespace, or punctuation
            pattern = rf'/{re.escape(bot)}(?=\s|$|[^\w])'
            if re.search(pattern, user_text):
                bot_commands.append(bot)
        for bot in bot_commands:
            user_text = user_text.replace(f'/{bot}', f'<[:~@{bot.upper()}:]>').strip()

        return user_text, bot_commands, ask_mode


    def _prepare_messages(self, bot_name: str, ask_mode: bool = False) -> List[Dict]:
        """Prepares the message list for the API call."""
        system_prompt = {'role': 'system', 'content': self._get_system_prompt(bot_name, ask_mode)}
        
        # Determine if last conversation entry was a failed applypatch tool call
        applypatch_failed_last = False
        if self.conversation_history:
            last_original_msg = self.conversation_history[-1]
            if last_original_msg.get('role') == 'tool' and last_original_msg.get('applypatch_failed'):
                applypatch_failed_last = True

        # Format conversation history to show bot identities
        formatted_history = []
        for msg in self.conversation_history:
            formatted_msg = None
            
            if msg['role'] == 'assistant' and 'bot_id' in msg:
                # Handle cases where assistant message might not have content (tool calls only)
                message_content = _content_to_text(msg.get('content')).strip()
                # Prepend the new said-tag label instead of "ASSISTANTNAME:"
                label = f"<[:~{msg['bot_id'].upper()} said~:]>"
                content = f"{label}\n{message_content}" if message_content else ""
                formatted_msg = {'role': 'assistant', 'content': content}
                if 'tool_calls' in msg:
                    # Ensure tool IDs meet provider requirements
                    sanitized_tool_calls = []
                    for tc in msg['tool_calls']:
                        tc_copy = tc.copy()
                        tc_copy['id'] = _sanitize_tool_id(tc_copy.get('id', ''))
                        sanitized_tool_calls.append(tc_copy)
                    formatted_msg['tool_calls'] = sanitized_tool_calls
            else:
                formatted_msg = msg.copy()
                if formatted_msg.get('role') == 'tool':
                    formatted_msg.pop('applypatch_failed', None)
            
            # Add reasoning_details if target is Gemini 3 Pro and they exist in history
            if bot_name in ('3pro', '3flash') and 'reasoning_details' in msg:
                formatted_msg['reasoning_details'] = msg['reasoning_details']
            elif 'reasoning_details' in formatted_msg:
                # Ensure we don't leak reasoning to other models if it was copied
                formatted_msg.pop('reasoning_details')
                
            formatted_history.append(formatted_msg)

        # If the last conversation entry was a failed applypatch tool call, add helper message temporarily
        reminders = []
        if applypatch_failed_last:
            reminders.append('Your applypatch failed. read patcherrors.txt for help, and craft a perfect patch this time.')
        if self.needs_prefix_reminder:
            reminders.append(f"Never add prefixes like <[:~{bot_name.upper()} said~:]> to your answers)")
        if reminders:
            formatted_history.append({'role': 'system', 'content': '\n'.join(reminders)})
        return [system_prompt] + formatted_history

    def _strip_said_tags(self, text: str) -> str:
        """Remove any occurrences of <[:~* said~:]> tags from text before storing."""
        try:
            return re.sub(r'<\[:~.*? said~:\]>', '', text, flags=re.DOTALL)
        except re.error:
            # Fail-safe: return text unchanged if regex fails to compile
            return text

    def _normalize_text_for_match(self, text: str) -> str:
        """Normalize text for comparing prompts when handling /revert.

        - Removes any inline bot addressing tags like <[:~@BOT:]> that we store in history
        - Removes explicit /bot tokens in the input (e.g., /kimi)
        - Collapses whitespace and lowercases for a robust, simple match
        """
        try:
            # Remove any assistant-address tags we may have inserted
            text = re.sub(r'<\[:~@.*?:\]>', ' ', text)
            # Remove any known /bot tokens (case-insensitive)
            bot_names = '|'.join([re.escape(name) for name in MODELS.keys()])
            text = re.sub(rf'/(?:{bot_names})\b', ' ', text, flags=re.IGNORECASE)
            # Collapse whitespace and lowercase
            text = re.sub(r'\s+', ' ', (text or '').strip())
            return text.lower()
        except Exception:
            return (text or '').strip().lower()

    def _executeshell_command(self, command: str, on_chunk: Optional[Callable[[str], None]] = None, require_approval: bool = True, echo_command: bool = True) -> str:
        """Executes a shell command after checking if it's safe.

        - Always attempts to run with a PTY (interactive-capable). If stdin is a TTY, keystrokes
          are forwarded to the child process. If not, falls back to a pseudo-tty wrapper via
          `script` and streams output line-by-line.
        - When using the PTY path, ctrl-c is forwarded to the child; no fixed timeout is applied.
        - When using the non-PTY streaming path, a 60s timeout is enforced.
        - If `on_chunk` is provided, output is streamed to the callback while accumulating the transcript.
        """
        if echo_command:
            print(f'\n{Colors.YELLOW}{command}{Colors.RESET}')
        if require_approval and not command_is_readonly(command) and not self.always_approve:
            try:
                self._play_completion_beep()  # Beep when asking for permission
                print(f'{Colors.RED}Run this command? (Yes / No / Always) {Colors.RESET}', end='', flush=True)
                response = get_single_key()
                
                if response in ('y', 'Y', 'enter'):
                    print('Yes')
                elif response in ('a', 'A'):
                    print('Always')
                    self.always_approve = True
                elif response in ('n', 'N', 'escape'):
                    print('No')
                    self.interrupt_event.set()
                    return 'Command execution cancelled by user.'
                else:
                    # Any other key means no
                    self.interrupt_event.set()
                    return 'Command execution cancelled by user.'
            except (EOFError, KeyboardInterrupt):
                self.interrupt_event.set()
                return 'Command execution cancelled by user.'
        
        # Always attempt interactive PTY mode: allocate a TTY and forward keystrokes + output
        try:
            if sys.stdin.isatty():
                return self._run_command_interactive_pty(command, on_chunk)
            else:
                preface = '[stdin is not a TTY; using pseudo-tty wrapper]\n'
                if on_chunk:
                    try:
                        on_chunk(preface)
                    except Exception:
                        pass
                # Wrap with script to force a pseudo-tty for better output behavior
                command = f'script -q /dev/null -c {shlex.quote(command)}'
        except Exception:
            # If any TTY checks fail, continue below with non-interactive path
            pass

        # Stream output using Popen so we can surface chunks and handle interrupts
        chunks: List[str] = []
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            # Enforce a hard timeout similar to previous behavior
            timeout_seconds = 60
            deadline = time.monotonic() + timeout_seconds

            # Read line-by-line with small polls so we can react to interrupts/timeouts
            assert proc.stdout is not None  # for type checkers
            try:
                while True:
                    # Interruption requested (e.g., ctrl-c)
                    if self.interrupt_event.is_set():
                        chunks.append('\n[Interrupted by user]\n')
                        if on_chunk:
                            try:
                                on_chunk('\n[Interrupted by user]\n')
                            except Exception:
                                pass
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                        try:
                            proc.wait(timeout=2)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                        break

                    # Handle timeout
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        chunks.append(f'\nCommand timed out after {timeout_seconds} seconds.\n')
                        if on_chunk:
                            try:
                                on_chunk(f'\nCommand timed out after {timeout_seconds} seconds.\n')
                            except Exception:
                                pass
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                        try:
                            proc.wait(timeout=2)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                        break

                    # Wait for data availability or process exit
                    try:
                        rlist, _, _ = select.select([proc.stdout], [], [], min(0.2, max(0.0, remaining)))
                    except (ValueError, OSError):
                        # Fallback: if select fails for any reason, attempt a blocking readline
                        rlist = [proc.stdout]

                    if rlist:
                        line = proc.stdout.readline()
                        if line == '':
                            # EOF: if process already exited, we are done
                            if proc.poll() is not None:
                                break
                            # No data but not exited yet; continue polling
                            continue
                        if on_chunk:
                            try:
                                on_chunk(line)
                            except Exception:
                                # Do not let callback failures disrupt command execution
                                pass
                        chunks.append(line)
                    else:
                        # Nothing ready; if process exited, stop
                        if proc.poll() is not None:
                            break
                        continue

                # Append return code if non-zero
                try:
                    rc = proc.wait(timeout=0.5)
                except Exception:
                    rc = proc.poll()
                if rc is not None and rc != 0:
                    chunks.append(f'\nReturn Code: {rc}')
                    if on_chunk:
                        try:
                            on_chunk(f'\nReturn Code: {rc}')
                        except Exception:
                            pass
            finally:
                try:
                    if proc.stdout:
                        proc.stdout.close()
                except Exception:
                    pass

            return ''.join(chunks)
        except Exception as e:
            traceback.print_exc()
            return f'Error executing command: {e}'

    def _change_directory(self, target: Optional[str], on_chunk: Optional[Callable[[str], None]] = None) -> (bool, str):
        """Change current working directory in-process. Returns (success, transcript)."""
        old_cwd = os.getcwd()
        try:
            if target is None or target.strip() == '':
                new_dir = os.path.expanduser('~')
            elif target == '-':
                # Swap with previous directory if available
                prev = self.previous_cwd or os.environ.get('OLDPWD') or old_cwd
                new_dir = prev
            else:
                new_dir = os.path.expanduser(os.path.expandvars(target))

            os.chdir(new_dir)
            # Update previous directory tracking
            self.previous_cwd, os.environ['OLDPWD'] = old_cwd, old_cwd
            msg = f"cwd: {os.getcwd()}\n"
            if on_chunk:
                try:
                    on_chunk(msg)
                except Exception:
                    pass
            return True, msg
        except Exception as e:
            msg = f"cd: {target if target else ''}: {e}\n"
            if on_chunk:
                try:
                    on_chunk(msg)
                except Exception:
                    pass
            return False, msg

    def _maybe_handle_cd_and_execute(self, command: str, on_chunk: Optional[Callable[[str], None]], require_approval: bool, echo_command: bool = True) -> Optional[str]:
        """If command starts with a cd, handle it in-process and optionally execute trailing command.

        Supports forms:
          cd
          cd path
          cd -
          cd path && rest
          cd path ; rest
        Returns the full transcript if handled, else None.
        """
        tokens = _tokenize_shell_command(command)
        if tokens is None:
            return None

        if not tokens or tokens[0] != 'cd':
            return None

        # Parse target and optional separator+rest
        target: Optional[str] = None
        sep: Optional[str] = None
        rest_tokens: List[str] = []

        j = 1
        if j < len(tokens) and tokens[j] not in {';', '&&', '||'}:
            target = tokens[j]
            j += 1
        if j < len(tokens) and tokens[j] in {';', '&&'}:  # ignore || for simplicity
            sep = tokens[j]
            j += 1
            rest_tokens = tokens[j:]

        # Change directory
        success, cd_msg = self._change_directory(target, on_chunk=on_chunk)

        transcript_parts: List[str] = [cd_msg]

        # Execute trailing command depending on separator rules
        if rest_tokens and (sep == ';' or (sep == '&&' and success)):
            # Reconstruct rest command with proper quoting
            def rejoin(ts: List[str]) -> str:
                out: List[str] = []
                for t in ts:
                    if t in {';', '&&', '||', '|'}:
                        out.append(t)
                    else:
                        out.append(shlex.quote(t))
                return ' '.join(out)

            rest_command = rejoin(rest_tokens)
            rest_output = self._executeshell_command(rest_command, on_chunk=on_chunk, require_approval=require_approval, echo_command=echo_command)
            transcript_parts.append(rest_output)

        return ''.join(transcript_parts)

    def _run_command_interactive_pty(self, command: str, on_chunk: Optional[Callable[[str], None]]) -> str:
        """Run command attached to a PTY, forwarding keystrokes and streaming output.

        - Sets the user's terminal to raw mode so all keys (including arrows, ctrl) pass through
        - Restores terminal settings on exit
        - Accumulates transcript and returns it at the end
        """
        master_fd, slave_fd = pty.openpty()
        transcript: List[str] = []

        stdin_fd = sys.stdin.fileno()
        old_tty = None
        try:
            # Put our stdin into raw mode so we can forward keys as-is
            old_tty = termios.tcgetattr(stdin_fd)
            tty.setraw(stdin_fd)
        except Exception:
            old_tty = None

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None,
            )
        finally:
            try:
                os.close(slave_fd)
            except Exception:
                pass

        try:
            while True:
                # Monitor both PTY master (child output) and our stdin (user keystrokes)
                rlist, _, _ = select.select([master_fd, stdin_fd], [], [], 0.05)

                if master_fd in rlist:
                    try:
                        data = os.read(master_fd, 4096)
                    except Exception:
                        data = b''
                    if data:
                        text = data.decode('utf-8', errors='replace')
                        transcript.append(text)
                        if on_chunk:
                            try:
                                on_chunk(text)
                            except Exception:
                                pass
                        else:
                            # Print raw to avoid color wrappers in interactive mode
                            print(text, end='', flush=True)
                    else:
                        # EOF; if process exited, break
                        if proc.poll() is not None:
                            break

                if stdin_fd in rlist:
                    try:
                        user_input = os.read(stdin_fd, 4096)
                        if user_input:
                            os.write(master_fd, user_input)
                    except Exception:
                        pass

                # If the bot was interrupted, forward SIGINT to the child
                if self.interrupt_event.is_set():
                    try:
                        if hasattr(os, 'killpg') and proc.pid:
                            os.killpg(proc.pid, signal.SIGINT)
                        else:
                            proc.send_signal(signal.SIGINT)
                    except Exception:
                        pass
                    # Give the child a moment to exit
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            if hasattr(os, 'killpg') and proc.pid:
                                os.killpg(proc.pid, signal.SIGTERM)
                            else:
                                proc.terminate()
                        except Exception:
                            pass
                    break

                # If the child exited naturally, stop
                if proc.poll() is not None:
                    break

            # Append return code if non-zero
            rc = proc.poll()
            if rc is not None and rc != 0:
                transcript.append(f'\nReturn Code: {rc}')
        finally:
            try:
                os.close(master_fd)
            except Exception:
                pass
            # Restore terminal mode
            if old_tty is not None:
                try:
                    termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_tty)
                except Exception:
                    pass

        return ''.join(transcript)

    def _record_and_print_usage(self, bot_name: str, usage: Dict) -> None:
        if not isinstance(usage, dict) or not usage:
            return

        cost = float(usage.get('cost') or 0)
        prompt_tokens = int(usage.get('prompt_tokens') or 0)
        completion_tokens = int(usage.get('completion_tokens') or 0)
        total_tokens = int(usage.get('total_tokens') or 0)
        reasoning_tokens = int((usage.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0)
        cached_tokens = int((usage.get('prompt_tokens_details') or {}).get('cached_tokens') or 0)

        self.session_cost += cost
        self.session_prompt_tokens += prompt_tokens
        self.session_completion_tokens += completion_tokens
        self.session_total_tokens += total_tokens
        self.session_reasoning_tokens += reasoning_tokens
        self.session_cached_tokens += cached_tokens

        self.usage_history.append({
            'timestamp': time.time(),
            'bot': bot_name,
            'model': MODELS.get(bot_name, {}).get('name', bot_name),
            'usage': usage
        })

        provider = MODELS.get(bot_name, {}).get('provider', 'openrouter')
        local_tag = " (local)" if provider == 'ollama' else ""
        print(f"\n{Colors.CYAN}Request: ${cost:.4f}{local_tag} ({prompt_tokens} up, {completion_tokens} down) | Session: ${self.session_cost:.4f} ({self.session_prompt_tokens} up, {self.session_completion_tokens} down){Colors.RESET}")

    def _print_stats(self):
        print(f"{Colors.BOLD}Session usage{Colors.RESET}")
        print(f"Total cost: {self.session_cost:.6f} credits")
        print(
            f"Total tokens: {self.session_total_tokens} "
            f"(prompt {self.session_prompt_tokens}, completion {self.session_completion_tokens}, "
            f"reasoning {self.session_reasoning_tokens}, cached {self.session_cached_tokens})"
        )
        if not self.usage_history:
            return
        for idx, rec in enumerate(self.usage_history, 1):
            t = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(rec['timestamp']))
            usage = rec['usage'] or {}
            cost = usage.get('cost') or 0
            upstream = (usage.get('cost_details') or {}).get('upstream_inference_cost')
            prompt_tokens = usage.get('prompt_tokens') or 0
            completion_tokens = usage.get('completion_tokens') or 0
            total_tokens = usage.get('total_tokens') or 0
            reasoning_tokens = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0
            cached_tokens = (usage.get('prompt_tokens_details') or {}).get('cached_tokens') or 0
            print(
                f"[{idx}] {t} | {rec['bot']} -> {rec['model']} | cost {cost:.6f} credits"
            )
            print(
                f"    tokens total {total_tokens}, prompt {prompt_tokens} (cached {cached_tokens}), "
                f"completion {completion_tokens} (reasoning {reasoning_tokens})"
            )
            if upstream is not None:
                print(f"    upstream_inference_cost {upstream}")


    def _print_last_json(self):
        """Prints the last JSON request and writes the response to a file for debugging."""
        print(f"\n{Colors.BOLD}--- LAST API CALL ---{Colors.RESET}")
        
        if self.last_request_payload:
            print(f"{Colors.CYAN}{Colors.BOLD}--- REQUEST ---{Colors.RESET}")
            try:
                print(f"{Colors.CYAN}{json.dumps(self.last_request_payload, indent=2)}{Colors.RESET}")
            except Exception as e:
                print(f"{Colors.RED}Error printing request: {e}{Colors.RESET}")
        else:
            print(f"{Colors.GREY}No request has been made in this session yet.{Colors.RESET}")

        if self.last_response_events:
            response_file_path = '/tmp/response.txt'
            print(f"\n{Colors.MAGENTA}{Colors.BOLD}--- RESPONSE ---{Colors.RESET}")
            try:
                with open(response_file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.last_response_events, f, indent=2)
                print(f"{Colors.MAGENTA}Last response written to {response_file_path}{Colors.RESET}")
            except Exception as e:
                print(f"{Colors.RED}Error writing response to file: {e}{Colors.RESET}")
        else:
            print(f"\n{Colors.GREY}No response has been received in this session yet.{Colors.RESET}")


    def _handle_tool_calls(self, tool_calls: List[Dict], bot_name: str):
        """Handles the execution of tool calls from the AI model."""

        for tool_call in tool_calls:
            if self.interrupt_event.is_set():
                break
            
            tool_name = tool_call['name']
            if tool_name == 'executeshell':
                try:
                    args = tool_call['args']
                    command = args.get('command')
                    # 'interactive' flag is no longer used; all commands run in interactive-capable mode
                    if command:
                        streamed_any = False

                        def _print_stream_chunk(text: str) -> None:
                            nonlocal streamed_any
                            streamed_any = True
                            # Always print raw to avoid breaking TUIs
                            print(text, end='', flush=True)

                        # First, check for an in-process cd (and optional trailing command)
                        handled = self._maybe_handle_cd_and_execute(command, on_chunk=_print_stream_chunk, require_approval=True, echo_command=False)
                        if handled is not None:
                            output = handled
                        else:
                            output = self._executeshell_command(command, on_chunk=_print_stream_chunk, echo_command=False)
                        tool_message = {
                            'role': 'tool',
                            'tool_call_id': _sanitize_tool_id(tool_call['id']),
                            'content': output
                        }
                        # If nothing was streamed (e.g. early cancel), print the content now
                        if not streamed_any and output:
                            print(f'{tool_message["content"]}', end='')
                        if (command and 'applypatch' in command and
                            output and not output.strip().startswith('Done!') and
                            not output.strip() == ''):
                            tool_message['applypatch_failed'] = True
                        self.conversation_history.append(tool_message)
                    else:
                        error_msg = "Error: Tool call missing 'command' argument"
                        print(f"{Colors.RED}{error_msg}{Colors.RESET}")
                        tool_message = {
                            'role': 'tool',
                            'tool_call_id': _sanitize_tool_id(tool_call['id']),
                            'content': error_msg
                        }
                        self.conversation_history.append(tool_message)
                except (KeyError, ValueError) as e:
                    error_msg = f"Error processing tool call: {e}"
                    tool_message = {
                        'role': 'tool',
                        'tool_call_id': _sanitize_tool_id(tool_call['id']),
                        'content': error_msg
                    }
                    print(f"{Colors.RED}{tool_message['content']}{Colors.RESET}")
                    self.conversation_history.append(tool_message)
            else:
                print(f"{Colors.RED}Unknown tool: {tool_name}{Colors.RESET}")
                tool_message = {
                    'role': 'tool',
                    'tool_call_id': _sanitize_tool_id(tool_call['id']),
                    'content': f"Error: Unknown tool '{tool_name}'"
                }
                self.conversation_history.append(tool_message)

        if not self.interrupt_event.is_set():
            self._call_bot(bot_name)

    def _parsedebate(self, text):
        """Parse /debate args into (topic, [(bot, position), ...], moderator)."""
        names = '|'.join(re.escape(n) for n in sorted(MODELS, key=len, reverse=True))
        allpat = re.compile(rf'/(mod:)?({names}|\w+)(?=\s|$|[^\w])', re.IGNORECASE)
        matches = list(allpat.finditer(text))
        if not matches: return None, None, None
        topic = text[:matches[0].start()].strip()
        if not topic: return None, None, None
        agents = []
        moderator = None
        for i, m in enumerate(matches):
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            pos = text[m.end():end].strip()
            name = m.group(2).lower()
            if m.group(1): moderator = name
            else: agents.append((name, pos))
        if len(agents) < 2: return None, None, None
        return topic, agents, moderator

    def _getdebatesystemprompt(self, botname, topic, position, allagents):
        others = ', '.join(
            f"{n.upper()} (arguing: {p})"
            for n, p in allagents if n != botname
        )
        pos = position if position else '(unspecified)'
        return (
            f"You are {botname.upper()} in a structured debate.\n"
            f"Topic: {topic}\n"
            f"Your position: {pos}\n"
            f"Other participants: {others}\n\n"
            f"Argue persuasively for your position. Respond to "
            f"previous arguments. Be concise (2-4 paragraphs).\n"
            f"Never add <[:~{botname.upper()} said~:]> to your "
            f"responses."
        )

    def _getmodsystemprompt(self, modname, topic, allagents, nextbotname=None):
        participants = ', '.join(
            f"{n.upper()} (arguing: {p})" if p else n.upper()
            for n, p in allagents
        )
        addressline = (f"Address {nextbotname.upper()} directly. "
                       f"Ask them 1 pointed question — the single most important "
                       f"question that cuts to the heart of the matter.\n"
                       if nextbotname else '')
        return (
            f"You are {modname.upper()} moderating a structured debate.\n"
            f"Topic: {topic}\n"
            f"Participants: {participants}\n\n"
            f"Your role:\n"
            f"- Identify the most important unaddressed points and weaknesses.\n"
            f"- Steer toward the strongest, most substantive lines of argument.\n"
            f"- Stay neutral. Do not argue for any position.\n"
            f"- Be concise.\n"
            f"{addressline}"
            f"Never add <[:~{modname.upper()} said~:]> to your responses."
        )

    def _preparedebatemessages(self, botname, topic, position, allagents, debatehistory, systempromptoverride=None):
        system = {'role': 'system', 'content': systempromptoverride or self._getdebatesystemprompt(botname, topic, position, allagents)}
        formatted = []
        for msg in debatehistory:
            if msg['role'] == 'assistant' and 'bot_id' in msg:
                label = f"<[:~{msg['bot_id'].upper()} said~:]>"
                content = msg.get('content', '')
                role = 'assistant' if msg['bot_id'] == botname else 'user'
                formatted.append({'role': role, 'content': f"{label}\n{content}" if content else ''})
            else: formatted.append(msg.copy())
        return [system] + formatted

    def _stream_chat(self, url: str, headers: dict, payload: dict) -> dict:
        """Make HTTP POST and stream SSE response. Returns accumulated state."""
        response = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            print(f"\n{Colors.RED}API call failed with status {response.status_code}{Colors.RESET}")
            try:
                print(f"{Colors.GREY}{response.text}{Colors.RESET}")
            except Exception:
                pass
            raise Exception(f"API call failed with status {response.status_code}")

        full_response = ''
        reasoning_details_acc = []
        tool_calls = {}
        first_chunk_content = True
        pending_whitespace = ''
        reasoning_printed = False
        last_usage = None
        response_events = []
        tool_calls_headers_printed = set()
        currently_streaming_tool_index = -1
        cancelled = False
        
        buffering_first_line = True
        first_line_buffer = ''

        STOP_TOKENS = {"<|im_start|>", "<|im_end|>", "<|endoftext|>", "<|repo_name|>"}

        for raw_line in response.iter_lines(decode_unicode=True):
            if self.interrupt_event.is_set():
                try:
                    response.close()
                except Exception:
                    pass
                break
            if not raw_line:
                continue
            line = raw_line.strip()
            if line.startswith(':'):
                continue
            if line.startswith('data:'):
                data = line[5:].strip()
            else:
                data = line
            if data == '[DONE]':
                break
            try:
                event = json.loads(data)
                response_events.append(event)
            except Exception:
                continue

            choices = event.get('choices', [])
            if not choices:
                continue
            delta = choices[0].get('delta', {})

            if event.get('usage'):
                last_usage = event.get('usage')

            if 'reasoning_details' in delta and delta.get('reasoning_details'):
                reasoning_details_acc.extend(delta.get('reasoning_details'))

            if 'reasoning' in delta and delta.get('reasoning'):
                reasoning_text = delta.get('reasoning')
                cleaned_reasoning = re.sub(r'^\s*\*\*.*?\*\*\s*\n*', '', reasoning_text, flags=re.MULTILINE)
                compact_reasoning = re.sub(r'\n{3,}', '\n\n', cleaned_reasoning)
                
                if compact_reasoning:
                    print(f"{Colors.GREY}{compact_reasoning}{Colors.RESET}", end='', flush=True)
                reasoning_printed = True

            content = delta.get('content')
            if content:
                full_response += content

                if buffering_first_line:
                    first_line_buffer += content
                    if '\n' in first_line_buffer:
                        line_to_print, remainder = first_line_buffer.split('\n', 1)
                        
                        cleaned_line = self._strip_said_tags(line_to_print)
                        cleaned_and_stripped = cleaned_line.lstrip()

                        if cleaned_and_stripped:
                            print(cleaned_and_stripped, end='', flush=True)
                            print('\n' + remainder, end='', flush=True)
                        else:
                            print(remainder, end='', flush=True)

                        buffering_first_line = False
                        first_chunk_content = False
                else:
                    if not content.isspace():
                        if pending_whitespace:
                            print(pending_whitespace, end='', flush=True)
                            pending_whitespace = ""
                        print(content, end='', flush=True)
                    else:
                        pending_whitespace += content
                
                stop_token_found = False
                for token in STOP_TOKENS:
                    if token in content:
                        stop_token_found = True
                        break
                if stop_token_found:
                    break

            if delta.get('tool_calls'):
                if buffering_first_line:
                    if first_line_buffer:
                        print(self._strip_said_tags(first_line_buffer).lstrip(), end='', flush=True)
                    buffering_first_line = False
                    first_chunk_content = False
                
                if self.interrupt_event.is_set():
                    try:
                        response.close()
                    except Exception:
                        pass
                    cancelled = True
                    break
                if not first_chunk_content and currently_streaming_tool_index == -1:
                     print()
                 
                first_chunk_content = False

                for tc in delta.get('tool_calls', []):
                    if self.interrupt_event.is_set():
                        try:
                            response.close()
                        except Exception:
                            pass
                        cancelled = True
                        break
                    index = tc.get('index', 0) if tc.get('index') is not None else 0

                    if currently_streaming_tool_index != -1 and currently_streaming_tool_index != index:
                        if tool_calls.get(currently_streaming_tool_index, {}).get('name') != 'executeshell':
                            print(f"{Colors.YELLOW}){Colors.RESET}\n", flush=True)
                        currently_streaming_tool_index = -1
                    
                    if index not in tool_calls:
                        tool_calls[index] = {'id': '', 'name': '', 'args': '', 'streaming_state': {}}
                    if 'id' in tc and tc.get('id'):
                        tool_calls[index]['id'] = _sanitize_tool_id(tc.get('id'))
                    function_obj = tc.get('function', {}) or {}
                    if function_obj.get('name'):
                        tool_calls[index]['name'] = function_obj.get('name')
                    
                    if tool_calls[index]['name'] and index not in tool_calls_headers_printed:
                        if tool_calls[index]['name'] != 'executeshell':
                            print(f"{Colors.YELLOW}{tool_calls[index]['name']}(", end='', flush=True)
                        tool_calls_headers_printed.add(index)
                        currently_streaming_tool_index = index

                    if function_obj.get('arguments'):
                        args_chunk = function_obj.get('arguments')
                        tool_calls[index]['args'] += args_chunk

                        if tool_calls[index]['name'] == 'executeshell':
                            state = tool_calls[index]['streaming_state']
                            full_args_str = tool_calls[index]['args']

                            if 'raw_pointer' not in state:
                                state['raw_pointer'] = 0
                                state['escape_buffer'] = ''
                                state['decoded_so_far'] = ''
                                print(f"{Colors.YELLOW}", end='')

                            command_regex = re.compile(r'\{\s*"command"\s*:\s*"(?P<command>(?:\\.|[^"\\])*)', re.DOTALL)
                            match = command_regex.search(full_args_str)

                            if match:
                                command_so_far = match.group('command')
                                new_raw = command_so_far[state['raw_pointer']:]
                                if new_raw:
                                    state['raw_pointer'] += len(new_raw)

                                    chunk = state['escape_buffer'] + new_raw
                                    state['escape_buffer'] = ''
                                    output_buffer = []
                                    i = 0
                                    length = len(chunk)

                                    while i < length:
                                        if self.interrupt_event.is_set():
                                            try:
                                                response.close()
                                            except Exception:
                                                pass
                                            cancelled = True
                                            break
                                        ch = chunk[i]
                                        if ch != '\\':
                                            output_buffer.append(ch)
                                            i += 1
                                            continue

                                        if i + 1 >= length:
                                            state['escape_buffer'] = '\\'
                                            i += 1
                                            break

                                        nxt = chunk[i + 1]
                                        i += 2

                                        if nxt == 'n':
                                            output_buffer.append('\n')
                                        elif nxt == 't':
                                            output_buffer.append('\t')
                                        elif nxt == 'r':
                                            output_buffer.append('\r')
                                        elif nxt == 'b':
                                            output_buffer.append('\b')
                                        elif nxt == 'f':
                                            output_buffer.append('\f')
                                        elif nxt == '"':
                                            output_buffer.append('"')
                                        elif nxt == '\\':
                                            output_buffer.append('\\')
                                        elif nxt == 'u':
                                            needed = 4
                                            if i + needed - 1 >= length:
                                                state['escape_buffer'] = '\\u' + chunk[i:]
                                                break
                                            hex_digits = chunk[i:i+needed]
                                            if all(c in string.hexdigits for c in hex_digits):
                                                output_buffer.append(chr(int(hex_digits, 16)))
                                                i += needed
                                            else:
                                                output_buffer.append('\\u' + hex_digits)
                                                i += needed
                                        elif nxt == 'x':
                                            needed = 2
                                            if i + needed - 1 >= length:
                                                state['escape_buffer'] = '\\x' + chunk[i:]
                                                break
                                            hex_digits = chunk[i:i+needed]
                                            if all(c in string.hexdigits for c in hex_digits):
                                                output_buffer.append(chr(int(hex_digits, 16)))
                                                i += needed
                                            else:
                                                output_buffer.append('\\x' + hex_digits)
                                                i += needed
                                        else:
                                            output_buffer.append('\\' + nxt)

                                    if output_buffer:
                                        text = ''.join(output_buffer)
                                        state['decoded_so_far'] += text
                                        print(text, end='', flush=True)
                                    if cancelled:
                                        try:
                                            print(Colors.RESET, flush=True)
                                        except Exception:
                                            pass
                                        currently_streaming_tool_index = -1
                                        break

                            try:
                                json.loads(full_args_str)
                                if state.get('escape_buffer'):
                                    trailing = state['escape_buffer']
                                    state['escape_buffer'] = ''
                                    state['decoded_so_far'] += trailing
                                    print(trailing, end='', flush=True)

                                print(Colors.RESET, flush=True)
                                currently_streaming_tool_index = -1
                                tool_calls[index]['streaming_state'] = {}
                            except json.JSONDecodeError:
                                pass

                        else:
                            print(f"{Colors.YELLOW}{args_chunk}", end='', flush=True)
                            if self.interrupt_event.is_set():
                                try:
                                    response.close()
                                except Exception:
                                    pass
                                cancelled = True
                                break

                if cancelled:
                    break

        if currently_streaming_tool_index != -1:
            if tool_calls.get(currently_streaming_tool_index, {}).get('name') != 'executeshell':
                print(f"{Colors.YELLOW}){Colors.RESET}\n", flush=True)
        
        if buffering_first_line and first_line_buffer:
            cleaned_and_stripped = self._strip_said_tags(first_line_buffer).lstrip()
            if cleaned_and_stripped:
                print(cleaned_and_stripped, end='', flush=True)
            first_chunk_content = False

        return {
            'full_response': full_response,
            'tool_calls': tool_calls,
            'reasoning_details_acc': reasoning_details_acc,
            'last_usage': last_usage,
            'response_events': response_events,
            'cancelled': cancelled,
            'reasoning_printed': reasoning_printed,
            'first_chunk_content': first_chunk_content,
            'currently_streaming_tool_index': currently_streaming_tool_index,
            'tool_calls_headers_printed': tool_calls_headers_printed,
        }

    def _prepare_request(self, model_key: str, messages: list, include_tools: bool = True):
        """Prepare URL, headers, and payload for a chat API request."""
        provider = MODELS[model_key].get('provider', 'openrouter')

        if provider == 'openrouter':
            if not self.openrouter_api_key:
                print(f"{Colors.RED}Error: OPENROUTER_API_KEY environment variable not set.{Colors.RESET}")
                raise Exception("OPENROUTER_API_KEY not set")

            headers = {
                'Authorization': f'Bearer {self.openrouter_api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://www.nairaland.com',
                'X-Title': 'Nairaland Forum',
                'Accept': 'text/event-stream'
            }

            payload = {
                'model': MODELS[model_key]['name'],
                'messages': messages,
                'stream': True,
                'provider': {
                    'sort': 'latency',
                    'ignore': ['deepinfra/fp4', 'baseten/fp4'],
                    'order': ['openai', 'anthropic', 'z-ai', 'alibaba', 'xai',
                              'moonshotai', 'minimax/fp8', 'google-ai-studio',
                              'google-vertex', 'parasail/bf16', 'parasail',
                              'fireworks', 'deepinfra/bf16', 'novita', 'novita/fp8',
                              'stealth', 'deepseek', 'atlas-cloud/fp8', 'siliconflow/fp8'],
                    'allow_fallbacks': False
                },
                'temperature': 0.6,
                'usage': {'include': True}
            }

            if model_key[:4] == 'qwen':
                payload['temperature'] = 0.7
                payload['top_p'] = 0.8
                payload['top_k'] = 20
                payload['repetition_penalty'] = 1.05

            if include_tools and model_key not in ('gpt5c',):
                payload['tools'] = [self.shell_tool_definition]
                payload['tool_choice'] = 'auto'

            if model_key == 'kimi':
                payload['temperature'] = 0.6
                payload['min-p'] = 0.01

            if r := MODELS[model_key].get('reasoning'):
                if isinstance(r, int):
                    payload['reasoning'] = {'max_tokens': r, 'enabled': True, 'exclude': False}
                elif isinstance(r, str):
                    payload['reasoning'] = {'effort': r, 'enabled': True, 'exclude': False}
                elif r:
                    payload['reasoning'] = {'enabled': True, 'exclude': False}

            url = self.api_url

        elif provider == 'ollama':
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream'
            }

            payload = {
                'model': MODELS[model_key]['name'],
                'messages': messages,
                'stream': True,
                'temperature': 0.6
            }

            # Include tools for Ollama; the /v1 endpoint ignores them if unsupported
            if include_tools:
                payload['tools'] = [self.shell_tool_definition]
                payload['tool_choice'] = 'auto'

            url = self.ollama_base_url

        else:
            raise Exception(f"Unknown provider: {provider}")

        self.last_request_payload = payload
        return url, headers, payload

    def _calldebatebot(self, botname, messages, ismoderator=False, modeloverride=None):
        """Stripped-down _call_bot for debate: no tools, returns response text."""
        modelkey = modeloverride or botname
        color = Colors.MAGENTA if ismoderator else Colors.BLUE
        print(f'\n{color}{botname.capitalize()}{Colors.RESET}:')
        self.bot_running = True

        for attempt, delay in enumerate([0] + self.retry_delays):
            if self.interrupt_event.is_set():
                self.bot_running = False
                return ''
            try:
                if delay > 0: time.sleep(delay)
                self.interrupt_event.clear()

                url, headers, payload = self._prepare_request(modelkey, messages, include_tools=False)

                result = self._stream_chat(url, headers, payload)
                
                if result['last_usage']:
                    self._record_and_print_usage(botname, result['last_usage'])
                self.bot_running = False
                return self._strip_said_tags(result['full_response']).strip()

            except Exception as e:
                errmsg = f'API call to {botname.capitalize()} failed (attempt {attempt + 1})'
                print(f'\n{Colors.RED}{errmsg}. Details: {e}{Colors.RESET}')
                print(f'{Colors.GREY}Stack trace:\n{traceback.format_exc()}{Colors.RESET}')
                if attempt < len(self.retry_delays):
                    print(f'{Colors.GREY}Retrying in {self.retry_delays[attempt]}s...{Colors.RESET}')
                else:
                    print(f'{Colors.RED}Giving up after {attempt + 1} attempts.{Colors.RESET}')
                    break

        self.bot_running = False
        return ''

    def _rundebate(self, topic, agents, moderator=None):
        predebatebot = self.last_bot_name
        moderator = moderator or predebatebot
        debatehistory = []
        numagents = len(agents)

        print(f"\n{Colors.BOLD}=== DEBATE ==={Colors.RESET}")
        print(f"Topic: {topic}")
        print(f"  {Colors.MAGENTA}MOD: {moderator.upper()}{Colors.RESET}")
        for name, pos in agents:
            print(f"  {Colors.BLUE}{name.upper()}{Colors.RESET}: {pos}" if pos else f"  {Colors.BLUE}{name.upper()}{Colors.RESET}")
        print(f"{Colors.GREY}Ctrl-C to interrupt and steer. /end-debate to finish.{Colors.RESET}")

        def _callmod(nextbotname):
            modprompt = self._getmodsystemprompt(moderator, topic, agents, nextbotname=nextbotname)
            msgs = self._preparedebatemessages(moderator, topic, None, agents, debatehistory, systempromptoverride=modprompt)
            self.interrupt_event.clear()
            resp = self._calldebatebot(moderator, msgs, ismoderator=True)
            if resp:
                debatehistory.append({'role': 'assistant', 'content': resp, 'bot_id': moderator})

        def _handleinterrupt():
            """Called after ctrl-c. Returns True if debate should end."""
            userinput = self._get_user_input()
            if userinput is None or userinput.lower() == 'exit': return True
            if userinput.strip().lower() == '/end-debate': return True
            if userinput.strip():
                debatehistory.append({'role': 'user', 'content': userinput.strip()})
            return False

        # Flow: mod(→speaker1) → speaker1 → mod(→speaker2) → speaker2 → ...
        done = False
        idx = 0
        turncount = 0
        while not done:
            botname, position = agents[idx]
            override = moderator if botname not in MODELS else None
            # Moderator addresses current speaker
            _callmod(botname)
            if self.interrupt_event.is_set():
                self.interrupt_event.clear()
                turncount = 0
                if _handleinterrupt():
                    done = True; continue
            # Debater speaks
            msgs = self._preparedebatemessages(botname, topic, position, agents, debatehistory)
            self.interrupt_event.clear()
            resp = self._calldebatebot(botname, msgs, modeloverride=override)
            if resp:
                debatehistory.append({'role': 'assistant', 'content': resp, 'bot_id': botname})
            if self.interrupt_event.is_set():
                self.interrupt_event.clear()
                turncount = 0
                if _handleinterrupt():
                    done = True; continue
            turncount += 1
            if turncount >= numagents * 2:
                turncount = 0
                if _handleinterrupt():
                    done = True; continue
            idx = (idx + 1) % numagents

        # Summary phase
        print(f"\n{Colors.BOLD}=== DEBATE SUMMARY ==={Colors.RESET}")
        summaryprompt = (
            f"Summarize this debate on '{topic}'. "
            f"Cover each participant's key arguments, "
            f"points of agreement/disagreement, and your assessment.")
        debatehistory.append({'role': 'user', 'content': summaryprompt})
        modprompt = self._getmodsystemprompt(moderator, topic, agents)
        msgs = self._preparedebatemessages(moderator, topic, None, agents, debatehistory, systempromptoverride=modprompt)
        self.interrupt_event.clear()
        summary = self._calldebatebot(moderator, msgs, ismoderator=True)

        # Append condensed record to main history
        record = f"[Debate on: {topic}]\n"
        for entry in debatehistory:
            if entry['role'] == 'assistant':
                record += f"{entry.get('bot_id', '').upper()}: {entry['content']}\n\n"
            elif entry['role'] == 'user' and entry['content'] != summaryprompt:
                record += f"User: {entry['content']}\n\n"
        if summary: record += f"Summary by {moderator.upper()}: {summary}"
        self.conversation_history.append({'role': 'assistant', 'content': record, 'bot_id': moderator})

    def _call_bot(self, bot_name, ask_mode: bool = False):
        self.last_bot_name = bot_name
        messages = self._prepare_messages(bot_name, ask_mode)

        print(f'\n{Colors.BLUE}{bot_name.capitalize()}{Colors.RESET}:')
        
        # Mark bot as running
        self.bot_running = True

        for attempt, delay in enumerate([0] + self.retry_delays):
            if self.interrupt_event.is_set():
                self.bot_running = False
                break
            try:
                if delay > 0:
                    time.sleep(delay)
                self.interrupt_event.clear()

                url, headers, payload = self._prepare_request(bot_name, messages, include_tools=True)

                result = self._stream_chat(url, headers, payload)

                if self.interrupt_event.is_set():
                    self.last_response_events = result['response_events']
                    print(f"{Colors.YELLOW}...interrupted.{Colors.RESET}")
                    self.bot_running = False
                    break

                if result['last_usage']:
                    self._record_and_print_usage(bot_name, result['last_usage'])

                full_response = result['full_response']
                tool_calls = result['tool_calls']
                reasoning_details_acc = result['reasoning_details_acc']
                response_events = result['response_events']
                first_chunk_content = result['first_chunk_content']

                # --- UNIFIED TOOL HANDLING ---

                # 1. Consolidate all tool calls (formal JSON + inline text) into a standard format
                all_tool_calls = []

                # Keep track of whether we streamed any text content
                text_streamed = not first_chunk_content

                # Process formal tool calls received in the stream
                if tool_calls:
                    formal_tool_calls = [tool_calls[i] for i in sorted(tool_calls.keys())]
                    for tc in formal_tool_calls:
                        if not tc.get('id') or not tc.get('name'):
                            print(f"Warning: Skipping invalid formal tool call with missing ID or name: {tc}")
                            continue
                        try:
                            # The args are already a string, so we just need to parse them
                            parsed_args = json.loads(tc['args'])
                            all_tool_calls.append({
                                'id': tc['id'],
                                'name': tc['name'],
                                'args': parsed_args
                            })
                        except json.JSONDecodeError:
                            print(f"Warning: Could not parse formal tool arguments: {tc['args']}")
                            # Add with empty args to maintain flow
                            all_tool_calls.append({'id': tc['id'], 'name': tc['name'], 'args': {}})

                # Parse and add any inline tool calls from the text content
                if full_response:
                    inline_tool_calls = _parse_inline_tool_calls(full_response)
                    # The parse function already returns the standard format {'id':..., 'name':..., 'args':...}
                    if inline_tool_calls:
                        all_tool_calls.extend(inline_tool_calls)

                # Deduplicate tool calls based on the command string to prevent duplicates
                if all_tool_calls:
                    seen_commands = set()
                    unique_tool_calls = []
                    for tc in all_tool_calls:
                        command = tc.get('args', {}).get('command')
                        if command and command not in seen_commands:
                            unique_tool_calls.append(tc)
                            seen_commands.add(command)
                    all_tool_calls = unique_tool_calls

                # 2. Add the text part of the response to history (if it exists)
                cleaned_content = _remove_inline_tool_calls(full_response).strip()

                # If there's any text content, print it now, but only if it wasn't already streamed.
                if cleaned_content and not text_streamed:
                    print(f"{cleaned_content}", flush=True)

                # Check if the model added a prefix before removing it
                if re.search(r'<\[:~.*? said~:\]>', cleaned_content):
                    self.needs_prefix_reminder = True
                else:
                    # Clear the flag when a clean response is received
                    self.needs_prefix_reminder = False

                # Remove any <[:~* said~:]> labels before storing
                cleaned_content = self._strip_said_tags(cleaned_content).strip()
                if cleaned_content:
                    msg = {'role': 'assistant', 'content': cleaned_content, 'bot_id': bot_name}
                    if reasoning_details_acc:
                        msg['reasoning_details'] = reasoning_details_acc
                    self.conversation_history.append(msg)

                # 3. Add the tool call part to history (if it exists) and then execute
                if all_tool_calls:
                    # Convert to the OpenAI format required for conversation history
                    openai_tool_calls_for_history = []
                    for tc in all_tool_calls:
                        openai_tool_calls_for_history.append({
                            'id': _sanitize_tool_id(tc['id']),
                            'type': 'function',
                            'function': {
                                'name': tc['name'],
                                'arguments': json.dumps(tc['args']) # Changed from 'arguments' to 'arguments'
                            }
                        })
                    tc_msg = {
                        'role': 'assistant',
                        'name': bot_name,
                        'tool_calls': openai_tool_calls_for_history,
                        'bot_id': bot_name
                    }
                    # Always add reasoning_details to tool call messages for Gemini 3 Pro compatibility
                    # (requires thought_signature to be preserved with function calls)
                    if reasoning_details_acc:
                        tc_msg['reasoning_details'] = reasoning_details_acc

                    self.conversation_history.append(tc_msg)

                    # Execute the tool calls
                    self._handle_tool_calls(all_tool_calls, bot_name)
                    self.bot_running = False
                    # No beep after tool calls complete (only on permission prompt or text-only completion)
                    return

                # If we've reached this point, there were no tool calls. The bot is done.
                self.last_response_events = response_events
                self.bot_running = False
                # Do not beep after text-only completions (beep happens on user prompt)
                return

            except Exception as e:
                error_message = f'API call to {bot_name.capitalize()} failed (attempt {attempt + 1})'
                stack_trace = traceback.format_exc()
                print(f'\n{Colors.RED}{error_message}. Details: {e}{Colors.RESET}')
                print(f'{Colors.GREY}Stack trace:\n{stack_trace}{Colors.RESET}')
                if attempt < len(self.retry_delays):
                    print(f'{Colors.GREY}Retrying in {self.retry_delays[attempt]}s...{Colors.RESET}')
                else:
                    print(f'{Colors.RED}Giving up after {attempt + 1} attempts.{Colors.RESET}')
                    break
        
        # Mark bot as no longer running
        self.bot_running = False

    def _list_ollama_models(self):
        """Query local Ollama server and print installed models."""
        try:
            resp = requests.get('http://localhost:11434/api/tags', timeout=5)
            if resp.status_code != 200:
                print(f"{Colors.RED}Ollama server returned status {resp.status_code}{Colors.RESET}")
                return
            data = resp.json()
            models = data.get('models', [])
            if not models:
                print(f"{Colors.GREY}No Ollama models installed.{Colors.RESET}")
                return
            print(f"{Colors.BOLD}Installed Ollama models:{Colors.RESET}")
            for m in models:
                name = m.get('name', 'unknown')
                size_gb = m.get('size', 0) / (1024**3)
                param = m.get('details', {}).get('parameter_size', '?')
                quant = m.get('details', {}).get('quantization_level', '?')
                print(f"  {Colors.GREEN}{name}{Colors.RESET} ({param}, {quant}, {size_gb:.1f}GB)")
        except requests.exceptions.ConnectionError:
            print(f"{Colors.RED}Ollama server not running at localhost:11434{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}Error listing Ollama models: {e}{Colors.RESET}")

    def run(self):
        """Main loop for the interactive chat."""
        openrouter_names = [n for n, m in MODELS.items() if m.get('provider', 'openrouter') == 'openrouter']
        ollama_names = [n for n, m in MODELS.items() if m.get('provider') == 'ollama']
        or_line = ", ".join([f"{Colors.BLUE}{n.capitalize()}{Colors.RESET}" for n in openrouter_names])
        ol_line = ", ".join([f"{Colors.GREEN}{n}{Colors.RESET}" for n in ollama_names])
        print(f"{Colors.BOLD}Welcome!{Colors.RESET}")
        print(f"  OpenRouter: {or_line}")
        print(f"  Ollama:     {ol_line}")
        print("Type 'exit' to quit, or 'BEGIN' to start multi-line input (end with 'END').")
        print(f"{Colors.GREY}Commands: /clear /stats /lastjson /img /imgclear /ollamas /debate [/mod:bot] <query>{Colors.RESET}")

        while True:
            user_text = self._get_user_input()
            if user_text is None or user_text.lower() == 'exit':
                break

            # Direct shell execution path is now determined by the '>' prefix
            if user_text.strip().startswith('>'):
                raw_cmd = user_text.strip()[1:].strip()
                if raw_cmd:
                    # Ensure any prior interrupt is cleared for a fresh command run
                    self.interrupt_event.clear()
                    # Stream output immediately to the console; skip approval for this explicit path
                    def _print_direct(text: str) -> None:
                        print(f"{text}", end='', flush=True)
                    # Handle in-process cd (and optional trailing command) first
                    handled = self._maybe_handle_cd_and_execute(raw_cmd, on_chunk=_print_direct, require_approval=False)
                    if handled is None:
                        output = self._executeshell_command(raw_cmd, on_chunk=_print_direct, require_approval=False, echo_command=False)
                    else:
                        output = handled
                    # Record into conversation history so AI can see direct shell activity
                    try:
                        self.conversation_history.append({'role': 'user', 'content': f'> {raw_cmd}\n{output}'.rstrip()})
                    except Exception:
                        pass
                # After a direct shell command, enable prefill for the next prompt
                self.prefill_shell_mode = True
                continue
            
            # If we are here, it's a message for the AI, so disable prefill
            self.prefill_shell_mode = False

            if user_text.strip().lower() == '/clear':
                os.system('cls' if platform.system() == 'Windows' else 'clear')
                # Clear conversation and all session statistics
                self.conversation_history = []
                self.usage_history = []
                self.session_cost = 0.0
                self.session_prompt_tokens = 0
                self.session_completion_tokens = 0
                self.session_total_tokens = 0
                self.session_reasoning_tokens = 0
                self.session_cached_tokens = 0
                print(f"{Colors.YELLOW}[Screen, context and session stats cleared]{Colors.RESET}")
                continue

            if user_text.strip().lower() == '/stats':
                self._print_stats()
                continue

            if user_text.strip().lower() == '/lastjson':
                self._print_last_json()
                continue

            if user_text.strip().lower() == '/ollamas':
                self._list_ollama_models()
                continue

            # Image attachments: attach one or more images to the *next* prompt.
            # Usage: /img /path/to.png "path with spaces.jpg" https://...  (URLs also supported)
            if user_text.strip().lower().startswith('/img'):
                try:
                    parts = shlex.split(user_text)
                except Exception:
                    parts = user_text.strip().split()
                refs = parts[1:] if len(parts) > 1 else []
                if not refs:
                    print("Usage: /img <path-or-url> [<path-or-url> ...]")
                    continue
                added = 0
                for ref in refs:
                    try:
                        url = _image_ref_to_image_url(ref)
                        self.pending_image_urls.append(url)
                        added += 1
                    except Exception as e:
                        print(f"{Colors.RED}Failed to attach image '{ref}': {e}{Colors.RESET}")
                if added:
                    print(f"{Colors.GREY}Attached {added} image(s) for next prompt.{Colors.RESET}")
                continue

            if user_text.strip().lower() == '/imgclear':
                self.pending_image_urls = []
                print(f"{Colors.GREY}Cleared pending image attachments.{Colors.RESET}")
                continue
                
            # Inline revert: "<original prompt> /revert" -> remove that user prompt and everything after it
            # Handle this BEFORE parsing bots or /ask so we match the original prompt text
            if re.search(r'\s*/revert\s*$', user_text, flags=re.IGNORECASE):
                base_text = re.sub(r'\s*/revert\s*$', '', user_text, flags=re.IGNORECASE).strip()
                if base_text:
                    target_norm = self._normalize_text_for_match(base_text)
                    target_index = None
                    # Walk history from newest to oldest to find the most recent matching user message
                    for idx in range(len(self.conversation_history) - 1, -1, -1):
                        msg = self.conversation_history[idx]
                        if msg.get('role') != 'user':
                            continue
                        content = _content_to_text(msg.get('content')).strip()
                        # Skip shell transcript entries recorded as user lines starting with '> '
                        first_line = content.splitlines()[0] if content else ''
                        if first_line.startswith('> '):
                            continue
                        hist_norm = self._normalize_text_for_match(content)
                        if hist_norm == target_norm:
                            target_index = idx
                            break
                    if target_index is not None:
                        self.conversation_history = self.conversation_history[:target_index]
                        print('=====reverted. re-enter the prompt===')
                    else:
                        print('No matching prompt found; nothing reverted.')
                else:
                    print('Nothing to revert.')
                # Do not add this input to history or call any bot
                continue

            if user_text.strip().lower().startswith('/debate'):
                topic, agents, moderator = self._parsedebate(user_text.strip()[7:])
                if topic and agents:
                    self._rundebate(topic, agents, moderator)
                else:
                    print("Usage: /debate <topic> [/mod:bot] /name1 position1 /name2 position2 [...]")
                continue

            cleaned_text, bots_to_call, ask_mode = self._parse_input(user_text)

            if ask_mode:
                backup_history = self.conversation_history
                self.conversation_history = []

            # Add the user message (optionally multimodal if images are pending)
            did_add_user_message = False
            if cleaned_text or self.pending_image_urls:
                if self.pending_image_urls:
                    prompt_text = (cleaned_text or '').strip() or 'Describe the image(s).'
                    parts = [{'type': 'text', 'text': prompt_text}]
                    for url in self.pending_image_urls:
                        parts.append({'type': 'image_url', 'image_url': {'url': url}})
                    self.conversation_history.append({'role': 'user', 'content': parts})
                    self.pending_image_urls = []
                    did_add_user_message = True
                else:
                    self.conversation_history.append({'role': 'user', 'content': cleaned_text.strip()})
                    did_add_user_message = True

            if not bots_to_call:
                bots_to_call = [self.last_bot_name]

            if did_add_user_message:
                for bot_name in bots_to_call:
                    self.interrupt_event.clear()
                    self._call_bot(bot_name, ask_mode=ask_mode)
                    if self.interrupt_event.is_set():
                        break
            
            if ask_mode:
                self.conversation_history = backup_history
            
            # Clear always approve mode when control returns to user
            self.always_approve = False

        print('\nGoodbye!')

APPLYPATCH = '''### applypatch command instructions
Use the `applypatch` shell command to edit files.
Your patch language is a stripped‑down, file‑oriented diff format designed to be easy to parse and safe to apply. You can think of it as a high‑level envelope:

*** Begin Patch
[ one or more file sections ]
*** End Patch

Within that envelope, you get a sequence of file operations.
You MUST include a header to specify the action you are taking.
Each operation starts with one of three headers:

*** Add File: <path> - create a new file. Every following line is a + line (the initial contents).
*** Delete File: <path> - remove an existing file. Nothing follows.
*** Update File: <path> - patch an existing file in place (optionally with a rename).

May be immediately followed by *** Move to: <new path> if you want to rename the file.
Then one or more "hunks", each introduced by @@ (optionally followed by a hunk header).
Within a hunk each line starts with:

For instructions on [context_before] and [context_after]:
- By default, show 3 lines of code immediately above and 3 lines immediately below each change. If a change is within 3 lines of a previous change, do NOT duplicate the first change's [context_after] lines in the second change's [context_before] lines.
- If 3 lines of context is insufficient to uniquely identify the snippet of code within the file, use the @@ operator to indicate the class or function to which the snippet belongs. For instance, we might have:
@@ class BaseClass
[3 lines of pre-context]
- [old_code]
+ [new_code]
[3 lines of post-context]

- If a code block is repeated so many times in a class or function such that even a single `@@` statement and 3 lines of context cannot uniquely identify the snippet of code, you can use multiple `@@` statements to jump to the right context. For instance:

@@ class BaseClass
@@ 	 def method():
[3 lines of pre-context]
- [old_code]
+ [new_code]
[3 lines of post-context]

The full grammar definition is below:
Patch := Begin { FileOp } End
Begin := "*** Begin Patch" NEWLINE
End := "*** End Patch" NEWLINE
FileOp := AddFile | DeleteFile | UpdateFile
AddFile := "*** Add File: " path NEWLINE { "+" line NEWLINE }
DeleteFile := "*** Delete File: " path NEWLINE
UpdateFile := "*** Update File: " path NEWLINE [ MoveTo ] { Hunk }
MoveTo := "*** Move to: " newPath NEWLINE
Hunk := "@@" [ header ] NEWLINE { HunkLine } [ "*** End of File" NEWLINE ]
HunkLine := (" " | "-" | "+") text NEWLINE

A full patch can combine several operations:

*** Begin Patch
*** Add File: hello.txt
+Hello world
*** Update File: src/app.py
*** Move to: src/main.py
@@ def greet():
-print("Hi")
+print("Hello, world!")
*** Delete File: obsolete.txt
*** End Patch

It is important to remember:

- You must include a header with your intended action (Add/Delete/Update)
- You must prefix new lines with `+` even when creating a new file
- File references can only be relative, NEVER ABSOLUTE.

You can invoke applypatch like:

```bash
applypatch << 'EOF'
***Begin Patch
***Add File: hello.txt
+Hello, world!
*** End Patch
EOF
```
'''

if __name__ == '__main__':
    app = CommandLineAIChat()
    # One-shot CLI mode:
    # - If invoked with args, treat them as a single prompt (shell already handled quoting),
    #   print it as-if the user typed it at the prompt, run the bot(s), then exit.
    # - Otherwise, fall back to the interactive REPL.
    if len(sys.argv) > 1:
        user_text = " ".join(sys.argv[1:]).strip()

        # Mimic the interactive UI: show the user label and the typed input.
        print(f'\n{Colors.GREEN}User:{Colors.RESET}')
        if user_text:
            print(user_text, flush=True)

        # Process exactly like a single REPL turn (except for the '>' direct-shell shortcut).
        cleaned_text, bots_to_call, ask_mode = app._parse_input(user_text)

        if ask_mode:
            backup_history = app.conversation_history
            app.conversation_history = []

        did_add_user_message = False
        if cleaned_text:
            app.conversation_history.append({'role': 'user', 'content': cleaned_text.strip()})
            did_add_user_message = True

        if not bots_to_call:
            bots_to_call = [app.last_bot_name]

        if did_add_user_message:
            for bot_name in bots_to_call:
                app.interrupt_event.clear()
                app._call_bot(bot_name, ask_mode=ask_mode)
                if app.interrupt_event.is_set():
                    break

        if ask_mode:
            app.conversation_history = backup_history

        raise SystemExit(0)

    app.run()
