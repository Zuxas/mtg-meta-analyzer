# How I Built the MTG Meta Analyzer with AI
### A Process Log for Learning AI-Assisted Development
**Author:** Jeremy Wallace (Zuxas)  
**Project:** MTG Meta Analyzer  
**Timeline:** March 20 - April 6, 2026 (~2.5 weeks)  
**Status at time of writing:** 91 commits, 262k+ match records, 10-tab desktop GUI

---

## The Starting Point

I'm not a software developer. I'm a competitive Magic: The Gathering player and Team Resolve team captain who wanted a tool that didn't exist: a personal desktop app that scrapes tournament data from multiple sources, tracks the meta across formats, and helps me prep for RCQs and Regional Championships.

The tools I used to build it: **Claude Code** (Anthropic's CLI for Claude) and **ChatGPT** for research and brainstorming. The IDE: **VS Code**.

---

## The Process, Step by Step

### Phase 1: Start Small, Learn the Loop (Day 1)

**What I did:**
- Started with a single, focused goal: scrape MTGTop8 tournament results and store them in a database
- Asked Claude/ChatGPT to explain what a web scraper is, what SQLite is, what Python libraries I'd need
- Had AI write the first scraper (`mtgtop8.py` - 265 lines) and the database schema

**What I learned:**
- Don't ask AI to build the whole thing at once. Start with one script that does one thing
- Run the code after every change. Read the errors. Paste them back to the AI
- The loop is: **describe what you want -> get code -> run it -> fix errors -> repeat**
- I learned Python syntax by reading what the AI wrote, not from a textbook

**Key takeaway:** Your first script will be ugly. That's fine. The MTGTop8 scraper was the foundation everything else was built on.

---

### Phase 2: Expand Carefully, One Feature at a Time (Days 2-5)

**What I did:**
- Added more scrapers: MTGDecks.net (needed Cloudflare bypass), melee.gg (real match data)
- Built the analysis layer: win rates, archetype normalization, matchup matrices
- Each new feature was a separate conversation/session with the AI

**What I learned:**
- **Keep a development document.** I started maintaining `NEXT_STEPS.md` - a session-by-session log of what was built, what broke, and what's next. This became critical for giving AI context in new conversations
- **Give AI context about your project.** I created `CLAUDE.md` - a file that describes the entire project state, rules, and architecture. Every new AI session starts by reading this file
- **Type hints matter.** Adding `name: str` and `-> str` to function signatures wasn't just for readability - it helped the AI understand my code when I pasted it in, and it helped me understand what functions expected

**Key takeaway:** Documentation isn't busywork. It's how you maintain continuity between AI sessions. Without `CLAUDE.md` and `NEXT_STEPS.md`, every conversation would start from scratch.

---

### Phase 3: The GUI Jump (Days 5-10)

**What I did:**
- Decided to build a desktop app instead of just CLI scripts
- AI recommended PyQt6. Started with a single-tab window, grew to 10 tabs
- Dashboard, Deck Analyzer, Search, Charts, Predictions, Knowledge Base, Tournament Prep, Match Log, Card Browser, Set Analysis

**What I learned:**
- **You don't need to understand everything the AI writes.** I didn't know Qt signals/slots when I started. I learned by seeing the patterns repeat across tabs
- **But you DO need to understand the structure.** I made sure every tab was its own file, every widget was reusable, every database query was in the `db/` folder. The AI helped me maintain this organization
- **Test constantly.** Every tab got tested as soon as it was written. Click every button. Try to break it. The number of crashes I caught early saved hours later

**Key takeaway:** Building a GUI is where the project goes from "scripts on my computer" to "this feels like a real app." It's also where complexity explodes - stay organized.

---

### Phase 4: Polish and Stability (Days 10-17)

**What I did:**
- Fixed Unicode crashes, memory leaks, worker thread lifecycle issues
- Added system tray integration, first-run setup wizard, Task Scheduler automation
- Built the sideboard advisor, deck classifier, and tournament math systems
- Hit 262k+ real match records across 5 formats

**What I learned:**
- **Bugs teach you more than features.** Debugging a worker memory leak taught me more about Python threading than any tutorial. Paste the traceback to the AI, but also try to understand *why* it crashed
- **Automation is worth the investment.** Setting up `.bat` scripts and Task Scheduler means the app updates itself daily at 6 AM. I wake up to fresh data
- **Set rules for yourself.** My non-negotiable: update docs before every commit, always push after commit. This discipline kept the project from becoming a mess

**Key takeaway:** The difference between a hobby project and a tool you actually use every day is reliability. Spend time on error handling, logging, and automation.

---

## How to Talk to AI (The Practical Stuff)

### What works:
1. **Be specific.** "Write a function that scrapes MTGTop8 event pages and returns a list of dicts with keys: event_name, date, format, num_players" beats "scrape MTGTop8"
2. **Give context.** Paste your existing code, your database schema, your error messages. The more context, the better the output
3. **Iterate, don't restart.** If the first attempt is 80% right, fix the 20% - don't ask for a complete rewrite
4. **Use a project context file.** My `CLAUDE.md` is 43KB. It has every rule, every working feature, every file path. When I start a session, the AI reads it and knows the whole project
5. **Ask "why" not just "how."** Understanding why the AI chose a certain approach helps you make decisions later without AI

### What doesn't work:
1. **"Build me an app"** - Too vague. Start with one function
2. **Ignoring errors** - Read them. They tell you exactly what's wrong
3. **Not testing** - Run the code. Click the buttons. Feed it bad data
4. **Skipping documentation** - Future you (and future AI sessions) will suffer
5. **Trying to build everything at once** - One feature per session. Get it working. Commit. Move on

---

## The Tools I Used

| Tool | What For | Why |
|------|----------|-----|
| **Claude Code (CLI)** | Primary development partner | Reads my whole project, writes code in-place, runs tests, commits to git |
| **ChatGPT** | Research and brainstorming | Good for "what's the best way to..." questions and exploring approaches |
| **VS Code** | IDE | Where I read code, review changes, and run the app |
| **Git** | Version control | 91 commits. Every feature, every fix, tracked and reversible |
| **Python 3.13** | Language | AI writes great Python. Type hints + docstrings = readable code |
| **PyQt6** | Desktop GUI | Professional-looking app without web development complexity |
| **SQLite** | Database | Zero setup, file-based, perfect for a personal tool |

---

## The Numbers

| Metric | Value |
|--------|-------|
| Development time | ~2.5 weeks (Mar 20 - Apr 6, 2026) |
| Git commits | 91 |
| Python files | 40+ |
| Lines of code | 10,000+ |
| GUI tabs | 10 + system tray |
| Data scraped | 262k+ match records, 37k+ decklists |
| Formats covered | Standard, Pioneer, Modern, Legacy, Pauper |
| Batch automations | 3 scheduled tasks (daily scrape, daily update, weekly card refresh) |
| Prior coding experience | Minimal |

---

## What I'd Tell Someone Starting Today

1. **Pick a project you actually care about.** I built this because I wanted it. That motivation carried me through every frustrating bug
2. **Start with one script.** Not an app. Not a framework. One Python file that does one thing
3. **Use Claude Code if you can.** Having the AI read your whole project, edit files directly, and run commands in your terminal is a different experience than copy-pasting into a chat window
4. **Keep a session log.** Write down what you built each session. What broke. What you learned. This becomes your project's memory
5. **Commit early, commit often.** Git is your undo button. Use it
6. **Read the code the AI writes.** You don't need to understand every line on day one, but over time, patterns will click. I can now read Python fluently even though I never formally learned it
7. **Don't be afraid of complexity.** This project has scrapers, databases, a GUI, charts, automation, and AI integration. None of it was built in a day. It grew one feature at a time
8. **A dev friend said my code "looks like professional python code."** That's not because I'm a professional - it's because I insisted on type hints, docstrings, and clean structure from the start, and the AI helped enforce those standards

---

*Last updated: 2026-04-06*
