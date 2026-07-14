# Remaining Translation Export

- source: C:\Games\No One Lives Forever 2\_work\analysis\CRES_modernizer_strings.csv
- CRES rows: 6355
- excluded IDs from chapter01_priority.tsv: 1228
- exported rows: 5127

## Category Counts

- dialogue: 1854
- equipment: 228
- intel: 922
- menu: 951
- mission: 221
- mission_failure: 2
- mission_objective: 202
- other: 410
- reward: 291
- server_admin: 46

## Editing Rules

- Translate only the `zh` column.
- Keep `%s`, `%d`, `%1!d!`, `@`, and similar placeholders intact.
- Keep `<` and `>` around angle-bracket labels.
- Newlines in `english` are escaped as `\n`; use `\n` in `zh` when you need a manual line break.
- `server_admin` / SCMD rows are low priority for single-player testing.
