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

## Step 4: MCP client

`Agent.py` can connect to a separate, standalone MCP server (not part of this folder).

- Edit `MCP_SERVER_PY` at the top of `Agent.py` to the standalone `server.py` path.
- STDIO: `python Agent.py`, choose 1 (the agent starts the server itself).
- HTTP: in the server folder run `python server.py --http`, then here `python Agent.py`, choose 2 (`MCP_HTTP_URL` is `http://127.0.0.1:8765/mcp`).
- After connecting, the LLM plans the tool calls to produce the three invoices. Then you can ask more questions. Type Q to quit.
- The planner maps years and singular/plural item words. Invalid or null tool names are skipped, not sent to MCP.
- The MCP client uses only the standard library (`subprocess`, `urllib`); no pip packages.
- The STDIO server receives only a minimal set of operating-system environment variables; credentials such as `LLM_API_KEY` remain in the ChefAI process.
