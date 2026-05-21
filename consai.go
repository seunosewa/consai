package main

// Create a go.mod file:
// go mod init consai
// go get github.com/creack/pty golang.org/x/term github.com/chzyer/readline github.com/joho/godotenv

import (
	"bufio"
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"os/user"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"syscall"
	"time"

	"github.com/chzyer/readline"
	"github.com/creack/pty"
	"github.com/google/shlex"
	"github.com/joho/godotenv"
	"golang.org/x/term"
)

// --- Constants & Configuration ---

var Models = map[string]map[string]interface{}{
	"opus46":     {"name": "anthropic/claude-opus-4.6", "reasoning": "medium"},
	"opus45":     {"name": "anthropic/claude-opus-4.5", "reasoning": "medium"},
	"sonnet45":   {"name": "anthropic/claude-sonnet-4.5", "reasoning": 32768},
	"sonnet46":   {"name": "anthropic/claude-sonnet-4.6", "reasoning": 32768},
	"haiku":      {"name": "anthropic/claude-haiku-4.5", "reasoning": 32768},
	"gpt52":      {"name": "openai/gpt-5.2", "reasoning": "medium"},
	"gpt5mini":   {"name": "openai/gpt-5-mini", "reasoning": "high"},
	"gpt52codex": {"name": "openai/gpt-5.2-codex", "reasoning": "medium"},
	"25pro":      {"name": "google/gemini-2.5-pro", "reasoning": 16384},
	"25flash":    {"name": "google/gemini-2.5-flash-preview-09-2025", "reasoning": 24576},
	"3pro":       {"name": "google/gemini-3-pro-preview", "reasoning": "medium"},
	"3flash":     {"name": "google/gemini-3-flash-preview", "reasoning": "high"},
	"glm5":       {"name": "z-ai/glm-5", "reasoning": 32768},
	"k25":        {"name": "moonshotai/kimi-k2.5", "reasoning": "high"},
	"m25":        {"name": "minimax/minimax-m2.5", "reasoning": "high"},
}

const (
	ColorGreen   = "\033[92m"
	ColorBlue    = "\033[94m"
	ColorYellow  = "\033[93m"
	ColorRed     = "\033[91m"
	ColorCyan    = "\033[96m"
	ColorMagenta = "\033[95m"
	ColorGrey    = "\033[90m"
	ColorReset   = "\033[0m"
	ColorBold    = "\033[1m"
)

var (
	textRO  = []string{"cat", "cut", "diff", "echo", "fmt", "grep", "head", "nl", "paste", "printf", "rev", "rg", "sort", "tail", "tr", "uniq", "wc", "sed", "awk", "jq"}
	fsRO    = []string{"cd", "basename", "cmp", "comm", "df", "dirname", "du", "file", "ls", "pwd", "realpath", "stat", "tree", "find"}
	sysRO   = []string{"cal", "date", "dmesg", "history", "hostname", "id", "lsof", "man", "ps", "uname", "uptime", "who", "whoami"}
	netRO   = []string{"dig", "host", "netstat", "ping", "traceroute", "curl"}
	miscRO  = []string{"clear", "false", "less", "more", "seq", "sleep", "test", "true", "whereis", "which", "yes", "ffprobe"}
	macOSRO = []string{"jq"}
)

var stopTokens = func() []string {
	p := "|"
	return []string{
		"<" + p + "im_start" + p + ">",
		"<" + p + "im_end" + p + ">",
		"<" + p + "endoftext" + p + ">",
		"<" + p + "repo_name" + p + ">",
	}
}()

func getROList() []string {
	var ro []string
	ro = append(ro, textRO...)
	ro = append(ro, fsRO...)
	ro = append(ro, sysRO...)
	ro = append(ro, netRO...)
	ro = append(ro, miscRO...)
	ro = append(ro, macOSRO...)
	return ro
}

var applyPatch = `### applypatch command instructions
Use the ` + "`" + `applypatch` + "`" + ` shell command to edit files.
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

- If a code block is repeated so many times in a class or function such that even a single ` + "`" + `@@` + "`" + ` statement and 3 lines of context cannot uniquely identify the snippet of code, you can use multiple ` + "`" + `@@` + "`" + ` statements to jump to the right context. For instance:

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
- You must prefix new lines with ` + "`" + `+` + "`" + ` even when creating a new file
- File references can only be relative, NEVER ABSOLUTE.

You can invoke applypatch like:

` + "```bash" + `
applypatch << 'EOF'
***Begin Patch
***Add File: hello.txt
+Hello, world!
*** End Patch
EOF
` + "```" + `
`

// --- Structs ---

type Message struct {
	Role             string           `json:"role"`
	Content          interface{}      `json:"content"` // string or []map[string]interface{}
	Name             string           `json:"name,omitempty"`
	ToolCalls        []ToolCall       `json:"tool_calls,omitempty"`
	ToolCallID       string           `json:"tool_call_id,omitempty"`
	BotID            string           `json:"bot_id,omitempty"`
	ApplyPatchFailed bool             `json:"applypatch_failed,omitempty"`
	ReasoningDetails []map[string]any `json:"reasoning_details,omitempty"`
}

type ToolCall struct {
	ID       string           `json:"id"`
	Type     string           `json:"type"`
	Function ToolCallFunction `json:"function"`
	Index    int              `json:"index,omitempty"`
}

type ToolCallFunction struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

type AppState struct {
	History             []Message
	LastBotName         string
	RetryDelays         []float64
	BotRunning          bool
	AlwaysApprove       bool
	UsageHistory        []map[string]interface{}
	SessionCost         float64
	SessionTokens       map[string]int
	PreviousCwd         string
	PrefillShellMode    bool
	PendingImageURLs    []string
	LastRequestPayload  interface{}
	LastResponseEvents  []interface{}
	NeedsPrefixReminder    bool
	HasShownUserLabelOnce  bool
	OpenRouterAPIKey       string
	APIURL                 string
	Interrupt              chan struct{}
	Rl                     *readline.Instance
}

// --- Global App Instance ---
var app *AppState

// --- Helper Functions ---

func playCompletionBeep() {
	if _, err := exec.LookPath("afplay"); err != nil { return }
	cmd := exec.Command("afplay", "/System/Library/Sounds/Glass.aiff")
	cmd.Stdout = nil
	cmd.Stderr = nil
	_ = cmd.Start() // Run asynchronously, don't wait
}

func getSingleKey() (string, error) {
	fd := int(os.Stdin.Fd())
	oldState, err := term.MakeRaw(fd)
	if err != nil { return "", err }
	defer term.Restore(fd, oldState)

	var buf [1]byte
	n, err := os.Stdin.Read(buf[:])
	if err != nil || n == 0 { return "", err }

	ch := buf[0]
	if ch == 27 { return "escape", nil }
	if ch == 13 || ch == 10 { return "enter", nil }
	return strings.ToLower(string(ch)), nil
}

func sanitizeToolID(id string) string {
	if regexp.MustCompile(`^[a-zA-Z0-9_-]+$`).MatchString(id) {
		return id
	}
	s := regexp.MustCompile(`[^a-zA-Z0-9_-]`).ReplaceAllString(id, "_")
	s = regexp.MustCompile(`__+`).ReplaceAllString(s, "_")
	s = strings.Trim(s, "_")
	if s == "" {
		return "toolcall"
	}
	return s
}

func contentToText(content interface{}) string {
	if content == nil {
		return ""
	}
	if s, ok := content.(string); ok {
		return s
	}
	if list, ok := content.([]interface{}); ok {
		var texts []string
		for _, part := range list {
			if m, ok := part.(map[string]interface{}); ok {
				if m["type"] == "text" {
					if txt, ok := m["text"].(string); ok {
						texts = append(texts, txt)
					}
				}
			}
		}
		return strings.Join(texts, "\n")
	}
	return fmt.Sprintf("%v", content)
}

func isURLLike(s string) bool {
	s = strings.ToLower(strings.TrimSpace(s))
	return strings.HasPrefix(s, "http://") || strings.HasPrefix(s, "https://") || strings.HasPrefix(s, "data:")
}

func imageRefToURL(ref string) (string, error) {
	ref = strings.TrimSpace(ref)
	if ref == "" {
		return "", fmt.Errorf("empty image ref")
	}
	if isURLLike(ref) {
		return ref, nil
	}
	pathStr := os.ExpandEnv(ref)
	if strings.HasPrefix(pathStr, "~") {
		usr, _ := user.Current()
		pathStr = filepath.Join(usr.HomeDir, pathStr[1:])
	}
	absPath, err := filepath.Abs(pathStr)
	if err != nil {
		return "", err
	}
	info, err := os.Stat(absPath)
	if err != nil {
		return "", fmt.Errorf("not a file: %s", absPath)
	}
	if info.Size() > 15*1024*1024 {
		return "", fmt.Errorf("file too large: %s", absPath)
	}
	fileBytes, err := os.ReadFile(absPath)
	if err != nil {
		return "", err
	}
	mimeType := mime.TypeByExtension(filepath.Ext(absPath))
	if mimeType == "" {
		mimeType = http.DetectContentType(fileBytes)
	}
	if !strings.HasPrefix(mimeType, "image/") {
		return "", fmt.Errorf("not an image file: %s", absPath)
	}
	b64 := base64.StdEncoding.EncodeToString(fileBytes)
	return fmt.Sprintf("data:%s;base64,%s", mimeType, b64), nil
}

func stripSaidTags(text string) string {
	re := regexp.MustCompile(`<\[:~.*? said~:\]>`)
	return re.ReplaceAllString(text, "")
}

func removeInlineToolCalls(content string) string {
	// First: if trailing fenced code block preceded by ':', remove just the block
	reMD := regexp.MustCompile("(?s)(:\\s*)```(?:bash|shell|sh)\\s*\\n(?:.*?)\\n```\\s*$")
	trimmed := strings.TrimRight(content, " \t\n")
	cleaned := reMD.ReplaceAllString(trimmed, "$1")
	if cleaned != trimmed {
		return cleaned
	}
	// Else: remove wrapper blocks and executeshell(...) syntax
	reWrapper := regexp.MustCompile(`(?s)<｜tool[\s▁]calls[\s▁]begin｜>.*?<｜tool[\s▁]calls[\s▁]end｜>`)
	reOld := regexp.MustCompile(`(?s)executeshell\s*\(\s*\{.*?\}\s*\)`)
	result := reWrapper.ReplaceAllString(content, "")
	result = reOld.ReplaceAllString(result, "")
	return result
}

// --- Shell Checks ---

func tokenizeShellCommand(cmd string) []string {
	tokens, err := shlex.Split(cmd)
	if err != nil {
		// Fallback to simple word splitting if shlex fails
		scanner := bufio.NewScanner(strings.NewReader(cmd))
		scanner.Split(bufio.ScanWords)
		var fallback []string
		for scanner.Scan() { fallback = append(fallback, scanner.Text()) }
		return fallback
	}
	// Merge && and || back together (shlex splits them)
	var merged []string
	for i := 0; i < len(tokens); i++ {
		tok := tokens[i]
		if i+1 < len(tokens) && tokens[i+1] == tok && (tok == "&" || tok == "|") {
			merged = append(merged, tok+tok)
			i++
		} else { merged = append(merged, tok) }
	}
	return merged
}

func commandIsReadOnly(cmd string) bool {
	cmd = strings.TrimSpace(cmd)
	if cmd == "" { return true }

	tokens := tokenizeShellCommand(cmd)
	if len(tokens) == 0 { return true }

	// Reject redirection/heredoc operators anywhere in command
	unsafeOps := map[string]bool{">": true, ">>": true, "<<": true, "<<<": true, ">&": true, "<&": true, "2>": true, "2>>": true}
	for _, tok := range tokens {
		if unsafeOps[tok] { return false }
	}

	// Split by pipeline/chain operators into segments
	var segments [][]string
	current := []string{}
	for _, tok := range tokens {
		if tok == "|" || tok == "&&" || tok == "||" || tok == ";" {
			if len(current) > 0 { segments = append(segments, current) }
			current = []string{}
		} else { current = append(current, tok) }
	}
	if len(current) > 0 { segments = append(segments, current) }

	roSet := make(map[string]bool)
	for _, r := range getROList() { roSet[r] = true }
	gitSafe := map[string]bool{"status": true, "diff": true, "ls-files": true, "ls-tree": true, "log": true, "show": true, "blame": true, "cat-file": true, "ls-remote": true}
	curlUnsafe := map[string]bool{"-X": true, "-d": true, "--data": true, "-F": true, "--form": true, "-T": true, "--upload-file": true, "-o": true, "--output": true}

	for _, seg := range segments {
		if len(seg) == 0 { continue }
		base := seg[0]

		if base == "git" {
			if len(seg) > 1 && !gitSafe[seg[1]] { return false }
			continue
		}
		if base == "curl" {
			for _, tok := range seg {
				if curlUnsafe[tok] { return false }
			}
			continue
		}
		if base == "awk" || base == "sed" {
			for _, tok := range seg {
				if tok == "-i" || tok == "--in-place" { return false }
			}
			if !roSet[base] { return false }
			continue
		}
		if base == "find" {
			for i, tok := range seg {
				if tok == "-delete" { return false }
				if tok == "-exec" && i+1 < len(seg) {
					execCmd := seg[i+1]
					if !roSet[execCmd] { return false }
				}
			}
			if !roSet[base] { return false }
			continue
		}
		if !roSet[base] { return false }
	}
	return true
}

// --- App Class Implementation in Go ---

func newApp() *AppState {
	_ = godotenv.Load()
	key := os.Getenv("OPENROUTER_API_KEY")
	if key == "" {
		fmt.Printf("%sError: OPENROUTER_API_KEY environment variable not set.%s\n", ColorRed, ColorReset)
		os.Exit(1)
	}

	home := os.Getenv("HOME")
	rl, err := readline.NewEx(&readline.Config{
		Prompt:          "",
		HistoryFile:     filepath.Join(home, ".consai_history"),
		InterruptPrompt: "^C",
		EOFPrompt:       "exit",
	})
	if err != nil {
		panic(err)
	}
	return &AppState{
		LastBotName: "sonnet46",
		RetryDelays: []float64{1.5},
		BotRunning:  false,
		SessionTokens: map[string]int{
			"prompt": 0, "completion": 0, "total": 0, "reasoning": 0, "cached": 0,
		},
		PreviousCwd:      os.Getenv("PWD"),
		OpenRouterAPIKey: key,
		APIURL:           "https://openrouter.ai/api/v1/chat/completions",
		Interrupt:        make(chan struct{}),
		Rl:               rl,
	}
}

func main() {
	app = newApp()

	// One-shot CLI mode
	if len(os.Args) > 1 {
		userText := strings.Join(os.Args[1:], " ")
		fmt.Printf("\n%sUser:%s\n%s\n", ColorGreen, ColorReset, userText)

		cleanedText, botsToCall, askMode := app.parseInput(userText)

		if askMode {
			app.History = []Message{}
		}

		// Simple content handling for CLI mode (no images)
		app.History = append(app.History, Message{Role: "user", Content: cleanedText})

		if len(botsToCall) == 0 {
			botsToCall = []string{app.LastBotName}
		}

		for _, bot := range botsToCall {
			app.callBot(bot)
		}
		return
	}

	app.run()
}

func (a *AppState) getSystemPrompt(botName string, askMode bool) string {
	assistantName := strings.ToUpper(botName)
	if askMode {
		return fmt.Sprintf("You are %s, a helpful AI assistant. Use your executeshell tool if needed.", assistantName)
	}

	// Sort keys for deterministic output
	var keys []string
	for k := range Models {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	var otherBots []string
	for _, k := range keys {
		if k != botName {
			otherBots = append(otherBots, strings.ToUpper(k))
		}
	}
	otherBotsInfo := strings.Join(otherBots, ", ")

	welcome := fmt.Sprintf(`You are %s, a helpful AI assistant.
You are in a chatroom with User and OTHER helpful AI assistants: %s.`, assistantName, otherBotsInfo)

	tempDir := "/tmp"
	if os.Getenv("TEMP") != "" {
		tempDir = os.Getenv("TEMP")
	}

	agentRules := ""
	paths := []string{os.ExpandEnv("$HOME/src/AGENTS.md"), "./AGENTS.md"}
	for _, p := range paths {
		if content, err := os.ReadFile(p); err == nil {
			agentRules += fmt.Sprintf("\n\nFollow these rules from %s:\n%s", p, string(content))
		}
	}

	googleKey := os.Getenv("GOOGLE_SEARCH_API_KEY")
	googleCSE := os.Getenv("GOOGLE_CSE_ID")
	googleLine := ""
	if googleKey != "" && googleCSE != "" {
		googleLine = fmt.Sprintf("\nUse google to search the web:\n`curl \"https://www.googleapis.com/customsearch/v1?key=%s&cx=%s&q=YOUR_QUERY\" | jq '[.items[] | {title, link, snippet}]'`\n", googleKey, googleCSE)
	}

	toolInstructions := fmt.Sprintf(`Your executeshell tool is powerful. Use it when needed.
Try your best to run shell commands in non-interactive mode e.g. echo "command to run" | script
Think creatively about how to chain simple shell commands to solve any problem. Long command chains are BEST.
Break complex tasks down into multiple tool calls if needed.
%s
All backup files or temporary scripts should go into %s.
Open and read files before mentioning them. Never guess what they contain. Always read them.
Directory: %s | Date: %s | OS: %s
%s
`, googleLine, tempDir, func() string { d, _ := os.Getwd(); return d }(), time.Now().Format("2006-01-02"), "darwin", applyPatch)

	if botName == "gpt5c" {
		toolInstructions = "You do not have any tools. Ask user for help instead.\n"
	}

	conclusion := `
        if you see the <[:~MODELNAME said~:]> prefix in an assistant message, it means that the model MODELNAME said it.
        if you see <[:~@MODELNAME:]> in a user message, it means the user addressed the message to the model MODELNAME.
        Never add <[:~MODELNAME said~:]> or <[:~@MODELNAME:]> to your responses.
        `

	return welcome + "\n\n" + toolInstructions + "\n\n" + agentRules + "\n\n" + conclusion
}

func (a *AppState) prepareMessages(botName string, askMode bool) []Message {
	sysMsg := Message{Role: "system", Content: a.getSystemPrompt(botName, askMode)}

	formattedHistory := []Message{}
	for _, msg := range a.History {
		formattedMsg := msg
		if msg.Role == "assistant" && msg.BotID != "" {
			txt := contentToText(msg.Content)
			label := fmt.Sprintf("<[:~%s said~:]>", strings.ToUpper(msg.BotID))
			newContent := ""
			if txt != "" {
				newContent = label + "\n" + txt
			}
			formattedMsg.Content = newContent
			// Sanitize tool calls
			newTCs := []ToolCall{}
			for _, tc := range msg.ToolCalls {
				tc.ID = sanitizeToolID(tc.ID)
				newTCs = append(newTCs, tc)
			}
			formattedMsg.ToolCalls = newTCs
		}
		// Reasoning filtering
		if botName == "3pro" || botName == "3flash" {
			// keep reasoning
		} else {
			formattedMsg.ReasoningDetails = nil
		}
		formattedHistory = append(formattedHistory, formattedMsg)
	}

	// Apply patch failed reminder check
	reminders := []string{}
	if len(a.History) > 0 {
		last := a.History[len(a.History)-1]
		if last.Role == "tool" && last.ApplyPatchFailed {
			reminders = append(reminders, "Your applypatch failed. read patcherrors.txt for help, and craft a perfect patch this time.")
		}
	}
	if a.NeedsPrefixReminder {
		reminders = append(reminders, fmt.Sprintf("Never add prefixes like <[:~%s said~:]> to your answers)", strings.ToUpper(botName)))
	}
	if len(reminders) > 0 {
		formattedHistory = append(formattedHistory, Message{Role: "system", Content: strings.Join(reminders, "\n")})
	}

	return append([]Message{sysMsg}, formattedHistory...)
}

// --- Execute Shell ---

func (a *AppState) executeShellCommand(cmd string, onChunk func(string), requireApproval bool, echo bool) string {
	if echo {
		fmt.Printf("\n%s%s%s\n", ColorYellow, cmd, ColorReset)
	}

	if requireApproval && !commandIsReadOnly(cmd) && !a.AlwaysApprove {
		playCompletionBeep()
		fmt.Printf("%sRun this command? (Yes / No / Always) %s", ColorRed, ColorReset)
		key, err := getSingleKey()
		if err != nil { key = "n" }
		if key == "y" || key == "enter" {
			fmt.Println("Yes")
		} else if key == "a" {
			fmt.Println("Always")
			a.AlwaysApprove = true
		} else {
			fmt.Println("No")
			return "Command execution cancelled by user."
		}
	}

	isInteractive := term.IsTerminal(int(os.Stdin.Fd()))
	var outputBuf bytes.Buffer

	if !isInteractive {
		// Non-TTY fallback: wrap with script for PTY-like behavior, enforce timeout
		preface := "[stdin is not a TTY; using pseudo-tty wrapper]\n"
		outputBuf.WriteString(preface)
		if onChunk != nil { onChunk(preface) }

		// Wrap command with script to force a pseudo-tty
		wrappedCmd := fmt.Sprintf("script -q /dev/null -c %s", fmt.Sprintf("'%s'", strings.ReplaceAll(cmd, "'", "'\\''")))
		c := exec.Command("sh", "-c", wrappedCmd)
		c.Stdout = &outputBuf
		c.Stderr = &outputBuf

		done := make(chan error, 1)
		go func() { done <- c.Run() }()

		select {
		case <-done:
		case <-time.After(60 * time.Second):
			_ = c.Process.Kill()
			outputBuf.WriteString("\nCommand timed out after 60 seconds.\n")
		}
		return outputBuf.String()
	}

	// Interactive PTY Execution
	c := exec.Command("sh", "-c", cmd)
	ptmx, err := pty.Start(c)
	if err != nil { return fmt.Sprintf("Error starting pty: %v", err) }
	defer func() { _ = ptmx.Close() }()

	// Resize pty
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, syscall.SIGWINCH)
	go func() {
		for range ch {
			if err := pty.InheritSize(os.Stdin, ptmx); err != nil { /* ignore */ }
		}
	}()
	ch <- syscall.SIGWINCH
	defer func() { signal.Stop(ch); close(ch) }()

	// Set stdin to raw mode
	oldState, err := term.MakeRaw(int(os.Stdin.Fd()))
	if err == nil { defer func() { _ = term.Restore(int(os.Stdin.Fd()), oldState) }() }

	errChan := make(chan error, 1)

	// Copy stdin to pty (only in interactive mode)
	go func() { _, _ = io.Copy(ptmx, os.Stdin) }()

	// Copy pty to stdout and buffer
	go func() {
		buf := make([]byte, 1024)
		for {
			n, err := ptmx.Read(buf)
			if n > 0 {
				chunk := buf[:n]
				outputBuf.Write(chunk)
				os.Stdout.Write(chunk)
			}
			if err != nil {
				errChan <- err
				return
			}
		}
	}()

	done := make(chan error)
	go func() { done <- c.Wait() }()
	<-done // Wait indefinitely for interactive commands

	return outputBuf.String()
}

func (a *AppState) maybeHandleCD(cmd string, onChunk func(string), requiredApproval bool) (string, bool) {
	tokens := tokenizeShellCommand(cmd)
	if len(tokens) == 0 || tokens[0] != "cd" { return "", false }

	// Parse: cd [target] [; or &&] [rest...]
	target := ""
	var sep string
	var restTokens []string
	j := 1
	if j < len(tokens) && tokens[j] != ";" && tokens[j] != "&&" && tokens[j] != "||" {
		target = tokens[j]
		j++
	}
	if j < len(tokens) && (tokens[j] == ";" || tokens[j] == "&&") {
		sep = tokens[j]
		j++
		restTokens = tokens[j:]
	}

	// Resolve target
	if target == "" {
		target = os.ExpandEnv("$HOME")
	} else if target == "-" {
		target = a.PreviousCwd
		if target == "" { target = os.ExpandEnv("$HOME") }
	} else { target = os.ExpandEnv(target) }

	oldCwd, _ := os.Getwd()
	err := os.Chdir(target)
	var msg string
	if err != nil {
		msg = fmt.Sprintf("cd: %s: %v\n", target, err)
	} else {
		a.PreviousCwd = oldCwd
		newCwd, _ := os.Getwd()
		msg = fmt.Sprintf("cwd: %s\n", newCwd)
	}
	if onChunk != nil { onChunk(msg) }

	// Execute trailing command if separator rules allow
	if len(restTokens) > 0 && (sep == ";" || (sep == "&&" && err == nil)) {
		// Reconstruct rest command with proper quoting
		var quoted []string
		for _, t := range restTokens {
			if t == ";" || t == "&&" || t == "||" || t == "|" {
				quoted = append(quoted, t)
			} else if strings.ContainsAny(t, " \t\n'\"\\") {
				quoted = append(quoted, fmt.Sprintf("'%s'", strings.ReplaceAll(t, "'", "'\\''")))
			} else { quoted = append(quoted, t) }
		}
		restCmd := strings.Join(quoted, " ")
		out := a.executeShellCommand(restCmd, onChunk, requiredApproval, false)
		return msg + out, true
	}
	return msg, true
}

// --- Chat Loop ---

func normalizeTextForMatch(text string) string {
	// Remove <[:~@BOT:]> tags
	text = regexp.MustCompile(`(?i)<\[:~@.*?:\]>`).ReplaceAllString(text, " ")
	// Remove /botname tokens
	var botNames []string
	for k := range Models {
		botNames = append(botNames, regexp.QuoteMeta(k))
	}
	text = regexp.MustCompile(`(?i)/(`+strings.Join(botNames, "|")+`)\b`).ReplaceAllString(text, " ")
	// Collapse whitespace, lowercase
	text = regexp.MustCompile(`\s+`).ReplaceAllString(strings.TrimSpace(text), " ")
	return strings.ToLower(text)
}

func (a *AppState) parseInput(text string) (string, []string, bool) {
	askMode := strings.Contains(text, "/ask")
	text = strings.ReplaceAll(text, "/ask", "")
	text = strings.TrimSpace(text)

	var botCommands []string
	for k := range Models {
		// match /botname followed by boundary
		re := regexp.MustCompile(fmt.Sprintf(`(?i)/%s\b`, regexp.QuoteMeta(k)))
		if re.MatchString(text) {
			botCommands = append(botCommands, k)
		}
	}

	for _, bot := range botCommands {
		re := regexp.MustCompile(fmt.Sprintf(`(?i)/%s`, regexp.QuoteMeta(bot)))
		text = re.ReplaceAllString(text, fmt.Sprintf("<[:~@%s:]>", strings.ToUpper(bot)))
	}

	return strings.TrimSpace(text), botCommands, askMode
}

func (a *AppState) run() {
	fmt.Printf("%sWelcome!%s\n", ColorBold, ColorReset)

	for {
		// Print the label manually so readline doesn't reprint it on every keystroke
		if a.PrefillShellMode {
			fmt.Printf("\n%sUser:%s\n", ColorGreen, ColorReset)
			a.Rl.SetPrompt("> ")
		} else {
			fmt.Printf("\n%sUser:%s\n", ColorGreen, ColorReset)
			a.Rl.SetPrompt("")
		}
		// Beep on user turn except the very first time
		if a.HasShownUserLabelOnce {
			playCompletionBeep()
		} else { a.HasShownUserLabelOnce = true }
		line, err := a.Rl.Readline()
		if err != nil {
			if err == readline.ErrInterrupt {
				// Ctrl-C while user typing: show help and continue
				fmt.Printf("\n%sType 'exit' or ctrl-d to quit%s\n", ColorGrey, ColorReset)
				continue
			}
			break // EOF or other error: exit
		}

		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}

		if line == "exit" {
			break
		}

		// Multi-line input: BEGIN ... END
		if line == "BEGIN" {
			fmt.Printf("%s[Multi-line mode - type END to finish]%s\n", ColorGrey, ColorReset)
			a.Rl.SetPrompt("")
			var mlLines []string
			for {
				ml, mlerr := a.Rl.Readline()
				if mlerr != nil {
					break
				}
				if strings.TrimSpace(ml) == "END" {
					break
				}
				mlLines = append(mlLines, ml)
			}
			line = strings.Join(mlLines, "\n")
			if line == "" {
				continue
			}
		}

		if strings.HasPrefix(line, ">") {
			cmd := strings.TrimSpace(line[1:])
			res, handled := a.maybeHandleCD(cmd, func(s string) { fmt.Print(s) }, false)
			if !handled {
				res = a.executeShellCommand(cmd, func(s string) { fmt.Print(s) }, false, false)
			}
			a.History = append(a.History, Message{Role: "user", Content: fmt.Sprintf("> %s\n%s", cmd, res)})
			a.PrefillShellMode = true
			continue
		}

		a.PrefillShellMode = false

		// Slash commands
		if line == "/clear" {
			a.History = []Message{}
			a.UsageHistory = nil
			a.SessionCost = 0
			a.SessionTokens = map[string]int{"prompt": 0, "completion": 0, "total": 0, "reasoning": 0, "cached": 0}
			fmt.Print("\033[H\033[2J") // Clear screen
			fmt.Printf("%s[Screen, context and session stats cleared]%s\n", ColorYellow, ColorReset)
			continue
		}

		if line == "/stats" {
			a.printStats()
			continue
		}

		if line == "/lastjson" {
			a.printLastJSON()
			continue
		}

		// /revert: "<original prompt> /revert" rewinds history to before that prompt
		if regexp.MustCompile(`(?i)\s*/revert\s*$`).MatchString(line) {
			baseText := regexp.MustCompile(`(?i)\s*/revert\s*$`).ReplaceAllString(line, "")
			baseText = strings.TrimSpace(baseText)
			if baseText == "" {
				fmt.Println("Nothing to revert.")
			} else {
				targetNorm := normalizeTextForMatch(baseText)
				targetIdx := -1
				for idx := len(a.History) - 1; idx >= 0; idx-- {
					msg := a.History[idx]
					if msg.Role != "user" {
						continue
					}
					content := contentToText(msg.Content)
					lines := strings.SplitN(content, "\n", 2)
					if len(lines) > 0 && strings.HasPrefix(lines[0], "> ") {
						continue
					}
					if normalizeTextForMatch(content) == targetNorm {
						targetIdx = idx
						break
					}
				}
				if targetIdx >= 0 {
					a.History = a.History[:targetIdx]
					fmt.Println("=====reverted. re-enter the prompt===")
				} else {
					fmt.Println("No matching prompt found; nothing reverted.")
				}
			}
			continue
		}

		// Handle Images
		if line == "/imgclear" {
			a.PendingImageURLs = []string{}
			fmt.Println("Pending images cleared.")
			continue
		}

		if strings.HasPrefix(line, "/img") {
			parts, err := shlex.Split(line)
			if err != nil { parts = strings.Fields(line) } // Fallback
			refs := parts[1:] // Skip "/img"
			if len(refs) == 0 {
				fmt.Println("Usage: /img <path-or-url> [<path-or-url> ...]")
				continue
			}
			added := 0
			for _, p := range refs {
				if url, err := imageRefToURL(p); err == nil {
					a.PendingImageURLs = append(a.PendingImageURLs, url)
					added++
				} else {
					fmt.Printf("%sFailed to attach image '%s': %v%s\n", ColorRed, p, err, ColorReset)
				}
			}
			if added > 0 {
				fmt.Printf("%sAttached %d image(s) for next prompt.%s\n", ColorGrey, added, ColorReset)
			}
			continue
		}

		if strings.HasPrefix(line, "/debate") {
			args := strings.TrimSpace(line[7:])
			topic, agents, moderator := parseDebate(args)
			if topic != "" && len(agents) >= 2 {
				a.runDebate(topic, agents, moderator)
			} else {
				fmt.Println("Usage: /debate <topic> [/mod:bot] /name1 position1 /name2 position2 [...]")
			}
			continue
		}

		cleanedText, botsToCall, askMode := a.parseInput(line)
		backupHistory := a.History

		if askMode {
			a.History = []Message{} // Temporary clear for ask mode
		}

		// Prepare user message
		var content interface{} = cleanedText
		if len(a.PendingImageURLs) > 0 {
			parts := []map[string]interface{}{
				{"type": "text", "text": cleanedText},
			}
			for _, u := range a.PendingImageURLs {
				parts = append(parts, map[string]interface{}{
					"type":      "image_url",
					"image_url": map[string]string{"url": u},
				})
			}
			content = parts
			a.PendingImageURLs = []string{}
		}

		a.History = append(a.History, Message{Role: "user", Content: content})

		if len(botsToCall) == 0 {
			botsToCall = []string{a.LastBotName}
		}

		for _, bot := range botsToCall {
			a.callBot(bot)
		}

		if askMode {
			a.History = backupHistory
		}
	}
}

// --- Debate ---

type debateAgent struct {
	Name     string
	Position string
}

func parseDebate(text string) (string, []debateAgent, string) {
	// Sort model names by length descending so longer names match first
	var names []string
	for k := range Models {
		names = append(names, regexp.QuoteMeta(k))
	}
	sort.Slice(names, func(i, j int) bool { return len(names[i]) > len(names[j]) })
	pat := regexp.MustCompile(`(?i)/(mod:)?(` + strings.Join(names, "|") + `|\w+)\b`)
	matches := pat.FindAllStringSubmatchIndex(text, -1)
	if len(matches) == 0 {
		return "", nil, ""
	}
	topic := strings.TrimSpace(text[:matches[0][0]])
	if topic == "" {
		return "", nil, ""
	}
	var agents []debateAgent
	moderator := ""
	for i, m := range matches {
		end := len(text)
		if i+1 < len(matches) {
			end = matches[i+1][0]
		}
		pos := strings.TrimSpace(text[m[1]:end])
		isMod := text[m[2]:m[3]] != ""
		name := strings.ToLower(text[m[4]:m[5]])
		if isMod {
			moderator = name
		} else {
			agents = append(agents, debateAgent{name, pos})
		}
	}
	if len(agents) < 2 {
		return "", nil, ""
	}
	return topic, agents, moderator
}

func getDebateSystemPrompt(botname, topic, position string, all []debateAgent) string {
	var others []string
	for _, a := range all {
		if a.Name != botname {
			others = append(others, strings.ToUpper(a.Name)+" (arguing: "+a.Position+")")
		}
	}
	pos := position
	if pos == "" {
		pos = "(unspecified)"
	}
	return fmt.Sprintf("You are %s in a structured debate.\nTopic: %s\nYour position: %s\nOther participants: %s\n\nArgue persuasively for your position. Respond to previous arguments. Be concise (2-4 paragraphs).\nNever add <[:~%s said~:]> to your responses.",
		strings.ToUpper(botname), topic, pos, strings.Join(others, ", "), strings.ToUpper(botname))
}

func getModSystemPrompt(modname, topic string, all []debateAgent, nextbot string) string {
	var parts []string
	for _, a := range all {
		if a.Position != "" {
			parts = append(parts, strings.ToUpper(a.Name)+" (arguing: "+a.Position+")")
		} else {
			parts = append(parts, strings.ToUpper(a.Name))
		}
	}
	addrline := ""
	if nextbot != "" {
		addrline = fmt.Sprintf("Address %s directly. Ask them 1 pointed question — the single most important question that cuts to the heart of the matter.\n", strings.ToUpper(nextbot))
	}
	return fmt.Sprintf("You are %s moderating a structured debate.\nTopic: %s\nParticipants: %s\n\nYour role:\n- Identify the most important unaddressed points and weaknesses.\n- Steer toward the strongest, most substantive lines of argument.\n- Stay neutral. Do not argue for any position.\n- Be concise.\n%sNever add <[:~%s said~:]> to your responses.",
		strings.ToUpper(modname), topic, strings.Join(parts, ", "), addrline, strings.ToUpper(modname))
}

func prepareDebateMessages(botname, topic, position string, all []debateAgent, history []Message, sysOverride string) []Message {
	sys := sysOverride
	if sys == "" {
		sys = getDebateSystemPrompt(botname, topic, position, all)
	}
	msgs := []Message{{Role: "system", Content: sys}}
	for _, msg := range history {
		if msg.Role == "assistant" && msg.BotID != "" {
			label := fmt.Sprintf("<[:~%s said~:]>", strings.ToUpper(msg.BotID))
			content := contentToText(msg.Content)
			role := "user"
			if msg.BotID == botname {
				role = "assistant"
			}
			msgs = append(msgs, Message{Role: role, Content: label + "\n" + content})
		} else {
			msgs = append(msgs, msg)
		}
	}
	return msgs
}

func (a *AppState) callDebateBot(botname string, messages []Message, isModerator bool) string {
	color := ColorBlue
	if isModerator {
		color = ColorMagenta
	}
	fmt.Printf("\n%s%s%s:\n", color, strings.Title(botname), ColorReset)

	modelInfo, ok := Models[botname]
	if !ok {
		// fallback: use last bot's model
		modelInfo = Models[a.LastBotName]
	}

	reqBody := map[string]interface{}{
		"model":       modelInfo["name"],
		"messages":    messages,
		"stream":      true,
		"temperature": 0.6,
	}
	jsonData, _ := json.Marshal(reqBody)
	req, _ := http.NewRequest("POST", a.APIURL, bytes.NewBuffer(jsonData))
	req.Header.Set("Authorization", "Bearer "+a.OpenRouterAPIKey)
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 60 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		fmt.Printf("Error: %v\n", err)
		return ""
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		fmt.Printf("%sAPI error %d: %s%s\n", ColorRed, resp.StatusCode, string(body), ColorReset)
		return ""
	}

	reader := bufio.NewReader(resp.Body)
	full := ""
	for {
		rawline, err := reader.ReadString('\n')
		if err != nil {
			break
		}
		rawline = strings.TrimSpace(rawline)
		if !strings.HasPrefix(rawline, "data: ") {
			continue
		}
		data := rawline[6:]
		if data == "[DONE]" {
			break
		}
		var event struct {
			Choices []struct {
				Delta struct {
					Content string `json:"content"`
				} `json:"delta"`
			} `json:"choices"`
		}
		if json.Unmarshal([]byte(data), &event) == nil && len(event.Choices) > 0 {
			c := event.Choices[0].Delta.Content
			if c != "" {
				fmt.Print(c)
				full += c
			}
		}
	}
	fmt.Println()
	return stripSaidTags(strings.TrimSpace(full))
}

func (a *AppState) runDebate(topic string, agents []debateAgent, moderator string) {
	if moderator == "" {
		moderator = a.LastBotName
	}
	var history []Message

	fmt.Printf("\n%s=== DEBATE ===%s\n", ColorBold, ColorReset)
	fmt.Printf("Topic: %s\n", topic)
	fmt.Printf("  %sMOD: %s%s\n", ColorMagenta, strings.ToUpper(moderator), ColorReset)
	for _, ag := range agents {
		if ag.Position != "" {
			fmt.Printf("  %s%s%s: %s\n", ColorBlue, strings.ToUpper(ag.Name), ColorReset, ag.Position)
		} else {
			fmt.Printf("  %s%s%s\n", ColorBlue, strings.ToUpper(ag.Name), ColorReset)
		}
	}
	fmt.Printf("%sCtrl-C to interrupt. /end-debate to finish.%s\n", ColorGrey, ColorReset)

	callMod := func(nextbot string) {
		modprompt := getModSystemPrompt(moderator, topic, agents, nextbot)
		msgs := prepareDebateMessages(moderator, topic, "", agents, history, modprompt)
		resp := a.callDebateBot(moderator, msgs, true)
		if resp != "" {
			history = append(history, Message{Role: "assistant", Content: resp, BotID: moderator})
		}
	}

	idx := 0
	turncount := 0
	for {
		ag := agents[idx]
		callMod(ag.Name)
		msgs := prepareDebateMessages(ag.Name, topic, ag.Position, agents, history, "")
		resp := a.callDebateBot(ag.Name, msgs, false)
		if resp != "" {
			history = append(history, Message{Role: "assistant", Content: resp, BotID: ag.Name})
		}
		turncount++
		if turncount >= len(agents)*2 {
			turncount = 0
			fmt.Printf("\n%s[Continue debate? /end-debate to finish, or press Enter]%s\n", ColorGrey, ColorReset)
			a.Rl.SetPrompt("")
			userinput, _ := a.Rl.Readline()
			userinput = strings.TrimSpace(userinput)
			if strings.ToLower(userinput) == "/end-debate" || userinput == "exit" {
				break
			}
			if userinput != "" {
				history = append(history, Message{Role: "user", Content: userinput})
			}
		}
		idx = (idx + 1) % len(agents)
	}

	// Summary
	fmt.Printf("\n%s=== DEBATE SUMMARY ===%s\n", ColorBold, ColorReset)
	summaryprompt := fmt.Sprintf("Summarize this debate on '%s'. Cover each participant's key arguments, points of agreement/disagreement, and your assessment.", topic)
	history = append(history, Message{Role: "user", Content: summaryprompt})
	modprompt := getModSystemPrompt(moderator, topic, agents, "")
	msgs := prepareDebateMessages(moderator, topic, "", agents, history, modprompt)
	summary := a.callDebateBot(moderator, msgs, true)

	// Append condensed record to main history
	record := fmt.Sprintf("[Debate on: %s]\n", topic)
	for _, entry := range history {
		if entry.Role == "assistant" {
			record += strings.ToUpper(entry.BotID) + ": " + contentToText(entry.Content) + "\n\n"
		} else if entry.Role == "user" && contentToText(entry.Content) != summaryprompt {
			record += "User: " + contentToText(entry.Content) + "\n\n"
		}
	}
	if summary != "" {
		record += fmt.Sprintf("Summary by %s: %s", strings.ToUpper(moderator), summary)
	}
	a.History = append(a.History, Message{Role: "assistant", Content: record, BotID: moderator})
}

func (a *AppState) recordUsage(botName string, u interface{}) {
	type usageShape struct {
		Cost                    float64 `json:"cost"`
		PromptTokens            int     `json:"prompt_tokens"`
		CompletionTokens        int     `json:"completion_tokens"`
		TotalTokens             int     `json:"total_tokens"`
		CompletionTokensDetails *struct {
			ReasoningTokens int `json:"reasoning_tokens"`
		} `json:"completion_tokens_details"`
		PromptTokensDetails *struct {
			CachedTokens int `json:"cached_tokens"`
		} `json:"prompt_tokens_details"`
	}
	// u may be the inline struct pointer or a map; marshal+unmarshal to normalise
	b, _ := json.Marshal(u)
	var us usageShape
	if json.Unmarshal(b, &us) != nil {
		return
	}
	if us.PromptTokens == 0 && us.CompletionTokens == 0 && us.Cost == 0 {
		return
	}

	reasoning := 0
	if us.CompletionTokensDetails != nil {
		reasoning = us.CompletionTokensDetails.ReasoningTokens
	}
	cached := 0
	if us.PromptTokensDetails != nil {
		cached = us.PromptTokensDetails.CachedTokens
	}

	a.SessionCost += us.Cost
	a.SessionTokens["prompt"] += us.PromptTokens
	a.SessionTokens["completion"] += us.CompletionTokens
	a.SessionTokens["total"] += us.TotalTokens
	a.SessionTokens["reasoning"] += reasoning
	a.SessionTokens["cached"] += cached

	a.UsageHistory = append(a.UsageHistory, map[string]interface{}{
		"timestamp":  time.Now().Unix(),
		"bot":        botName,
		"model":      Models[botName]["name"],
		"cost":       us.Cost,
		"prompt":     us.PromptTokens,
		"completion": us.CompletionTokens,
		"total":      us.TotalTokens,
		"reasoning":  reasoning,
		"cached":     cached,
	})
	fmt.Printf("\n%sRequest: $%.4f (%d up, %d down) | Session: $%.4f (%d up, %d down)%s\n",
		ColorCyan, us.Cost, us.PromptTokens, us.CompletionTokens,
		a.SessionCost, a.SessionTokens["prompt"], a.SessionTokens["completion"], ColorReset)
}

func (a *AppState) printStats() {
	fmt.Printf("%sSession usage%s\n", ColorBold, ColorReset)
	fmt.Printf("Total cost: %.6f credits\n", a.SessionCost)
	fmt.Printf("Total tokens: %d (prompt %d, completion %d, reasoning %d, cached %d)\n",
		a.SessionTokens["total"], a.SessionTokens["prompt"], a.SessionTokens["completion"],
		a.SessionTokens["reasoning"], a.SessionTokens["cached"])
	for i, rec := range a.UsageHistory {
		t := time.Unix(int64(rec["timestamp"].(int64)), 0).Format("2006-01-02 15:04:05")
		fmt.Printf("[%d] %s | %v -> %v | cost %.6f credits\n", i+1, t, rec["bot"], rec["model"], rec["cost"])
		fmt.Printf("    tokens total %v, prompt %v (cached %v), completion %v (reasoning %v)\n",
			rec["total"], rec["prompt"], rec["cached"], rec["completion"], rec["reasoning"])
	}
}

func (a *AppState) printLastJSON() {
	fmt.Printf("\n%s--- LAST API CALL ---%s\n", ColorBold, ColorReset)
	if a.LastRequestPayload != nil {
		fmt.Printf("%s%s--- REQUEST ---%s\n", ColorCyan, ColorBold, ColorReset)
		b, err := json.MarshalIndent(a.LastRequestPayload, "", "  ")
		if err != nil {
			fmt.Printf("%sError: %v%s\n", ColorRed, err, ColorReset)
		} else {
			fmt.Printf("%s%s%s\n", ColorCyan, string(b), ColorReset)
		}
	} else {
		fmt.Printf("%sNo request has been made in this session yet.%s\n", ColorGrey, ColorReset)
	}
	if len(a.LastResponseEvents) > 0 {
		path := "/tmp/response.txt"
		fmt.Printf("\n%s%s--- RESPONSE ---%s\n", ColorMagenta, ColorBold, ColorReset)
		b, _ := json.MarshalIndent(a.LastResponseEvents, "", "  ")
		if err := os.WriteFile(path, b, 0644); err != nil {
			fmt.Printf("%sError writing response: %v%s\n", ColorRed, err, ColorReset)
		} else {
			fmt.Printf("%sLast response written to %s%s\n", ColorMagenta, path, ColorReset)
		}
	} else {
		fmt.Printf("\n%sNo response has been received in this session yet.%s\n", ColorGrey, ColorReset)
	}
}

func (a *AppState) callBot(botName string) {
	a.BotRunning = true
	defer func() { a.BotRunning = false }()

	fmt.Printf("\n%s%s%s:\n", ColorBlue, strings.Title(botName), ColorReset)

	modelInfo, ok := Models[botName]
	if !ok {
		fmt.Printf("%sUnknown model: %s%s\n", ColorRed, botName, ColorReset)

		return
	}

	messages := a.prepareMessages(botName, false)

	// JSON Request
	reqBody := map[string]interface{}{
		"model":       modelInfo["name"],
		"messages":    messages,
		"stream":      true,
		"temperature": 0.6,
		"provider": map[string]interface{}{
			"sort":            "latency",
			"ignore":          []string{"deepinfra/fp4", "baseten/fp4"},
			"order":           []string{"openai", "anthropic", "z-ai", "alibaba", "xai", "avian/fp8", "moonshotai", "minimax/fp8", "google-ai-studio", "google-vertex", "fireworks", "novita", "novita/fp8", "stealth", "deepseek", "atlas-cloud/fp8", "siliconflow/fp8"},
			"allow_fallbacks": false,
		},
	}

	// Tools
	if botName != "gpt5c" {
		reqBody["tools"] = []interface{}{
			map[string]interface{}{
				"type": "function",
				"function": map[string]interface{}{
					"name":        "executeshell",
					"description": "Executes a shell command and returns its output.",
					"parameters": map[string]interface{}{
						"type": "object",
						"properties": map[string]interface{}{
							"command": map[string]string{"type": "string", "description": "The shell command to execute."},
						},
						"required": []string{"command"},
					},
				},
			},
		}
		reqBody["tool_choice"] = "auto"
	}

	// Per-model reasoning config
	if r, ok := modelInfo["reasoning"]; ok && r != nil {
		switch v := r.(type) {
		case int:
			reqBody["reasoning"] = map[string]interface{}{"max_tokens": v, "enabled": true, "exclude": false}
		case string:
			reqBody["reasoning"] = map[string]interface{}{"effort": v, "enabled": true, "exclude": false}
		case bool:
			if v {
				reqBody["reasoning"] = map[string]interface{}{"enabled": true, "exclude": false}
			}
		}
	}

	reqBody["usage"] = map[string]bool{"include": true}

	jsonData, _ := json.Marshal(reqBody)
	a.LastRequestPayload = reqBody

	// Retry loop matching Python's retry_delays behavior
	delays := append([]float64{0}, a.RetryDelays...)
	var resp *http.Response
	var lastErr error

	for attempt, delay := range delays {
		if delay > 0 {
			fmt.Printf("%sRetrying in %.1fs...%s\n", ColorGrey, delay, ColorReset)
			time.Sleep(time.Duration(delay * float64(time.Second)))
		}

		// Check for interrupt before each attempt
		select {
		case <-a.Interrupt:
			fmt.Printf("%s[Interrupted]%s\n", ColorYellow, ColorReset)
			return
		default:
		}

		req, _ := http.NewRequest("POST", a.APIURL, bytes.NewBuffer(jsonData))
		req.Header.Set("Authorization", "Bearer "+a.OpenRouterAPIKey)
		req.Header.Set("Content-Type", "application/json")

		client := &http.Client{Timeout: 60 * time.Second}
		var err error
		resp, err = client.Do(req)
		if err != nil {
			lastErr = err
			fmt.Printf("%sAPI call failed (attempt %d): %v%s\n", ColorRed, attempt+1, err, ColorReset)
			if attempt < len(delays)-1 { continue }
			fmt.Printf("%sGiving up after %d attempts.%s\n", ColorRed, attempt+1, ColorReset)
			return
		}

		if resp.StatusCode != 200 {
			body, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			fmt.Printf("%sAPI call failed with status %d (attempt %d)%s\n", ColorRed, resp.StatusCode, attempt+1, ColorReset)
			fmt.Printf("%s%s%s\n", ColorGrey, string(body), ColorReset)
			lastErr = fmt.Errorf("status %d", resp.StatusCode)
			if attempt < len(delays)-1 { continue }
			fmt.Printf("%sGiving up after %d attempts.%s\n", ColorRed, attempt+1, ColorReset)
			return
		}
		lastErr = nil
		break // Success - exit retry loop
	}
	if lastErr != nil { return }
	defer resp.Body.Close()

	// Stream Reading with SIGINT handling
	reader := bufio.NewReader(resp.Body)
	fullResponse := ""
	var toolCalls []ToolCall
	currentToolCall := -1
	var reasoningDetailsAcc []map[string]any
	var responseEvents []interface{}
	interrupted := false

	// Set up SIGINT handler for this streaming session
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGINT)
	defer signal.Stop(sigChan)

	// Goroutine to handle SIGINT during streaming
	go func() {
		select {
		case <-sigChan:
			interrupted = true
			resp.Body.Close() // Force reader to return error
		case <-a.Interrupt:
			interrupted = true
			resp.Body.Close()
		}
	}()

	for {
		if interrupted {
			fmt.Printf("\n%s[Bot interrupted by user]%s\n", ColorYellow, ColorReset)
			return
		}
		line, err := reader.ReadString('\n')
		if err != nil {
			if interrupted {
				fmt.Printf("\n%s[Bot interrupted by user]%s\n", ColorYellow, ColorReset)
				return
			}
			break
		}

		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		data := line[6:]
		if data == "[DONE]" {
			break
		}

		var event struct {
			Choices []struct {
				Delta struct {
					Content          string           `json:"content"`
					ToolCalls        []ToolCall       `json:"tool_calls"`
					Reasoning        string           `json:"reasoning"`
					ReasoningDetails []map[string]any `json:"reasoning_details"`
				} `json:"delta"`
			} `json:"choices"`
			Usage *struct {
				Cost                    float64 `json:"cost"`
				PromptTokens            int     `json:"prompt_tokens"`
				CompletionTokens        int     `json:"completion_tokens"`
				TotalTokens             int     `json:"total_tokens"`
				CompletionTokensDetails *struct {
					ReasoningTokens int `json:"reasoning_tokens"`
				} `json:"completion_tokens_details"`
				PromptTokensDetails *struct {
					CachedTokens int `json:"cached_tokens"`
				} `json:"prompt_tokens_details"`
			} `json:"usage"`
		}

		// Capture raw event for /lastjson
		var rawEvent map[string]any
		if json.Unmarshal([]byte(data), &rawEvent) == nil {
			responseEvents = append(responseEvents, rawEvent)
		}

		if json.Unmarshal([]byte(data), &event) == nil {
			if event.Usage != nil {
				a.recordUsage(botName, event.Usage)
			}
			if len(event.Choices) > 0 {
				if rd := event.Choices[0].Delta.ReasoningDetails; len(rd) > 0 {
					reasoningDetailsAcc = append(reasoningDetailsAcc, rd...)
				}
				delta := event.Choices[0].Delta

				// Text Content
				if delta.Content != "" {
					fmt.Print(delta.Content)
					fullResponse += delta.Content
					// Stop token truncation (consai.py:1634)
					for _, tok := range stopTokens {
						if strings.Contains(delta.Content, tok) {
							goto streamDone
						}
					}
				}
				if delta.Reasoning != "" {
					fmt.Printf("%s%s%s", ColorGrey, delta.Reasoning, ColorReset)
				}

				// Tool Calls
				if len(delta.ToolCalls) > 0 {
					for _, tc := range delta.ToolCalls {
						// Assuming index is sequential/monotonic as per OpenAI spec
						idx := tc.Index // OpenAI usually sends index
						if currentToolCall != idx {
							// New tool call or switch
							// If appending to existing array logic needed
							if idx >= len(toolCalls) {
								toolCalls = append(toolCalls, tc)
							}
							currentToolCall = idx
						} else {
							// Append args
							toolCalls[idx].Function.Arguments += tc.Function.Arguments
						}
					}
				}
			}
		}
	}
streamDone:
	fmt.Println() // Newline at end

	// Save response events for /lastjson
	a.LastResponseEvents = responseEvents

	// Prefix reminder detection on cleaned response
	cleanedResponse := removeInlineToolCalls(fullResponse)
	reSaid := regexp.MustCompile(`<\[:~.*? said~:\]>`)
	a.NeedsPrefixReminder = reSaid.MatchString(cleanedResponse)

	// Process Tool Calls
	// 1. Unified list (from stream + inline regex parsing)

	inlineCalls := parseInlineToolCalls(fullResponse)

	// Execute
	mergedCalls := []ToolCall{}
	// Merge streamed
	for _, tc := range toolCalls {
		if tc.Function.Name != "" {
			mergedCalls = append(mergedCalls, tc)
		}
	}
	// Merge inline
	for _, tc := range inlineCalls {
		mergedCalls = append(mergedCalls, tc)
	}
	// Dedupe by command string: keep first occurrence, keep unparseable calls
	finalToolCalls := []ToolCall{}
	seenCmds := map[string]bool{}
	for _, tc := range mergedCalls {
		var args struct {
			Command string `json:"command"`
		}
		if json.Unmarshal([]byte(tc.Function.Arguments), &args) != nil || args.Command == "" {
			finalToolCalls = append(finalToolCalls, tc)
			continue
		}
		if !seenCmds[args.Command] {
			seenCmds[args.Command] = true
			finalToolCalls = append(finalToolCalls, tc)
		}
	}

	if len(finalToolCalls) > 0 {
		// Add assistant message with tool calls
		tcMsg := Message{
			Role:      "assistant",
			Content:   stripSaidTags(removeInlineToolCalls(fullResponse)),
			BotID:     botName,
			ToolCalls: finalToolCalls,
		}
		if len(reasoningDetailsAcc) > 0 && (botName == "3pro" || botName == "3flash") {
			tcMsg.ReasoningDetails = reasoningDetailsAcc
		}
		a.History = append(a.History, tcMsg)

		for _, tc := range finalToolCalls {
			if tc.Function.Name == "executeshell" {
				// Parse JSON args
				var args struct {
					Command string `json:"command"`
				}
				// Try parsing, if fails, might be just raw string or malformed
				if err := json.Unmarshal([]byte(tc.Function.Arguments), &args); err != nil {
					// fallback ??
				}

				output := ""
				if args.Command != "" {
					res, handled := a.maybeHandleCD(args.Command, func(s string) { fmt.Print(s) }, true)
					if handled {
						output = res
					} else {
						output = a.executeShellCommand(args.Command, func(s string) { fmt.Print(s) }, true, false)
					}
				} else {
					output = "Error: missing command"
				}

				toolMsg := Message{
					Role:       "tool",
					ToolCallID: sanitizeToolID(tc.ID),
					Content:    output,
				}
				if strings.Contains(args.Command, "applypatch") && output != "" && !strings.HasPrefix(output, "Done!") {
					toolMsg.ApplyPatchFailed = true
				}
				a.History = append(a.History, toolMsg)
			}
		}
		// Recursive call? The original loop does check interrupt and then calls bot again.
		// Here we just return for simplicity or loop. Python calls _call_bot recursively at the end.
		// Let's do nothing and let the main loop handle it? No, in Python call_bot calls call_bot.
		// We should call callBot unless interrupted.
		if !a.BotRunning { // prevent infinite loop if flag mismanagement
			a.callBot(botName)
		} else {
			// We are inside callBot, so we can re-call it?
			// No, standard recursion.
			// But we need to update state.
			// Actually, simply returning and letting User type is WRONG for tool use.
			// Tool use implies the bot should reply to the tool output.
			// So we must recurse.
			a.callBot(botName)
		}
	} else {
		// Just text
		msg := Message{
			Role:    "assistant",
			Content: stripSaidTags(removeInlineToolCalls(fullResponse)),
			BotID:   botName,
		}
		if len(reasoningDetailsAcc) > 0 && (botName == "3pro" || botName == "3flash") {
			msg.ReasoningDetails = reasoningDetailsAcc
		}
		a.History = append(a.History, msg)
	}
}

func parseInlineToolCalls(content string) []ToolCall {
	calls := []ToolCall{}

	// 1. Wrapper format: <｜tool calls begin｜>...<｜tool calls end｜>
	reWrapper := regexp.MustCompile(`(?s)<｜tool[\s▁]calls[\s▁]begin｜>(.*?)<｜tool[\s▁]calls[\s▁]end｜>`)
	reInnerTC := regexp.MustCompile(`(?s)<｜tool[\s▁]call[\s▁]begin｜>\s*executeshell<｜tool[\s▁]sep｜>(\{.*?\})\s*<｜tool[\s▁]call[\s▁]end｜>`)
	for i, wm := range reWrapper.FindAllStringSubmatch(content, -1) {
		for j, tcm := range reInnerTC.FindAllStringSubmatch(wm[1], -1) {
			var args map[string]interface{}
			if json.Unmarshal([]byte(tcm[1]), &args) != nil {
				continue
			}
			cmd, _ := args["command"].(string)
			if cmd == "" {
				continue
			}
			js, _ := json.Marshal(map[string]string{"command": cmd})
			calls = append(calls, ToolCall{
				ID:       fmt.Sprintf("inline_new_%d_%d_%d", time.Now().Unix(), i, j),
				Type:     "function",
				Function: ToolCallFunction{Name: "executeshell", Arguments: string(js)},
			})
		}
	}

	// 2. Original executeshell({...}) format
	reOld := regexp.MustCompile(`(?s)executeshell\s*\(\s*(\{.*?\})\s*\)`)
	for i, m := range reOld.FindAllStringSubmatch(content, -1) {
		calls = append(calls, ToolCall{
			ID:       fmt.Sprintf("inline_old_%d_%d", time.Now().Unix(), i),
			Type:     "function",
			Function: ToolCallFunction{Name: "executeshell", Arguments: m[1]},
		})
	}

	// Markdown
	// (?s) for content
	reMD := regexp.MustCompile(`(?s):\s*` + "```" + `(?:bash|shell|sh)\s*\n(.*?)\n` + "```")
	matchesMD := reMD.FindAllStringSubmatch(content, -1)
	for i, m := range matchesMD {
		// Create proper JSON args
		js, _ := json.Marshal(map[string]string{"command": m[1]})
		calls = append(calls, ToolCall{
			ID:   fmt.Sprintf("inline_md_%d_%d", time.Now().Unix(), i),
			Type: "function",
			Function: ToolCallFunction{
				Name:      "executeshell",
				Arguments: string(js),
			},
		})
	}

	return calls
}
