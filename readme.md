# ConsAI

ConsAI is a terminal chat and coding assistant that connects to multiple AI
models through OpenRouter. Models share a conversation, so you can switch
between them, ask several for their views, or run a moderated debate.

In normal chat, models can run local shell commands, edit files, search the
web, and fetch web pages. You can also attach images, run commands yourself,
ask questions outside the main conversation, and inspect usage and costs.

## Setup and launch

You need Python 3.9 or newer, a terminal on macOS, Linux, or Windows with WSL,
and an OpenRouter API key. The program imports Unix terminal modules such as
`termios` and `pty`, so run it inside WSL rather than native Windows Python.
API calls require an internet connection and available OpenRouter credits.

From the directory containing `consai.py`, install the dependencies:

```sh
python3 -m pip install -r requirements.txt
```

The dependencies are `prompt_toolkit`, `python-dotenv`, and `requests`.
Commands the assistant runs also need their own programs installed, such as
Git for repository work.

Create a key in [OpenRouter's API key settings](https://openrouter.ai/settings/keys).

Prefer adding the key to your shell's rc (startup) file: `~/.zshrc` for zsh
or `~/.bashrc` for Bash. Add this line to the file:

```sh
export OPENROUTER_API_KEY='your-key-here'
```

Open a new terminal or reload the file with `source ~/.zshrc` for zsh or
`source ~/.bashrc` for Bash. The key will then be available when you launch
ConsAI from that shell.

Otherwise, create a `.env` file beside `consai.py` containing:

```dotenv
OPENROUTER_API_KEY=your-key-here
```

If neither option is configured, ConsAI prompts for the key at startup.
The input is hidden and the key stays in memory for that session; ConsAI
does not save it. An empty answer exits. Ctrl-C or Ctrl-D cancels the prompt.

The existing shell variable takes precedence over `.env`. Surrounding
whitespace is stripped from the key. `.env` is ignored by this repository's
Git configuration. See the [OpenRouter quickstart](https://openrouter.ai/docs/quickstart)
for API background.

Start the program:

```sh
python3 consai.py
```

To work in another project, launch the script by its path from that
project's directory. Shell commands and relative file paths use ConsAI's
current working directory, not the script's directory.

## Chat and model selection

Type a prompt and press Enter. The initial model is `sonnet`.

```text
Explain what this project does.
/pareto Review the previous answer and identify anything it missed.
Which change should we make first?
```

The following names and OpenRouter model IDs are configured in `consai.py`:

| Command | Configured model ID |
| --- | --- |
| `/sonnet` | `~anthropic/claude-sonnet-latest` |
| `/opus` | `~anthropic/claude-opus-latest` |
| `/sol` | `~openai/gpt-sol-latest` |
| `/astra` | `~openai/gpt-astra-latest` |
| `/pareto` | `unbiased/pareto-26.10-preview` |
| `/glmflash` | `~z-ai/glm-flash-latest` |
| `/glm` | `~z-ai/glm-latest` |
| `/dsflash` | `~deepseek/deepseek-flash-latest` |
| `/dspro` | `~deepseek/deepseek-pro-latest` |
| `/kimi` | `~moonshotai/kimi-latest` |
| `/mimoflash` | `xiaomi/mimo-v2.6-flash` |
| `/mimopro` | `xiaomi/mimo-v2.6-pro` |
| `/qwen` | `qwen/qwen3.8-2.4t-a95b` |
| `/qwen27b` | `qwen/qwen3.8-27b` |
| `/geminiflash` | `~google/gemini-flash-latest` |
| `/geminipro` | `~google/gemini-pro-latest` |

This table describes the local configuration. Availability, image support,
and tool support depend on the selected model and its OpenRouter route.

Use `/model-name` anywhere in a prompt to address a model. A prompt without
a model name goes to the last model called. Normal model commands are
lowercase. Switching models keeps the conversation, including earlier
model replies and tool results.

You can address several models in one prompt:

```text
Compare the two approaches discussed above. /sonnet /astra
```

They answer one at a time in the order you type their names. Later models
see earlier replies. Repeating a model's name does not give it an extra
turn; its first appearance determines its place in the order.

### Multiline input

Enter `BEGIN` on its own line, enter or paste your text, then enter `END` on
its own line to submit it. Both markers are uppercase.

```text
BEGIN
/sonnet Review this function:
def double(value): return value * 2
Explain its inputs and output.
END
```

The terminal supports input editing and persistent input history through
`prompt_toolkit`. Responses stream as they arrive; reasoning text is shown
in grey when the provider supplies it.

### Ask outside the current conversation

```text
/ask /pareto Explain the difference between latency and throughput.
```

`/ask` temporarily starts an empty conversation for this prompt and restores
the main conversation afterward. Its question and answers are not added to
the main context. Multiple selected models still share this temporary
conversation. Usage still counts toward the session totals, and the last
model called becomes the default for the next prompt.

`/ask` runs without tools: the model cannot run shell commands, edit files,
search the web, or fetch pages. It uses a short question-answering system
prompt instead of the normal project instructions.

## Run a prompt from the command line

Pass a quoted prompt after the script name to run it and exit:

```sh
python3 consai.py 'Explain what a reverse proxy does.'
python3 consai.py '/opus Review consai.py for error handling problems.'
python3 consai.py '/sonnet /astra Compare queues and publish-subscribe systems.'
python3 consai.py '/ask /pareto Explain eventual consistency.'
```

All arguments are joined into one prompt. Model selection and `/ask` work
here, and tool calls can still request approval. Use an interactive terminal
when approval may be needed.

Other interactive commands, including `!`, `/img`, `/debate`, `/stats`, and
`/clear`, are not dispatched in this mode. There is no command-line option
parser: `--help` is treated as prompt text, not a help flag. Standard input
is not loaded as the prompt.

## Shell commands, file edits, and web tools

Ask for a task in plain language:

```text
/sonnet Read the source files and explain the program's entry point.
/opus Fix the error in the function we just discussed, then run its tests.
/geminipro Search the web for the official documentation for this library.
```

The model chooses which tools to use and can continue working after their
results arrive:

- **Shell:** run local commands and return their output to the conversation.
  Commands classified as likely read-only run automatically; other commands
  request approval. AI commands set `GIT_PAGER=cat` so Git output does not
  wait for pager input.
- **Edit:** replace exact text in an existing UTF-8 file. ConsAI shows a
  coloured diff before approval. The match must be unique unless the model
  requests replacement of all occurrences. The edit is rejected if the file
  changes while approval is pending. New files are created through the shell.
- **Web search and fetch:** ask OpenRouter's server tools to search or read
  pages using Exa. Fetches request at most 20,000 content tokens. Normal chat
  prints a Sources list when the API returns URL citations.

The shell approval check is a command allowlist heuristic, not an operating
system sandbox. Shell commands run with your account's permissions.

### Approval controls

At `Yes / No / Always`, press a single key:

| Key | Effect |
| --- | --- |
| `y` or Enter | Approve this command or edit. |
| `n` or Escape | Decline and interrupt the current model turn. |
| `a` | Approve this and subsequent approval requests until the current normal chat turn finishes. |

Other keys also decline. `Always` covers both shell commands and edits; it
resets when the normal chat turn returns control to you.

### Run a command yourself

Prefix a command with `!`:

```text
! pwd
! git status --short
! python3 -m pytest
```

Direct commands run immediately without an approval prompt. Their command
and output are added to the conversation so the models can use the results.
They inherit your normal environment, including your Git pager settings.

After a direct command, the next input is prefilled with `!`. Delete that
prefix to return to chat.

Leading `cd` commands change ConsAI's own working directory, so the change
persists for later commands and model requests:

```text
! cd ~/src/myproject
! cd -
! cd
! cd ~/src/myproject && pwd
```

`cd -` returns to the previous directory; bare `cd` goes home. The built-in
handler supports a trailing command after `&&` or `;`. Use these simple
forms: it is not a complete shell parser. Other commands run in child
shells, so an `export` in one command does not configure later commands.

With a terminal attached, shell commands use a pseudo-terminal and forward
keystrokes to interactive programs. The non-interactive path uses the
system `script` utility and a 60-second command timeout.

## Images

Queue one or more images, then send your question to a model that supports
image input:

```text
/img screenshot.png "design draft.jpg"
/sonnet What differences do you see between these images?
```

HTTP, HTTPS, and `data:` image URLs are also accepted:

```text
/img https://example.com/diagram.png
/geminipro Explain this diagram.
```

Local paths may be relative to the working directory and may contain `~` or
environment variables. Quote paths containing spaces. Local images must
have a recognised image MIME type and be no larger than 15 MiB each. They
are encoded as base64 and sent with the prompt.

Repeated `/img` commands add to the pending queue. The next normal chat or
`/ask` prompt consumes that queue; an empty prompt with pending images asks
the model to describe them. Images in a normal conversation remain in its
context after the queue is consumed. Debates do not consume pending images.

Use `/imgclear` to discard queued images without sending them. Images
already sent remain in the conversation. `/clear` removes both queued
images and the conversation context, and resets session usage counters.

## Moderated debates

Start a debate with a topic, at least two participants, and optional
positions and moderator:

```text
/debate Should this service use a queue? /mod:opus /sonnet Argue for a queue /astra Argue for direct calls
```

Put the topic before the first `/name` or `/mod:name`. Each participant's
position runs until the next slash command. Omit a position to leave it
unspecified. Without `/mod:name`, the last normal chat model moderates
(`sonnet` initially). Choose a configured model for the moderator.

Participants take turns in the order written. Before each turn, the
moderator asks that participant a focused question. After two full rounds,
ConsAI pauses for input. Press Enter to continue, type guidance to steer the
debate, or enter `/end-debate` to finish. Ctrl-C during a response also opens
a steering prompt.

You can use custom participant names as personas; names not found in
`MODELS` use the moderator's model:

```text
/debate How should we deploy? /mod:opus /builder Prioritise delivery speed /reviewer Prioritise reliability
```

Debates start with their own history and run without shell, edit, or web
tools. They do not inherit the main chat context or normal `AGENTS.md`
instructions. When finished, the moderator gives a summary, and the debate
record and summary are added to the main conversation. Debate calls count
toward session usage. `/end-debate` is recognised at debate input prompts,
not as a normal chat command.

## Context, usage, and debugging

| Interactive command | Effect |
| --- | --- |
| `/stats` | Show session cost and token totals, plus recorded usage for each request. |
| `/lastjson` | Print the latest cached request payload and write cached response events to `/tmp/response.txt`. |
| `/imgclear` | Discard pending image attachments. |
| `/clear` | Clear the terminal, conversation context, pending images, and session usage counters. |
| `<original prompt> /revert` | Remove the most recent matching user prompt and all later messages from the conversation. |
| `exit` or Ctrl-D at the input prompt | Exit ConsAI. |

For example, to remove a previous question and everything after it:

```text
/sonnet Explain the authentication flow.
Explain the authentication flow. /revert
```

Matching ignores model tags, letter case, and extra whitespace. Direct shell
transcript entries are excluded from matching. After reverting, re-enter
the prompt you want to send. `/revert` alone has no target and does nothing.
It does not undo file edits, commands, or API charges, and does not reset
usage totals.

The program displays request and running session cost plus input/output
tokens when usage is returned by the API. `/stats` also includes reasoning
tokens, cached tokens, timestamps, model IDs, and upstream inference cost
when supplied. These figures depend on the API's usage reports; clearing
them does not affect billing.

`/lastjson` makes no API call. It overwrites `/tmp/response.txt` when cached
events exist. It prints the request body, not the authentication headers;
the body may contain prompts, file content, tool results, or encoded images.
Debate calls update the cached request but do not update the response-event
cache, so after a debate those two views can refer to different requests.

Conversation context lives in memory and is not restored when the program
restarts. Typed interactive input is stored separately in
`~/.consai_history` for recall, including `/ask` input. `/clear` and `/revert`
do not erase that file. `/clear` also leaves the selected model, working
directory, and last API debug data unchanged.

## Project instructions and settings

Normal chat reads `../AGENTS.md` and `./AGENTS.md`, relative to the current
working directory, whenever it prepares a model request. Both files are
included when present, parent first, with their absolute paths. This is a
two-file lookup, not a search through every ancestor directory.

Use those files for project conventions and instructions. Changing the
files or using `! cd` changes what subsequent normal requests see.
`/ask` requests and debates use their own system prompts instead.

Model and API settings are defined in `consai.py`:

- `MODELS` sets bot names, model IDs, and optional reasoning settings.
  Currently, all entries except `pareto` request medium reasoning effort.
- `_prepare_request` sets temperature to `0.6` and defines provider routing.
  Requests set `provider.zdr = true`, specify a provider order, request
  latency sorting, and disable fallback outside that provider list.
- `WEBTOOLS` configures web search and fetch.
- `retry_delays` currently permits one retry after 1.5 seconds for a failed
  model call. HTTP requests use a 60-second connection/read timeout.

There are no interactive commands for changing temperature, reasoning
effort, or provider routing. Edit the configuration and restart to change
them. ZDR routing restricts eligible endpoints and can leave a model with
no route; see [OpenRouter's provider routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection).
It does not remove ConsAI's local input history or debug files.

## Interrupts and troubleshooting

- **Stop a model:** press Ctrl-C while it is responding. In a debate, this
  opens the steering prompt. During an interactive shell command, keystrokes
  are forwarded to the child program. Use `exit` or Ctrl-D at the normal
  prompt to quit; Ctrl-C at an input prompt can also exit.
- **Missing Python module:** run
  `python3 -m pip install -r requirements.txt` with the same interpreter used
  to launch ConsAI.
- **`termios` import error on Windows:** run the program with Python inside
  WSL.
- **API error:** read the status and error body printed in the terminal.
  Check the key, account credits, model ID, and allowed provider routes.
  Use `/lastjson` to inspect the request. The configured model table is not
  an availability check.
- **Image rejected:** check the local path, image type, and 15 MiB limit,
  then use a model with image support.
- **Edit rejected:** the old text must match exactly. Ask the model to read
  the file again if there is no match, more than one match, or the file
  changed during approval.
- **No notification sound:** the program uses macOS `afplay`, or
  `powershell.exe` for a Windows beep when available in WSL. Without either,
  it runs silently. It beeps at approval prompts and when returning to user
  input after the first prompt.

This README describes the current `consai.py`. `changelog.txt` also contains
historical features and files that are not part of the current program.
