# ChefAI

ChefAI step 1: hardcoded today's shipment expenses printed in the terminal.

- Run: `python Agent.py`
- Uses OpenAI model `gpt-4o-mini`
- API key comes from the Windows environment variable `LLM_API_KEY`
- LLM call uses `urllib`, not the `openai` package
- Later: MCP + CSV + HTML

## Step 2

- `SKILL.md` (skill `format-expense-table`) is loaded by `Agent.py` and used only for the second, formatted table.
- The first report is the plain step 1 output; the totals are always computed in Python, never by the LLM.
