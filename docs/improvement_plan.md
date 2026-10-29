# Improvement plan: identity-gated hybrid meal agent

## Objective

Improve the reliability of natural-language orchestration around Beacon's fixed
deterministic Knapsack recommender without conflating orchestration quality with
meal-selection quality.

## Research questions

1. How reliably do local LLMs route requests and execute the required tool workflow?
2. Does a deterministic identity gate prevent recommendations
   for missing, unknown, ambiguous, or mismatched personas?
3. What utility, latency, and model-compliance tradeoffs does the gate introduce?
4. In a separate follow-up, can an LLM improve preference or nutrition metrics by
   reranking deterministic candidate plans without violating hard constraints?

## Experiment A: orchestration safety

### Matched conditions

1. **Prompt-only agent:** the LLM receives the policy in its system prompt and
   controls all three tools.
2. **Identity-gated hybrid agent:** deterministic code resolves one explicit stored
   persona before model execution, locks profile and Knapsack tools to that ID,
   bypasses the model with a clarification when identity is unclear, and renders
   the final response from trusted application state.

Both conditions retain the same request set, tool semantics, Beacon backend,
Knapsack implementation, temperature, and trace-based scorer.

3. **No-LLM pipeline:** deterministic code resolves the name and directly runs
   Knapsack or returns a clarification. This baseline passes the current 30
   cases and shows that the present explicit-name dataset does not require an
   LLM.

### Models

- `llama3.2:1b`
- `llama3.2:3b`
- `phi4-mini:3.8b`
- `qwen3.5:4b`
- `granite4:3b`

`qwen2-math:1.5b` is excluded because the reused ADF study identifies it as a
direct-only model that does not support tool calling.

### Primary metrics

- complete-case pass rate;
- intended-persona routing;
- correct Knapsack action;
- exact deterministic plan fidelity;
- required tool sequence;
- clarification success;
- unsafe Knapsack executions on unclear requests;
- policy-blocked calls;
- API/loop and tool failures; and
- latency.

## Experiment B: recommendation source (preliminary controlled comparison)

Keep this separate from Experiment A.

1. **Deterministic-only:** Beacon Knapsack selects the plan.
2. **LLM selector:** Granite 4 3B and Llama 3.2 3B select directly from the same
   complete role-eligible catalog using the stored profile. Role/catalog syntax
   is constrained, but no persona-specific dietary filter or recommender is used.
3. **Constrained hybrid reranker (next):** deterministic code generates multiple valid
   candidate plans; the LLM reranks them; a deterministic validator rejects any
   role, restriction, or catalog violation.

The comparison measures goodness, Beacon quality, nutrition fit, hard-constraint
violations, repeated foods, exact Knapsack agreement, latency, and tokens. A
larger follow-up should add repeated runs, preference fit, and explanation
faithfulness.

## Interpretation rules

- MCP or LangChain adoption is an implementation/portability comparison, not the
  scientific novelty.
- A gate improvement is a system-level result; it does not mean the underlying
  LLM became safer.
- The present six-person data are simulated and do not establish clinical safety.
- Experiment B is a six-person, one-run preliminary comparison; it does not establish general
  recommendation superiority or clinical safety.

