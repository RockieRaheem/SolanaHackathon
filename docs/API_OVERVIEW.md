# Active API Surface

Base path: `/api/v1`

- `GET /health`
- `GET /students`
- `GET /students/:id`
- `GET /fees`
- `GET /payments`
- `GET /arrears`
- `GET /reconciliation`
- `GET /reports`
- `GET /audit-events`

The Python API and Supabase PostgreSQL database are the active implementation. New endpoints must support a defined bursar workflow end to end.
