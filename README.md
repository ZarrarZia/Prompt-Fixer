# Prompt Fixer

A floating desktop button that rewrites whatever you're typing into a well-structured AI prompt, using a **local** LLM through [Ollama](https://ollama.com). It runs entirely on your machine, with no API keys and no data leaving your PC.

Type a rough instruction in VS Code, a terminal, a browser, or a chat box, click the overlay, and the text is replaced in place with a clean, structured prompt.

```
before:  add rate limiting to my express api login route

after:   [ROLE & CONTEXT]: Backend developer working on an Express API with authentication.
         [TASK]: Add rate limiting to the login route to cap attempts per IP.
         [CONSTRAINTS]: Use express-rate-limit; 5 attempts/min per IP; login route only;
         return a clear error message when the limit is hit.
```

## Features

- **One-click, in-place rewrite:** it copies the text from the focused input, rewrites it, and pastes it back.
- **Two prompt modes**
  - 🟢 **Standard Structured** (`S` badge): role, task, and constraints.
  - 🟣 **Loop Engineering** (`L` badge): goal, then inspection, incremental diff, verification, self-correction, and termination criteria. Built for autonomous coding agents.
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
| RAM | ~2 GB free for the default model |

## Installation

**1. Install Python.** Download it from [python.org](https://www.python.org/downloads/). During setup, tick **"Add Python to PATH"**.

**2. Install Ollama.** Download it from [ollama.com/download](https://ollama.com/download) and run the installer. Ollama then runs in the background (you'll see its icon in the system tray).

**3. Download the model** (about 1 GB):

```powershell
ollama pull qwen2.5-coder:1.5b
```

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

From the menu you can switch between **Standard** and **Loop** mode, pick any installed Ollama model, recheck the connection, or quit.

**Tip:** click inside the text box you want to fix *first*, then click the overlay.

### Status indicators

- 🟢 **Green/blue ring, `S` badge:** Standard Structured mode
- 🟣 **Purple/amber ring, `L` badge:** Loop Engineering mode
- 🔴 **Red dot:** Ollama is offline
- **Green flash:** the rewrite was pasted
- **Red flash with a tooltip:** something failed (the tooltip explains what)

## Configuration

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `PROMPT_FIXER_MODEL` | `qwen2.5-coder:1.5b` | Ollama model to use |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server address |

Other settings are constants near the top of `app.py`:

- `SYSTEM_PROMPTS`: the rewrite instructions for each mode.
- `BREVITY`: asks the model for terse output, which is roughly 40% faster. Set it to `""` for longer rewrites.
- `OLLAMA_OPTIONS`: `num_ctx`, `temperature`, and `num_predict`.
- `HOLD_MS`: how long to hold for the menu.

### Choosing a model

| Model | Size | Notes |
|---|---|---|
| `qwen2.5-coder:1.5b` | ~1 GB | **Default.** Fast on CPU-only laptops (~4 s Standard, ~10 s Loop) |
| `qwen2.5:3b` | ~2 GB | Better wording, about 2× slower on CPU |
| any larger model | varies | Recommended only if you have a GPU |

Pull another model with `ollama pull <name>`, then select it from the right-click menu.

## Quick test (no GUI)

Checks that Ollama and the model work:

```powershell
py app.py --test "make a login page"
py app.py --test --loop "fix the flaky login test"
```

## Start automatically with Windows

1. Press **Win + R**, type `shell:startup`, and press Enter.
2. Create a shortcut there with the target `pyw "C:\path\to\Prompt-Fixer\app.py"`.

Launching `app.py` again automatically closes any copy that is already running, so it's safe to re-run after updating.

## Troubleshooting

| Problem | Fix |
|---|---|
| Red dot / "Ollama is offline" | Start Ollama from the Start menu, or run `ollama serve` |
| "Model ... is not pulled" | `ollama pull qwen2.5-coder:1.5b` |
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
