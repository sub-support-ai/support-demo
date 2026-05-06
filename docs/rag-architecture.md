# RAG architecture notes

## Current state

Knowledge articles already have structured fields:

- `problem`
- `symptoms`
- `applies_to`
- `steps`
- `when_to_escalate`
- `required_context`
- `owner`
- `reviewed_at`
- `expires_at`
- `version`
- `access_scope`

Production PostgreSQL search uses:

- generated `tsvector` column: `knowledge_articles.search_vector`;
- GIN index: `ix_knowledge_articles_search_vector`;
- `websearch_to_tsquery` with `russian` and `simple` configs;
- `ts_rank_cd` as the database full-text score;
- application-level additions: request context filters, freshness, feedback score.

The service keeps a SQLite-compatible fallback for local tests.

## Decision thresholds

- High score: answer from the article.
- Medium score: ask for missing context from `required_context`.
- Low score: do not show a weak article; continue collecting request context.

This prevents irrelevant answers for cases where the user describes a physical incident or a topic not covered by the knowledge base.

## Feedback loop

For each shown article the system stores:

- article id;
- conversation id;
- message id;
- user id;
- original query;
- search score;
- decision: `answer`, `clarify`, `escalate`;
- later user feedback: `helped`, `not_helped`, `not_relevant`;
- linked escalated ticket id if the user creates a request after the article.

These fields support deflection rate, helpfulness rate and escalation-after-article metrics.

## pgvector rollout

Do not add a mandatory pgvector migration until the database image and extension are ready.

Correct rollout order:

1. Backup existing PostgreSQL data.
2. Move dev/staging database to a PostgreSQL image with pgvector installed.
3. Add a migration with `CREATE EXTENSION IF NOT EXISTS vector`.
4. Add vector columns to `knowledge_chunks`, not only to whole articles.
5. Add HNSW or IVFFlat index after enough chunks exist.
6. Add an embedding worker that recalculates embeddings when article content changes.
7. Combine final rank as:

```text
full_text_score + semantic_score + context_score + freshness_score + feedback_score
```

Until then, PostgreSQL full-text search is the primary reliable retrieval layer.
