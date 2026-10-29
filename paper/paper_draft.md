# Deterministic, LLM-Only, and Policy-Gated Agentic Meal Recommendation

**Sai Teja Paladi**  
CSE 798 Independent Study  
Working paper draft — October 2026

## Abstract

Large language models can translate natural-language requests into tool calls,
but delegating the complete recommendation process to a model makes it difficult
to distinguish language-understanding errors from recommendation errors. This
paper studies a narrower hybrid architecture for meal recommendation. A language
model interprets a request and orchestrates profile and recommendation tools,
while the existing BEACON Knapsack method remains the only component that selects
food. We first compare direct Knapsack execution with an agentic path over six
fictional personas. The agent reproduces all six deterministic plans with 100%
exact plan fidelity and required tool-sequence compliance, but increases mean
latency from 202.4 ms to 5706.4 ms. We then evaluate prompt-only orchestration on
30 fixed requests covering exact names, paraphrases, first names, adversarial
instructions, and unclear personas. Results across five local models show that
stronger tool use does not guarantee safe clarification: the strongest model
passes 22/30 cases but runs Knapsack on all six unclear requests. We introduce a
deterministic policy gate that resolves and authorizes one persona before model
execution, locks identity-dependent tool arguments, clarifies unclear identity,
and renders verified results from application state. Across 150 matched
model-request pairs per architecture, complete-case passes increase from 49/150
to 73/150, unclear-request success increases from 6/30 to 30/30, unsafe Knapsack
executions fall from 10 to zero, and mean latency decreases by 44.9%. Valid
recommendation workflows remain unchanged at 43/120. The result is therefore a
system-level safety and efficiency improvement, not an improvement in the
underlying models. Finally, we compare Knapsack with direct LLM meal selection
from the same role-eligible catalog. Knapsack produces six of six safe plans
with mean Beacon quality 0.860 in 183.5 ms. Granite produces six safe plans but
lower quality (0.679), lower nutrition fit, repeated foods, and 4.34 s latency.
Llama produces only three safe plans, makes four dietary violations, and scores
0.453 quality in 4.04 s. The combined results support a division of labor in
which deterministic components retain constraint-sensitive selection and
authorization while models handle language-dependent interaction.

**Keywords:** LLM agents, tool use, meal recommendation, deterministic
optimization, policy enforcement, clarification

## 1. Introduction

Meal recommendation combines two different kinds of work. Natural-language
requests may be incomplete, ambiguous, or adversarial, while profile retrieval,
constraint enforcement, and optimization should be reproducible. An LLM can be
useful for the first kind of work, but it is not automatically the appropriate
component for the second. Garimella, Srivastava, and Sheth show this distinction
clearly for exact arithmetic: deterministic implementations achieve perfect
accuracy with far lower latency than LLM and agentic alternatives [3]. Their
architectural decision framework motivates using a model only where language
understanding is useful and retaining deterministic procedures for exact work.

This paper applies that principle to the BEACON meal-recommendation setting.
BEACON studies the tradeoff between nutrition and convenience for configurable,
long-horizon meal recommendations [11, 12]. We do not replace or modify its
Knapsack recommender. Instead, we investigate whether an LLM can reliably
orchestrate the workflow around it and what happens when the user's persona is
missing, unknown, or ambiguous.

The study asks three research questions:

- **RQ1:** Can an LLM-orchestrated workflow reproduce the exact output of direct
  deterministic Knapsack execution?
- **RQ2:** How robust is prompt-only orchestration across natural-language,
  adversarial, missing, unknown, and ambiguous-persona requests?
- **RQ3:** Can a deterministic identity and authorization gate improve
  clarification safety without changing the recommender?
- **RQ4:** How do direct LLM-selected meal plans compare with deterministic
  Knapsack plans on constraint adherence, quality, nutrition fit, variety, and
  latency?

The paper makes three bounded contributions:

1. a controlled separation between language-model orchestration and
   deterministic meal selection in the BEACON system;
2. a policy-gated hybrid architecture that resolves and authorizes a persona
   outside the model, constrains identity-dependent tool calls, and renders
   verified results without a final generative step; and
3. a trace-based, five-model evaluation that measures exact plan fidelity,
   tool order, clarification, unsafe execution, failures, and latency without an
   LLM judge; and
4. a same-persona, same-catalog comparison between deterministic Knapsack and
   two local LLM-only selectors, scored after generation by the same Beacon
   evaluators.

This is not a claim of a new optimization algorithm, a new language model, or a
clinically validated recommender. It is a controlled systems study of agentic
orchestration around an existing deterministic recommender.

## 2. Related Work

### 2.1 Reasoning, acting, and recommendation agents

ReAct formalizes an agent pattern in which a language model interleaves
reasoning, actions, and observations from an external environment [1]. Our
implementation follows the observable part of this pattern: the model receives
tool schemas, chooses tool names and arguments, observes structured results, and
decides whether to call another tool or stop. The presence of a particular agent
framework is not what makes this loop agentic.

RecMind applies an autonomous LLM agent to recommendation using planning,
personalized memory, world knowledge, and tools [2]. It demonstrates that LLMs
can add flexible language understanding and planning to recommendation tasks.
Our study asks a different and narrower question. The LLM does not rank meals;
it must correctly invoke an existing recommender. This boundary allows an
orchestration failure to be separated from a meal-selection failure.

### 2.2 Choosing between deterministic and agentic computation

*Doing Less with More* compares native functions, service architectures, direct
LLM responses, and tool-using agents on 1,000 exact expressions [3]. Its central
lesson is not that agents are universally ineffective, but that architecture
should follow task properties. Exact known procedures should remain
deterministic, while models can be reserved for linguistic or uncertain steps.
Our architecture transfers this idea from arithmetic to meal-agent workflow
control: Knapsack selection and authorization remain deterministic; request
interpretation and valid tool sequencing remain model-driven.

### 2.3 Evaluating tool-using agents

Tool-use evaluation requires more than judging final prose. τ-bench evaluates
tool-agent-user interaction using domain policies and final environment state
[4]. ToolSandbox emphasizes state dependencies, canonicalization, and
insufficient-information cases [5]. The Berkeley Function-Calling Leaderboard
also evaluates tool selection, arguments, multi-turn execution, and irrelevant
or hallucinated calls [6]. Following this line of work, our evaluator checks the
executed persona, tool order, Knapsack action, and exact returned plan rather
than using an LLM to rate the response text.

### 2.4 Clarification and runtime policy enforcement

Clarification is a separate capability from tool invocation. Testoni and
Fernández show that model uncertainty does not necessarily match human
clarification behavior [7]. Zhang and Choi likewise frame deciding when to ask
as an explicit stage in ambiguity resolution [8]. These findings motivate
treating missing or ambiguous identity as an observable test condition rather
than assuming that a system prompt will reliably produce a question.

AgentDojo shows that tool-using agents may fail tasks and security properties
even without or under prompt-injection attacks [9]. CaMeL proposes placing a
protective system layer around the model and enforcing capabilities through
explicit control and data flows [10]. Our policy gate is substantially smaller
and does not inherit CaMeL's formal guarantees. It adopts the relevant design
principle: a security-relevant authorization decision should be enforced by the
application rather than delegated solely to prompt compliance.

### 2.5 BEACON and meal recommendation

BEACON formulates meal planning as a combination problem involving food roles,
user constraints, convenience, nutrition, and longer-term considerations
[11, 12]. Its prototype includes deterministic recommendation methods and
quality measures. Our study reuses its personas, local food sources, Knapsack
implementation, and evaluators. We hold these components fixed so the experiment
measures orchestration rather than introducing a competing meal algorithm.

### 2.6 MCP and LangChain

The Model Context Protocol standardizes how AI applications discover and invoke
external tools and resources [13]. LangChain provides an agent harness that can
implement a model-tool loop [14]. Neither changes the scientific distinction
between model-controlled orchestration and deterministic selection. The present
benchmark therefore uses a small native OpenAI-compatible function-calling loop,
which makes every request, response, and tool trace directly auditable. An MCP
or LangChain implementation would be a useful portability or framework-overhead
comparison, but it is not the novelty claimed here.

## 3. System Design

### 3.1 Fixed recommendation component

For a stored persona (p), the BEACON Knapsack implementation produces a
one-day plan:

\[
K(p, C, d) \rightarrow M,
\]

where (C) is the fixed local catalog, (d) is the fixed planning date, and
(M) contains breakfast, lunch, and dinner role-item assignments. The same
persona, catalog, date, and backend version are used in all conditions.

The language model never supplies meal IDs to Knapsack and never replaces the
selected plan. Consequently, if two conditions successfully execute Knapsack
for the same persona, their expected role-item assignments are identical.

### 3.2 Agent tools

The agent receives three logical tools:

| Tool | Purpose | State effect |
| --- | --- | --- |
| `list_personas()` | Return stored persona identifiers and names. | Read only |
| `get_persona(persona_id)` | Retrieve one stored profile. | Records retrieved identity |
| `run_knapsack_for_persona(persona_id)` | Execute BEACON Knapsack. | Produces the meal plan |

For valid requests, the required trajectory is:

```text
user request
    → model calls list_personas
    → model calls get_persona for the intended persona
    → model calls run_knapsack_for_persona for the same persona
    → verified deterministic plan
```

The model genuinely chooses each tool and its arguments. A wrong tool, wrong
persona, wrong order, missing call, or repeated execution is preserved in the
trace and scored as a failure.

### 3.3 Prompt-only architecture

In the prompt-only condition, the system prompt tells the model to identify the
persona, retrieve the profile, preserve stored restrictions, ask for
clarification when necessary, and invoke Knapsack. These instructions are not
enforced outside the model. The model can therefore choose an unrelated persona,
skip a step, provide the full name where an internal identifier is required, or
run Knapsack despite insufficient information.

### 3.4 Policy-gated architecture

The proposed architecture adds four deterministic controls:

1. **Identity resolution.** Before model execution, application code performs a
   case- and punctuation-insensitive match against one explicit full name or
   unique first name in the stored persona set.
2. **Safe clarification.** Missing, unknown, or multiple persona matches return
   a deterministic clarification. The model and identity-dependent tools are
   not called.
3. **Capability restriction.** For a resolved request, `get_persona` and
   `run_knapsack_for_persona` are locked to the authorized identifier. Knapsack
   also requires the list and matching-profile steps to have succeeded.
4. **Trusted rendering.** After successful Knapsack execution, the application
   returns a short confirmation from trusted state. It does not ask the model to
   restate nutrition facts or invent an explanation.

This gate does not choose meals and does not complete the valid tool sequence
for the model. It converts incorrect model actions into explicit failures while
preventing them from becoming wrong-person recommendations.

## 4. Experimental Method

### 4.1 Experiment 1: direct versus agentic execution

Experiment 1 tests RQ1 using the six fictional BEACON personas. The direct
condition receives a selected persona identifier and invokes Knapsack. The
agentic condition receives a natural-language request, uses hosted
`openai/gpt-oss-20b` through Groq at temperature zero, and must complete the three-tool
trajectory. Both conditions use the same backend, catalog, fixed date, and
reference plans.

The metrics are requested-role coverage, exact role-item fidelity to direct
Knapsack, required tool-sequence compliance, BEACON's original goodness,
BEACON's newer quality score, post-hoc nutrition-goal fit, failures, retries,
and end-to-end latency. Nutrition fit is evaluated after generation; the tested
Knapsack implementation does not optimize the numeric calorie, carbohydrate,
protein, and fiber targets directly.

### 4.2 Experiment 2: request robustness

Experiment 2 tests RQ2 and RQ3 with 30 fixed requests over the same six stored
personas. Twenty-four requests require recommendation: six each use an exact
full name, a paraphrase, a unique first name, or an instruction to ignore saved
restrictions. Six requests require clarification because identity is unknown,
missing, or ambiguous.

Five local Ollama models are evaluated:

- `llama3.2:1b`;
- `llama3.2:3b`;
- `phi4-mini:3.8b`;
- `qwen3.5:4b`; and
- `granite4:3b`.

Each model receives every request in both the prompt-only and policy-gated
architectures, producing 300 case-level executions. Runs are sequential to avoid
local memory contention. Temperature is zero, the turn limit is eight, and the
same tool schemas, backend, reference plans, and scoring rules are used.

### 4.3 Experiment 3: deterministic versus LLM-only selection

Experiment 3 tests RQ4 using the same six personas and local Beacon catalog.
The deterministic condition runs Knapsack. In each LLM-only condition, the
model receives the stored profile and all 124 unique candidates eligible for
the requested main-course, side, or beverage roles (145 role memberships) in
a compact representation containing candidate ID, name, role, dietary flags,
and available calories, carbohydrates, protein, and fiber. The LLM selects the
nine catalog items directly. It cannot call Knapsack or another recommendation
tool, and candidates are not pre-filtered for the persona's dietary conditions.

To measure meal choice rather than malformed ID copying, Ollama structured
output constrains each field to an ID belonging to the requested role and
catalog. This schema performs no ranking and applies no persona-specific dietary
filter. `granite4:3b` and `llama3.2:3b` each make one call per persona at
temperature zero. After selection, deterministic validation checks stored
dietary conditions, and the same Beacon evaluators measure goodness, overall
quality, nutrition fit, repeated foods, exact Knapsack match, tokens, and
latency.

### 4.4 Scoring

A valid request passes only if it:

1. retrieves the intended profile;
2. invokes Knapsack exactly once for that persona;
3. follows `list → profile → Knapsack`; and
4. exactly matches the direct Knapsack role-item assignments.

An unclear request passes only if it returns a usable clarification and does not
run Knapsack. We separately count unsafe Knapsack executions, policy-blocked
calls, API or loop failures, failed tools, and wall-clock latency. No generated
text is graded for recommendation quality by another model.

An LLM-only plan is safe and valid only if it fills every requested meal role
with a catalog member and violates none of the stored diabetes, vegetarian,
vegan, or gluten-free conditions. Quality metrics are computed after generation
and do not influence the model's selection.

### 4.5 Reproducibility

The benchmark records the dataset hash, prompt hash, source commit, hashes of
the benchmark and policy-gate implementations, model, temperature, complete tool
trace, application errors, and latency. All profiles are fictional and all food
sources are local to the compatible BEACON checkout.

## 5. Results

### 5.1 Direct versus agentic fidelity

| Condition | Completed | Role coverage | Exact fidelity | Required sequence | Goodness | BEACON quality | Nutrition fit | Mean latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct Knapsack | 6/6 | 100% | 100% | N/A | 1.000 | 0.860 | 0.549 | 202.4 ms |
| Agentic Knapsack | 6/6 | 100% | 100% | 100% | 1.000 | 0.860 | 0.549 | 5706.4 ms |

The agent successfully reproduces the deterministic output for all six
personas, answering RQ1 positively for this small controlled set. Meal-quality
metrics are identical because the same Knapsack method selects the food. The
agentic path is approximately 28 times slower when provider retry waits are
included. Excluding 23.8 seconds of recorded rate-limit waits, its mean latency
is 1747.2 ms, still about 8.6 times the direct baseline.

### 5.2 Prompt-only versus policy-gated robustness

| Model | Architecture | Overall | Valid requests | Unclear requests | Unsafe executions | Mean latency |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Granite 4 3B | Prompt-only | 22/30 | 22/24 | 0/6 | 6 | 9815.1 ms |
| Granite 4 3B | Policy-gated | **28/30** | 22/24 | **6/6** | **0** | **3154.7 ms** |
| Llama 3.2 1B | Prompt-only | 0/30 | 0/24 | 0/6 | 0 | 3596.2 ms |
| Llama 3.2 1B | Policy-gated | **6/30** | 0/24 | **6/6** | 0 | **2150.2 ms** |
| Llama 3.2 3B | Prompt-only | 5/30 | 5/24 | 0/6 | 3 | 3868.7 ms |
| Llama 3.2 3B | Policy-gated | **11/30** | 5/24 | **6/6** | **0** | **2809.4 ms** |
| Phi-4 Mini 3.8B | Prompt-only | 6/30 | 0/24 | 6/6 | 0 | **1992.8 ms** |
| Phi-4 Mini 3.8B | Policy-gated | 6/30 | 0/24 | 6/6 | 0 | 2001.4 ms |
| Qwen 3.5 4B | Prompt-only | 16/30 | 16/24 | 0/6 | 1 | 15351.0 ms |
| Qwen 3.5 4B | Policy-gated | **22/30** | 16/24 | **6/6** | **0** | **8953.8 ms** |

Aggregating the matched runs gives the following result:

| Measure | Prompt-only | Policy-gated |
| --- | ---: | ---: |
| Complete-case passes | 49/150 | **73/150** |
| Valid workflow passes | 43/120 | 43/120 |
| Unclear-request passes | 6/30 | **30/30** |
| Unsafe unclear-case Knapsack executions | 10 | **0** |
| Mean latency per case | 6924.8 ms | **3813.9 ms** |

The policy gate improves all 24 unclear cases that were not already complete
passes and introduces no matched pass-to-fail regressions. The 44.9% mean
latency reduction comes from bypassing model inference for unclear identity and
omitting an unnecessary final model turn after verified Knapsack execution.

### 5.3 Deterministic versus LLM-only selection

| Selector | Safe plans | Hard violations | Exact Knapsack matches | Goodness | Beacon quality | Nutrition fit | Repeated foods | Latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Beacon Knapsack | **6/6** | **0** | 6/6 reference | **1.000** | **0.860** | 0.549 | **0.0** | **183.5 ms** |
| Granite 4 3B LLM-only | **6/6** | **0** | 0/6 | **1.000** | 0.679 | 0.479 | 2.0 | 4338.9 ms |
| Llama 3.2 3B LLM-only | 3/6 | 4 | 0/6 | 0.981 | 0.453 | **0.563** | **0.0** | 4035.3 ms |

Granite returns six dietary-adherent plans, but its mean Beacon quality is 0.181
below Knapsack, nutrition fit is lower, and it repeats two foods per plan on
average. Llama avoids repeated foods and slightly exceeds Knapsack's mean
nutrition fit, but it violates stored dietary conditions for Jessica, Becca,
and Dylan. The four violations are two non-low-sugar choices for a persona with
diabetes and one meat-containing choice for each of two vegetarians. Beacon
assigns zero overall quality to those unsafe plans, reducing Llama's mean
quality to 0.453.

Neither model exactly reproduces a Knapsack plan. This demonstrates that the
models are genuinely selecting different meals; exact disagreement alone is
not an error. The safety and quality metrics show why the difference matters.
Both LLMs are more than 20 times slower than direct Knapsack and consume about
12,900 prompt-plus-completion tokens across six personas, whereas Knapsack uses
no model tokens.

### 5.4 Model capability versus architecture safety

The valid-workflow total is exactly 43/120 in both architectures. This is the
most important interpretation boundary in the study: the gate does not improve
the model's ability to select tools. Granite and Qwen remain substantially more
capable than the smaller models on valid trajectories. The gate instead changes
what the system permits when the model is wrong or the request is incomplete.

Phi-4 Mini illustrates the distinction. It safely clarifies all six unclear
requests even without the gate but completes none of the 24 valid workflows.
Granite illustrates the opposite failure: it completes 22/24 valid workflows
but runs Knapsack on all six unclear prompt-only requests. General tool-use
capability and safe clarification are therefore empirically separable.

## 6. Discussion

### 6.1 Answering the research questions

**RQ1:** The agentic path reproduces all six direct Knapsack plans in the
initial experiment, showing that successful orchestration can preserve a fixed
deterministic recommender. It adds substantial latency and does not improve meal
quality.

**RQ2:** Prompt-only robustness varies widely by model. No tested model combines
high valid-workflow completion with consistently safe unclear-persona handling.
The strongest prompt-only model completes 22/24 valid cases but executes the
recommender in all six cases where clarification is required.

**RQ3:** The deterministic gate produces complete safe clarification for all 30
unclear model-request pairs, eliminates ten unsafe executions, and reduces mean
latency without changing valid-workflow performance. It improves the system,
not the underlying models.

**RQ4:** Direct LLM selection does not outperform Knapsack in this pilot.
Granite preserves dietary constraints but loses overall quality, nutrition fit,
and variety. Llama improves the isolated nutrition-fit mean but violates hard
conditions in half of the personas. Knapsack is faster, token-free, safe on all
six cases, and has the highest overall Beacon quality.

### 6.2 What is novel

The novelty is the combination of a task-specific architecture and controlled
evaluation:

- it isolates natural-language orchestration from deterministic meal selection;
- it converts persona resolution into an explicit application-level capability
  decision instead of relying only on a system prompt;
- it evaluates the same agent with and without that gate across five local
  models and identical requests; and
- it scores executed state—identity, tool order, Knapsack action, and exact plan
  fidelity—while separately reporting safety and model capability; and
- it compares deterministic and direct LLM selection on the same profiles,
  catalog, roles, and post-hoc evaluators instead of comparing systems on
  incompatible inputs.

The work does not claim that deterministic authorization is itself a new idea.
Its contribution is applying and measuring that principle in a reproducible
BEACON meal-agent workflow, exposing a concrete tradeoff that a final-answer
accuracy metric would hide: a model can be good at valid tool trajectories and
simultaneously unsafe when identity is unclear.

### 6.3 Architecture lesson from LLM-only selection

The new recommendation-source experiment strengthens the architecture argument.
The LLM-only selectors are not merely slower alternatives that produce the same
plans. They make different tradeoffs: Granite repeatedly chooses foods despite
being safe, while Llama obtains a favorable numeric nutrition-fit mean partly
through plans that violate stored dietary conditions. A single aggregate metric
would hide both failures.

The result supports a hybrid design in which deterministic code first enforces
hard constraints and produces feasible candidates. An LLM may still add value
by reranking that bounded set using soft preferences or by explaining tradeoffs.
This is different from allowing the model to select from the unrestricted
catalog and hoping a prompt will preserve every condition.

The earlier six-case synthetic pilot in the broader project used different
data and a simplified rule engine. Its numbers remain excluded from the Beacon
tables rather than being pooled with the controlled comparison reported here.

## 7. Limitations and Ethical Scope

The evaluation uses six fictional personas and 30 handcrafted requests. Exact
first-name matching is deliberately conservative and does not resolve typos,
nicknames, pronouns, or conversational identity. The study uses one local
machine and one run per model-request pair at temperature zero; it does not
estimate variance across sampling, hardware, or model versions. The models are
small local models, so results should not be generalized to frontier hosted
systems.

The LLM-only experiment uses role- and catalog-constrained JSON generation. It
therefore measures meal choice after eliminating malformed role/ID output; it
does not measure fully unconstrained generation. It does not filter candidates
by persona, so the observed dietary violations remain model decisions. Only two
models are included in this recommendation-source comparison.

Meal plans are evaluated using existing BEACON metrics and deterministic
fidelity. The study does not establish that plans are clinically appropriate,
that users will follow them, or that the policy gate provides complete security.
Nutrition-goal fit is post-hoc and must not be described as an optimized
constraint. No real personal or protected health information is used.

The aggregate 49/150 and 73/150 observations contain repeated prompts across
models and should not be treated as 150 independent human samples. The current
result is a controlled systems comparison, not a user study or clinical trial.

## 8. Next Experiment: Constrained Hybrid Reranking

The next study should add a hybrid selection condition while retaining the two
completed baselines. It should hold personas, catalog, candidate visibility,
and evaluation metrics fixed and compare:

1. **Deterministic Knapsack:** the existing reference selector;
2. **LLM-only selector:** the completed direct-selection condition;
3. **Constrained hybrid reranker:** deterministic code produces several feasible
   candidate plans, the LLM reranks them for stated soft preferences, and a
   deterministic validator rejects any invalid output.

Run each stochastic condition repeatedly and expand the persona/request set.
Primary measures should include hard-constraint violations, BEACON goodness,
quality and nutrition-goal fit, preference satisfaction, exact consistency over
repeated runs, explanation faithfulness, latency, and token cost. This three-way
experiment would answer whether language-model judgment adds recommendation
value. It must remain separate from the orchestration experiment so a ranking
change is not confused with a routing failure.

## 9. Conclusion

This study demonstrates that an LLM can correctly orchestrate an existing
deterministic meal recommender, but success on clear requests does not ensure
safe behavior when identity is insufficient. Prompt-only agents either fail
valid workflows, fail clarification, or both. A small deterministic policy gate
eliminates observed wrong-person Knapsack executions and reduces latency while
preserving the models' valid-request performance. The main lesson is a division
of responsibility. The direct-selection comparison reinforces this conclusion:
one LLM sacrifices quality and variety while the other violates stored dietary
conditions despite a favorable nutrition-fit mean. Use the model for
language-dependent orchestration and bounded soft-preference ranking; retain
constraint-sensitive recommendation and authorization decisions in inspectable
deterministic components; and evaluate both the trajectory and the resulting
state.

## References

[1] S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan, and Y. Cao.
“[ReAct: Synergizing Reasoning and Acting in Language Models](https://openreview.net/forum?id=WE_vluYUL-X).” *International Conference on Learning Representations*, 2023.

[2] Y. Wang, Z. Jiang, Z. Chen, F. Yang, Y. Zhou, E. Cho, X. Fan, Y. Lu,
X. Huang, and Y. Yang. “[RecMind: Large Language Model Powered Agent for Recommendation](https://aclanthology.org/2024.findings-naacl.271/).” *Findings of NAACL*, pp. 4351–4364, 2024. doi:10.18653/v1/2024.findings-naacl.271.

[3] R. Garimella, B. Srivastava, and A. Sheth. “[Doing Less with More: A First-Principles Exploration of the Suitability of Agentic Computing over Alternative Architectural Choices](https://arxiv.org/abs/2610.23921).” 2026.

[4] S. Yao, N. Shinn, P. Razavi, and K. Narasimhan. “[τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains](https://arxiv.org/abs/2406.12045).” 2024.

[5] J. Lu et al. “[ToolSandbox: A Stateful, Conversational, Interactive Evaluation Benchmark for LLM Tool Use Capabilities](https://arxiv.org/abs/2408.04682).” 2024.

[6] S. G. Patil, H. Mao, F. Yan, C. C.-J. Ji, V. Suresh, I. Stoica, and
J. E. Gonzalez. “[The Berkeley Function Calling Leaderboard (BFCL): From Tool Use to Agentic Evaluation of Large Language Models](https://proceedings.mlr.press/v267/patil25a.html).” *Proceedings of the 42nd International Conference on Machine Learning*, pp. 48371–48392, 2025.

[7] A. Testoni and R. Fernández. “[Asking the Right Question at the Right Time: Human and Model Uncertainty Guidance to Ask Clarification Questions](https://aclanthology.org/2024.eacl-long.16/).” *EACL*, pp. 258–275, 2024. doi:10.18653/v1/2024.eacl-long.16.

[8] M. J. Q. Zhang and E. Choi. “[Clarify When Necessary: Resolving Ambiguity Through Interaction with LMs](https://aclanthology.org/2025.findings-naacl.306/).” *Findings of NAACL*, pp. 5541–5558, 2025. doi:10.18653/v1/2025.findings-naacl.306.

[9] E. Debenedetti, J. Zhang, M. Balunović, L. Beurer-Kellner, M. Fischer,
and F. Tramèr. “[AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents](https://arxiv.org/abs/2406.13352).” 2024.

[10] E. Debenedetti et al. “[Defeating Prompt Injections by Design](https://arxiv.org/abs/2503.18813).” 2025.

[11] V. Nagpal, S. L. Valluru, K. Lakkaraju, and B. Srivastava. “[BEACON: Balancing Convenience and Nutrition in Meals With Long-Term Group Recommendations and Reasoning on Multimodal Recipes](https://arxiv.org/abs/2406.13714).” 2024.

[12] V. Nagpal, S. L. Valluru, K. Lakkaraju, N. Gupta, Z. Abdulrahman,
A. Davison, and B. Srivastava. “[A Novel Approach to Balance Convenience and Nutrition in Meals With Long-Term Group Recommendations and Reasoning on Multimodal Recipes and its Implementation in BEACON](https://arxiv.org/abs/2412.17910).” 2024.

[13] Model Context Protocol. “[Specification](https://modelcontextprotocol.io/specification/).” Accessed October 27, 2026.

[14] LangChain. “[Agents](https://docs.langchain.com/oss/python/langchain/agents).” Accessed October 27, 2026.
