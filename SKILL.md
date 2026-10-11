# format-expense-table

- **Name:** format-expense-table
- **When to use:** after today's expenses are totaled.

## Rules

- Do not change the numbers; only format.
- Columns: Item | Vendor | Qty | Unit price | Line total
- Right-align Qty and all money columns.
- Money is written as $X.XX.
- Output, in order:
  1. Title line: ChefAI — today's shipment (formatted)
  2. Header row
  3. Dash separator
  4. One row per item
  5. A TOTAL row with the grand total in the last column
