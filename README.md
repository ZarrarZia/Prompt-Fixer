# Prompt Fixer

A floating desktop button that rewrites whatever you're typing, using a **local** LLM through [Ollama](https://ollama.com). It can turn text into a well-structured AI prompt, translate it into English, or write it up as a formatted email. It runs entirely on your machine, with no API keys and no data leaving your PC.

Type in VS Code, a terminal, a browser, or a chat box, click the overlay, and the text is replaced in place.

```
before:  add rate limiting to my express api login route

after:   [ROLE & CONTEXT]: Backend developer working on an Express API with authentication.
         [TASK]: Add rate limiting to the login route to cap attempts per IP.
         [CONSTRAINTS]: Use express-rate-limit; 5 attempts/min per IP; login route only;
         return a clear error message when the limit is hit.
```

## Features

- **One-click, in-place rewrite:** it copies the text from the focused input, rewrites it, and pastes it back.
- **Four modes**
  - 🟢 **Standard Structured Prompt** (`S` badge): role, task, and constraints.
  - 🟣 **Loop Engineering Prompt** (`L` badge): goal, then inspection, incremental diff, verification, self-correction, and termination criteria. Built for autonomous coding agents.
  - 🩵 **Translate to English** (`EN` badge): a faithful translation from any language, including Roman Urdu/Hindi. It adds, removes, and answers nothing; English input only gets its spelling and grammar fixed.
  - 🩷 **Write as Email** (`@` badge): turns rough notes into a formatted email with a subject, greeting, body, and sign-off. It uses only facts from your text and puts `[placeholders]` where details are missing.
- **A model per mode:** a small, fast model for prompts and a stronger multilingual model for English and Email.
- **Live progress:** a green progress ring with a percentage, plus a status pill (Copying → Thinking → Rewriting → Pasting).
- **Always on top, never steals focus:** your cursor stays in the app you're working in.
- **Tuned for local inference:** the model stays loaded (`keep_alive: -1`), uses a small context (`num_ctx: 2048`), low temperature, a capped output length, and streamed responses.
- **Safe on failure:** if Ollama is offline, nothing is typed and your clipboard is left untouched.
- **Single file**, with PyQt6 as the only dependency.

## Requirements

| | |
|---|---|
| OS | **Windows 10 / 11** (focus switching and keystrokes use the Win32 API) |
| Python | 3.10 or newer |
| Ollama | latest, from [ollama.com/download](https://ollama.com/download) |
| RAM | ~2 GB for the prompt modes; ~11 GB free if you also use English/Email with the default `gemma4:e4b` (see [Choosing models](#choosing-models)) |

## Installation

**1. Install Python.** Download it from [python.org](https://www.python.org/downloads/). During setup, tick **"Add Python to PATH"**.

**2. Install Ollama.** Download it from [ollama.com/download](https://ollama.com/download) and run the installer. Ollama then runs in the background (you'll see its icon in the system tray).

**3. Download the models:**

```powershell
ollama pull qwen2.5-coder:1.5b   # prompt modes, ~1 GB
ollama pull gemma4:e4b           # English + Email modes, ~9.6 GB
```

If you only want the prompt modes, you can skip `gemma4:e4b`. For a lighter English/Email setup, see [Choosing models](#choosing-models).

**4. Get the code and install the dependency:**

```powershell
git clone https://github.com/ZarrarZia/Prompt-Fixer.git
cd Prompt-Fixer
pip install -r requirements.txt
```

(If you don't have git, use **Code → Download ZIP** on GitHub and extract it.)

**5. Run it:**

```powershell
pyw app.py
```

`pyw` runs it without a console window. Use `py app.py` if you want to see errors in the terminal. A round button appears in the bottom-right corner of your screen.

## Usage

| Action | Result |
|---|---|
| **Click** | Rewrite the text in the input you were last typing in |
| **Hold 3 seconds** | Open the menu (a ring fills while you hold) |
| **Right-click** | Open the menu instantly |
| **Drag** | Move the button (its position is remembered) |

From the menu you can switch modes, choose the model for the current mode, recheck the connection, or quit.

**Tip:** click inside the text box you want to fix *first*, then click the overlay.

### Status indicators

- 🟢 **Green/blue ring, `S` badge:** Standard Structured Prompt
- 🟣 **Purple/amber ring, `L` badge:** Loop Engineering Prompt
- 🩵 **Teal ring, `Aa` icon, `EN` badge:** Translate to English
- 🩷 **Pink ring, envelope icon, `@` badge:** Write as Email
- 🔴 **Red dot:** Ollama is offline
- **Green flash:** the rewrite was pasted
- **Red flash with a tooltip:** something failed (the tooltip explains what)

## Configuration

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `PROMPT_FIXER_MODEL` | `qwen2.5-coder:1.5b` | Model for the Standard and Loop modes |
| `PROMPT_FIXER_TEXT_MODEL` | `gemma4:e4b` | Model for the English and Email modes |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server address |

Other settings are constants near the top of `app.py`:

- `SYSTEM_PROMPTS`: the instructions for each mode.
- `BREVITY`: asks the model for terse output in the prompt modes, which is roughly 40% faster. Set it to `""` for longer rewrites.
- `MODE_OPTIONS`: per-mode temperature and output length (translation uses 0.1 to stay literal).
- `OLLAMA_OPTIONS`: `num_ctx`, `temperature`, and `num_predict`.
- `HOLD_MS`: how long to hold for the menu.

### Choosing models

Each mode remembers its own model. Switch to a mode, then pick **Model for this mode** in the menu. A model loads the first time its mode is used.

| Model | Size | Good for | Notes |
|---|---|---|---|
| `qwen2.5-coder:1.5b` | ~1 GB | Standard, Loop | **Default for prompts.** Fast on CPU-only laptops (~4 s Standard, ~10 s Loop) |
| `qwen2.5:3b` | ~2 GB | any mode | Better wording; a lighter English/Email option, but less accurate on Roman Urdu |
| `gemma4:e4b` | ~9.6 GB | English, Email | **Default for English/Email.** Most accurate translation; ~12–15 s per sentence on CPU |

Measured on a CPU-only laptop, the 1.5B model was not accurate enough for translation: it changed meanings and added commentary. That's why English and Email use a stronger model by default.

Pull another model with `ollama pull <name>`, then select it from the right-click menu.

## Quick test (no GUI)

Checks that Ollama and the model work:

```powershell
py app.py --test "make a login page"
py app.py --test --loop "fix the flaky login test"
py app.py --test --english "mujhe kal tak report bhej do"
py app.py --test --email "client ko batana hai ke kaam 2 din late hoga"
```

## Start automatically with Windows

1. Press **Win + R**, type `shell:startup`, and press Enter.
2. Create a shortcut there with the target `pyw "C:\path\to\Prompt-Fixer\app.py"`.

Launching `app.py` again automatically closes any copy that is already running, so it's safe to re-run after updating.

## Troubleshooting

| Problem | Fix |
|---|---|
| Red dot / "Ollama is offline" | Start Ollama from the Start menu, or run `ollama serve` |
| "Model ... is not pulled" | Run the `ollama pull` command shown in the message (e.g. `ollama pull gemma4:e4b`) |
| English/Email is slow or uses a lot of RAM | Choose `qwen2.5:3b` for that mode from the menu (faster, slightly less accurate) |
| "Nothing was copied" | Click inside the input box before clicking the overlay |
| Doesn't work in an admin app | Run Prompt Fixer as administrator too (Windows blocks keystrokes into elevated windows) |
| Terminal only rewrites the current line | Expected: many shells treat Ctrl+A as "go to start of line" |
| Slow responses | Use a smaller model, or keep `BREVITY` enabled; a GPU helps most |

## How it works

1. A background timer remembers the last window you were typing in.
2. On click, it checks that Ollama is reachable **before** touching anything.
3. It brings that window back to the front, then sends **Ctrl+A** and **Ctrl+C**.
4. It sends the text to Ollama's `/api/chat` on a worker thread, streaming the reply to drive the progress bar.
5. It selects the text again and pastes the result with **Ctrl+V**. If anything fails, your original clipboard is restored.
