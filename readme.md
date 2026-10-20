# ConsAI

ConsAI is a terminal system admin and devops assistant that connects to multiple
AI models through OpenRouter. Models share a conversation, so you can switch
between them or ask several for their views.

In normal chat, models can run local shell commands, read, create, edit and
delete files, search the web, and fetch web pages. You can also attach images,
run commands yourself, ask questions outside the main conversation, and
inspect usage and costs.

## Setup and launch

You need Python 3.9 or newer, a terminal on macOS, Linux, or Windows with WSL,
and an OpenRouter API key. The program imports Unix terminal modules such as
`termios` and `pty`, so run it inside WSL rather than native Windows Python.
API calls require an internet connection and available OpenRouter credits.

ConsAI has no external Python dependencies. Input editing and history use
Python's built-in `readline`; HTTP requests and streaming use the built-in
`urllib.request`.
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

The built-in loader reads `.env` only from the folder containing `consai.py`,
regardless of the working directory. It does not search parent folders.
It loads only `OPENROUTER_API_KEY` and ignores every other setting, so other
keys in the file do not reach the commands ConsAI runs.
It accepts one `KEY=value` setting per line, trims surrounding spaces, and
removes matching single or double quotes around values. Blank lines and
lines starting with `#` are ignored. It does not support `export` prefixes,
inline comments, variable expansion, escape decoding, or multiline values.
A missing `.env` file is ignored.

If neither option is configured, ConsAI prompts for the key at startup.
The input is hidden and the key stays in memory for that session; ConsAI
does not save it. An empty answer exits. Ctrl-C or Ctrl-D cancels the prompt.

The existing shell variable takes precedence over `.env`. 
`.env` is ignored by this repository's Git configuration. See the [OpenRouter quickstart](https://openrouter.ai/docs/quickstart) for API background.

Start the program:

```sh
python3 consai.py
```

To work in another project, launch the script by its path from that
project's directory. Shell commands and relative file paths use ConsAI's
current working directory, not the script's directory.

## Chat and model selection

Type a prompt and press Enter. The initial model is `sonnet`. Tab completes
model names, commands, and file paths. On a blank line, or when nothing
matches, Tab inserts a tab character.

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
| `/haiku` | `~anthropic/claude-haiku-latest` |
| `/luna` | `~openai/gpt-luna-latest` |
| `/terra` | `~openai/gpt-terra-latest` |
| `/sol` | `~openai/gpt-sol-latest` |
| `/astra` | `~openai/gpt-astra-latest` |
| `/pareto` | `unbiased/pareto-26.10-preview` |
| `/grok` | `~x-ai/grok-latest` |
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
Python's built-in `readline`. Responses stream as they arrive; reasoning text
is shown in grey when the provider supplies it.

### Ask outside the current conversation

```text
/ask /pareto Explain the difference between latency and throughput.
```

`/ask` temporarily starts an empty conversation for this prompt and restores
the main conversation afterward. Its question and answers are not added to
the main context. Multiple selected models still share this temporary
conversation. Usage still counts toward the session totals, and the last
model called becomes the default for the next prompt.

`/ask` runs without tools: the model cannot run shell commands, read, create,
edit or delete files, search the web, or fetch pages. It uses a short
question-answering system prompt instead of the normal project instructions.

## Run a prompt from the command line

Pass a quoted prompt after the script name to run it and exit:

```sh
python3 consai.py 'Explain what a reverse proxy does.'
python3 consai.py '/opus Review consai.py for error handling problems.'
python3 consai.py '/sonnet /astra Compare queues and publish-subscribe systems.'
python3 consai.py '/ask /pareto Explain eventual consistency.'
python3 consai.py '/always /opus Run the tests and fix any failures.'
```

All arguments are joined into one prompt. Model selection, `/ask` and
`/always` work here, and tool calls can still request approval. Use an
interactive terminal when approval may be needed, or add `/always` to approve
every tool call in advance.

Other interactive commands, including `!`, `/img`, `/stats`, and
`/clear`, are not dispatched in this mode. There is no command-line option
parser: `--help` is treated as prompt text, not a help flag. Standard input
is not loaded as the prompt.

## Shell commands, file tools, and web tools

Ask for a task in plain language:

```text
/sonnet Read the source files and explain the program's entry point.
/opus Fix the error in the function we just discussed, then run its tests.
/geminipro Search the web for the official documentation for this library.
```

The model chooses which tools to use and can continue working after their
results arrive:

- **Shell:** run local commands and return their output to the conversation.
  Commands print in yellow as the model writes them. When the response
  finishes, ConsAI classifies every shell command in it. If all are likely
  read-only, no shell approval is needed. Otherwise one prompt under the
  commands, covers all of them. A command that names a `.env` file is never
  classified as read-only. AI commands set `GIT_PAGER=cat` and
  `MANPAGER=cat` so Git and man output does not wait for pager input.
- **Read:** return a file's lines with 1-based line numbers and a tab. Files
  longer than 2000 lines need an explicit `start_line` and `end_line`; a
  requested range is always returned in full. Reading needs no approval.
- **Edit:** replace exact text in an existing UTF-8 file. ConsAI shows a
  coloured diff before approval. The match must be unique unless the model
  requests replacement of all occurrences. The edit is rejected if the file
  changes while approval is pending.
- **Create:** write a new UTF-8 file. It fails if the path already exists, so
  existing files must be changed with Edit. ConsAI shows the full content as a
  diff before approval.
- **Delete:** remove a file after showing its content as a diff. The path is
  resolved without following symlinks, so a link is deleted, not its target.
- **Web search and fetch:** ask OpenRouter's server tools to search or read
  pages using Exa. Fetches request at most 20,000 content tokens. Normal chat
  prints a Sources list when the API returns URL citations.

The shell approval check is a command allowlist heuristic, not an operating
system sandbox. Shell commands run with your account's permissions.

### Approval controls

A response can contain several tool calls. Its shell commands share one
prompt, such as `Run 3 commands?`, asked once after the response finishes.
The count includes read-only commands in the same response, since all of
them run. Each Edit, Create and Delete still shows its diff and asks on its
own when its turn comes. At `Yes / No / Always`, press a single key:

| Key | Effect |
| --- | --- |
| `y` or Enter | Approve: run every shell command in the response, or apply this edit, create or delete. |
| `n` or Escape | Decline: cancel every tool call still pending in the response and return control to you. |
| `a` | Approve this and every later prompt, for commands and file changes, until the normal chat turn returns control to you. |

Other keys also decline. Cancelled tool calls are recorded as cancelled in
the conversation, so the model sees that they did not run.

To approve a whole turn before any prompt appears, add `/always` anywhere in
your prompt:

```text
/always /opus Fix the failing tests and run them until they pass.
```

`/always` has the same effect as pressing `a` at the first prompt: every
shell command and every Edit, Create and Delete runs without asking until the
turn returns control to you. It must be a separate word; letter case does not
matter. It is removed from the prompt before the model sees it. Use it only
for tasks you would approve anyway, since the model can then run any command
your account can.

Approvals are not silent. Edit, Create and Delete still show their diffs, and
each approval prints a grey `... auto-approved` line. For shell commands, that
line is followed by the commands that needed approval. The same lines appear
after you press `a`. Ctrl-C still stops the model.

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

Each command runs in its own child shell, so `cd` and `export` affect only
that command. `! cd ~/src/myproject && pwd` prints the project path, but
the next command starts again in ConsAI's working directory. Use `/cd <path>`
to change ConsAI's working directory for subsequent commands. Use `/cd`
without a path to return to your home directory.

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
context after the queue is consumed.

Use `/imgclear` to discard queued images without sending them. Images
already sent remain in the conversation. `/clear` removes both queued
images and the conversation context, and resets session usage counters.

## Context, usage, and debugging

| Interactive command | Effect |
| --- | --- |
| `/cd <path>` | Change the working directory for shell commands, edits, AGENTS.md lookup, and the models. No path means home. The directory shows after the `User:` label. |
| `/stats` | Show session cost and token totals, plus recorded usage for each request. |
| `/lastjson` | Print the latest cached request payload and write cached response events to `/tmp/response.txt`. |
| `/imgclear` | Discard pending image attachments. |
| `/clear` | Clear the terminal, conversation context, pending images, and session usage counters. |
| `/revert` or `<original prompt> /revert` | Remove the newest user prompt, or the most recent one matching the text, and all later messages from the conversation. |
| `exit` or Ctrl-D at the input prompt | Exit ConsAI. |

For example, to remove a previous question and everything after it:

```text
/sonnet Explain the authentication flow.
Explain the authentication flow. /revert
```

Matching ignores model tags, letter case, and extra whitespace. Direct shell
transcript entries are excluded from matching. After reverting, re-enter
the prompt you want to send. `/revert` alone removes the newest prompt.
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

Conversation context lives in memory and is not restored when the program
restarts. Typed interactive input is stored separately in
`~/.consai_history` for recall, including `/ask` input. A trailing `/revert`
is not saved, so ↑ recalls the prompt itself. `/clear` and `/revert`
do not erase that file. `/clear` also leaves the selected model, working
directory, and last API debug data unchanged.

## Project instructions and settings

Normal chat reads `../AGENTS.md` and `./AGENTS.md`, relative to the current
working directory, whenever it prepares a model request. Both files are
included when present, parent first, with their absolute paths. This is a
two-file lookup, not a search through every ancestor directory.

Use those files for project conventions and instructions. Changing the
files changes what subsequent normal requests see.
`/ask` requests use their own system prompt instead.

Model and API settings are defined in `consai.py`:

- `MODELS` sets bot names, model IDs, and optional reasoning settings.
  Currently, all entries except `pareto` request medium reasoning effort.
- `_prepare_request` sets temperature to `0.6` and defines provider routing.
  Requests set `provider.zdr = true`, specify a provider order, request
  latency sorting, and enable provider fallbacks.
- `WEBTOOLS` configures web search and fetch.
- `retry_delays` currently permits one retry after 1.5 seconds for a failed
  model call. HTTP requests use a 60-second connection/read timeout.

There are no interactive commands for changing temperature, reasoning
effort, or provider routing. Edit the configuration and restart to change
them. ZDR routing restricts eligible endpoints and can leave a model with
no route; see [OpenRouter's provider routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection).
It does not remove ConsAI's local input history or debug files.

## Interrupts and troubleshooting

- **Stop a model:** press Ctrl-C while it is responding. During an
  interactive shell command, keystrokes are forwarded to the child program.
  Use `exit` or Ctrl-D at the normal prompt to quit; Ctrl-C at an input
  prompt can also exit.
- **Missing `readline` module:** use a Python built with GNU readline, such
  as the system `python3` on Ubuntu or Debian.
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
- **Create rejected:** the path already exists. Use Edit for existing files,
  or choose a new path.
- **Read rejected:** the file has more than 2000 lines and no line range was
  given. Ask for a `start_line` and `end_line`.
- **No notification sound:** the program uses macOS `afplay`, or
  `powershell.exe` for a Windows beep when available in WSL. Without either,
  it runs silently. It beeps at approval prompts and when returning to user
  input after the first prompt.

This README describes the current `consai.py`. `changelog.txt` also contains
historical features and files that are not part of the current program.
