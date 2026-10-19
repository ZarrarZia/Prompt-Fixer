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

## The 4 modes at a glance

| Mode | What you type | What you get | AI model |
|---|---|---|---|
| 🟢 **Standard Structured Prompt** | `add dark mode to my settings page` | A prompt with `[ROLE & CONTEXT]`, `[TASK]` and `[CONSTRAINTS]` | `qwen2.5-coder:1.5b` (fast) |
| 🟣 **Loop Engineering Prompt** | `fix the flaky login test` | An agent plan: goal, inspect, minimal change, verify, self-correct, done criteria | `qwen2.5-coder:1.5b` (fast) |
| 🩵 **Translate to English** | `server ka masla abhi tak hal nahi hua, team us par kaam kar rahi hai` | `The server issue has not been resolved yet, the team is working on it.` | `qwen2.5:3b` |
| 🩷 **Write as Email** | `client ko batana hai ke website ka kaam 2 din late hoga kyunke server issue aa gaya tha` | A complete email: subject, greeting, body, sign-off | `qwen2.5:3b` |

Switch modes from the menu (right-click the button, or hold it for 3 seconds). See [AI models](#ai-models) for why each mode uses the model it does.

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
| RAM | ~4 GB free (both default models loaded); ~12 GB if you choose the optional `gemma4:e4b` (see [AI models](#ai-models)) |
| Disk | ~3 GB for the default models (+9.6 GB for the optional `gemma4:e4b`) |

## Installation

### Quick install (recommended)

1. Download the project: **Code → Download ZIP** on GitHub, then extract it (or `git clone https://github.com/ZarrarZia/Prompt-Fixer.git`).
2. Double-click **`setup.bat`**.

`setup.bat` does everything for you:

| Step | What it does |
|---|---|
| 1 | Checks for Python 3.10+, and installs it with `winget` if it's missing |
| 2 | Installs the Python package (`pip install -r requirements.txt`) |
| 3 | Checks for Ollama, installs it with `winget` if it's missing, and starts it |
| 4 | Downloads the AI models (it asks which English/Email model you want; see below) |
| 5 | Creates a **Prompt Fixer** desktop shortcut, and optionally starts it with Windows |

When it asks about the English + Email model:

- **1:** `qwen2.5:3b`, **recommended**: about 2 GB, fast, and good for most text
- **2:** `gemma4:e4b`, the most accurate on Roman Urdu, but heavy (9.6 GB download, ~10 GB of RAM)
- **3:** skip, if you only want the two prompt modes

For a silent install with the default models, run `setup.bat /yes`.

> **Why aren't the models in `requirements.txt`?** That file can only list Python packages for pip. Ollama models are downloaded by Ollama, which is why `setup.bat` exists.

If Python had to be installed, setup asks you to run `setup.bat` once more so Windows picks up the new PATH.

### Manual install

**1. Install Python.** Download it from [python.org](https://www.python.org/downloads/). During setup, tick **"Add Python to PATH"**.

**2. Install Ollama.** Download it from [ollama.com/download](https://ollama.com/download) and run the installer. Ollama then runs in the background (you'll see its icon in the system tray).

**3. Download the models:**

```powershell
ollama pull qwen2.5-coder:1.5b   # prompt modes, ~1 GB
ollama pull qwen2.5:3b           # English + Email modes, ~2 GB
```

If you only want the prompt modes, you can skip `qwen2.5:3b`. For the most accurate translation, see [AI models](#ai-models).

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

## AI models

Everything runs locally through Ollama. Each mode uses the model that fits its job:

| Model | Used for | Download | Why |
|---|---|---|---|
| `qwen2.5-coder:1.5b` | Standard, Loop | ~1 GB | Small and fast, and good at structured, technical prompts. About 4 s (Standard) and 10 s (Loop) on a CPU-only laptop. |
| `qwen2.5:3b` | English, Email | ~2 GB | **Default.** A good balance of speed, size, and language quality. About 4–8 s per sentence and 15 s per email on CPU. |
| `gemma4:e4b` | optional: English, Email | ~9.6 GB | The most accurate on Roman Urdu/Hindi, but heavy: ~10 GB of RAM and ~13 s per sentence on CPU. |

**Why these models?** The 1.5B model is fast enough for prompts but too inaccurate for translation. `qwen2.5:3b` is the default for English and Email because it's light and fast. To improve its accuracy, the app gives it 5 worked Roman Urdu → English examples before each translation; in testing on sentences it hadn't seen, that raised accuracy from 4/8 to 6/8 sentences correct. It can still misread some slang words (e.g. "naraz" = upset), so for important text, choose `gemma4:e4b` for that mode from the menu.

> **License note:** `qwen2.5:3b` is under the Qwen Research License, which allows **non-commercial use only**. `qwen2.5-coder:1.5b` (Apache 2.0) and `gemma4:e4b` (Gemma terms) allow commercial use.

**Speed tips:** each model stays loaded in memory after first use, so there's no reload delay. "Thinking" is turned off for models that support it (such as Gemma), which cuts their response time from over a minute to seconds. A GPU makes everything much faster.

## Configuration

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `PROMPT_FIXER_MODEL` | `qwen2.5-coder:1.5b` | Starting model for the Standard and Loop modes |
| `PROMPT_FIXER_TEXT_MODEL` | `qwen2.5:3b` | Starting model for the English and Email modes (`setup.bat` sets this if you choose option 2) |

A model you pick from the menu always takes priority over these defaults.
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server address |

Other settings are constants near the top of `app.py`:

- `SYSTEM_PROMPTS`: the instructions for each mode.
- `BREVITY`: asks the model for terse output in the prompt modes, which is roughly 40% faster. Set it to `""` for longer rewrites.
- `MODE_OPTIONS`: per-mode temperature and output length (translation uses 0.1 to stay literal).
- `OLLAMA_OPTIONS`: `num_ctx`, `temperature`, and `num_predict`.
- `HOLD_MS`: how long to hold for the menu.

### Choosing models

Each mode remembers its own model. Switch to a mode, then pick **Model for this mode** in the menu. A model loads the first time its mode is used. To try another model, download it with `ollama pull <name>`, then select it from the menu. See [AI models](#ai-models) for the recommended ones.

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
| `setup.bat` says winget is missing | Install "App Installer" from the Microsoft Store, or install Python and Ollama manually (see [Manual install](#manual-install)) |
| Red dot / "Ollama is offline" | Start Ollama from the Start menu, or run `ollama serve` |
| "Model ... is not pulled" | Run the `ollama pull` command shown in the message (e.g. `ollama pull qwen2.5:3b`) |
| A translation has the wrong meaning | Run `ollama pull gemma4:e4b`, then choose it for that mode from the menu (more accurate, but heavier and slower) |
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
