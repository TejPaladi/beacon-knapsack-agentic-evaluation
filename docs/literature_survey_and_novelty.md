# Focused literature survey and novelty statement

## Why the current agent is genuine

ReAct defines an agent pattern in which a language model interleaves reasoning
and actions against an external environment. Our implementation uses the same
observable control structure: the model receives tool schemas, selects tool names
and arguments, observes results, and decides the next action. LangChain is one
possible harness for that loop, but it is not what makes the loop agentic.

- Yao et al. (2023), [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629).
- LangChain's current documentation likewise defines an agent as a model calling
  tools in a loop until the task is complete: [LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents).

## Recommendation agents

RecMind uses an LLM as an autonomous recommendation agent with planning, memory,
and tools. It demonstrates that LLMs can contribute language understanding and
high-level planning around recommender components. Our scope is narrower: the LLM
does not rank food in the orchestration study. That controlled boundary makes it
possible to measure workflow failures separately from recommendation quality.

- Wang et al. (2024), [RecMind: Large Language Model Powered Agent For Recommendation](https://aclanthology.org/2024.findings-naacl.271/).

Nutrition-focused LLM work commonly lets a model generate or retrieve meal
recommendations. These studies motivate a later recommendation-quality comparison,
but they do not remove the need for hard constraint enforcement.

- Khamesian et al. (2025), [NutriGen: Personalized Meal Plan Generator Leveraging Large Language Models](https://arxiv.org/abs/2502.20601).
- Wang et al. (2026), [An LLM-RAG Approach for Healthy Eating Index-Informed Personalized Food Recommendations](https://arxiv.org/abs/2605.15213).

## Tool-use and policy evaluation

General function-calling accuracy is not enough. Real agents must maintain state,
handle insufficient information, follow domain policies, and produce the correct
environment state.

- Yao et al. (2024), [$\tau$-bench](https://arxiv.org/abs/2406.12045), evaluates
  tool-agent-user interaction and policy following using final database state.
- Lu et al. (2024), [ToolSandbox](https://arxiv.org/abs/2408.04682), highlights
  state dependency, canonicalization, and insufficient-information cases.
- Berkeley's [Function Calling Leaderboard](https://gorilla.cs.berkeley.edu/leaderboard)
  evaluates correct tools and arguments, multi-turn behavior, relevance, and
  hallucinated calls.

Our trace-based metrics follow the same principle: evaluate the executed persona,
tool order, Knapsack action, and final plan state rather than grading prose alone.

## Clarification is a first-class capability

Ambiguous and underspecified requests should trigger information gathering rather
than an irreversible guess. Clarification research reports that LLMs struggle to
decide when to ask and that uncertainty-aware clarification can improve task
success.

- Testoni and Fernández (2024), [Asking the Right Question at the Right Time](https://aclanthology.org/2024.eacl-long.16/).
- Zhang and Choi (2025), [Clarify When Necessary](https://aclanthology.org/2025.findings-naacl.306/).

This directly matches our empirical failure: both tested models achieved 0%
clarification success on unknown, missing, and ambiguous persona requests.

## Why prompt-only safety is insufficient

AgentDojo shows that tool-using agents can violate security properties, while
CaMeL argues for a protective layer around the model that separates trusted
control flow from model-processed data and enforces capabilities at runtime.

- Debenedetti et al. (2024), [AgentDojo](https://arxiv.org/abs/2406.13352).
- Debenedetti et al. (2025), [Defeating Prompt Injections by Design](https://arxiv.org/abs/2503.18813).

Our proposed gate is smaller than CaMeL and is not claimed to provide its formal
security guarantees. It adopts the relevant architectural principle: persona
identity binding is enforced by deterministic code, not delegated to prompt
compliance.

## Connection to the ADF paper

The ADF study finds that known exact procedures should remain deterministic and
that LLM agents should delegate exact work to tools. Our system applies this idea
to a recommendation workflow: language interpretation remains model-driven,
while identity resolution, Knapsack selection, validation, and response
rendering are deterministic.

- Garimella, Srivastava, and Sheth (2026), [Doing Less with More](https://arxiv.org/abs/2610.23921).

## MCP and LangChain

MCP standardizes discovery and invocation across tool providers. It is valuable
when the same tools must be reused by several AI hosts or moved across process and
network boundaries. The current tools are local to one controlled benchmark, so
native function calling avoids adding a transport variable.

- [Official Model Context Protocol specification](https://modelcontextprotocol.io/specification/).
- [LangChain MCPAdapter documentation](https://docs.langchain.com/oss/python/langchain/mcp).

LangChain supplies a reusable harness and middleware. Our explicit loop is short,
auditable, and records exactly the traces being evaluated. Replacing it with
LangChain would be an engineering variant, not evidence of greater autonomy or
novelty. An MCP/LangChain mirror can be added later to test portability and
framework overhead while preserving the native baseline.

## Bounded novelty claim

The novelty is **not** a new Knapsack algorithm, a new LLM, or the use of MCP.
The contribution is a controlled evaluation and architecture for a health-adjacent
recommendation workflow:

1. hold the deterministic recommender and catalog fixed;
2. isolate natural-language routing and tool orchestration;
3. separate agent compliance from system-level safety;
4. enforce a deterministic persona capability gate and trusted response renderer;
5. compare prompt-only, identity-gated, and no-LLM systems on the same valid, restriction-override,
   missing, unknown, and ambiguous requests across multiple local models; and
6. measure exact plan fidelity, clarification, unsafe execution, failures, and
   latency without an LLM judge; and
7. compare Knapsack with direct LLM meal selection on the same six profiles,
   role-eligible catalog, and post-hoc Beacon evaluators, separating hard
   violations from nutrition fit and overall quality.

This is a defensible semester-scale contribution. A conference-strength claim
would require more personas and linguistic variants, repeated trials, stronger
and more diverse models, statistical analysis, a constrained hybrid-reranking
condition, and evaluation on an additional group-recommendation setting.

