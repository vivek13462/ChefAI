# ChefAI

ChefAI step 1: hardcoded today's shipment expenses printed in the terminal.

- Run: `python Agent.py`
- Uses OpenAI model `gpt-4o-mini`
- API key comes from the Windows environment variable `LLM_API_KEY`
- LLM call uses `urllib`, not the `openai` package
- Later: skill for a nicer table, then MCP + CSV + HTML
