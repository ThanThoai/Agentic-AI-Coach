# Usage Metering Design — AI Query Cost System

## Cost Analysis by Feature Type

Not all queries carry equal cost. The three features differ significantly in how many LLM calls they require, how predictable their token consumption is, and how much reasoning complexity is involved.

**Feature 1 — RAG Query** is the lightest workload. Each request triggers one embedding call to convert the question into a vector, one retrieval pass against the vector database, and one LLM generation call with a context window of roughly 1,000 input tokens and 300 output tokens. The total cost per query is stable and predictable — typically in the range of $0.0006 to $0.0008. Because the knowledge base is fixed and retrieval is deterministic, there is no variance between a simple and a complex question at this layer.

**Feature 2 — Workout History Analysis** sits in the middle tier. It requires one LLM call for intent classification, one statistical pre-processing pass over the workout history, and one generation call whose input size scales with the length of the structured summary. A coach asking about a single exercise over 30 days produces a summary of roughly 500 tokens. A coach asking for a full training review across three months of history can push that to 1,500 tokens or more. This variability makes Analysis cost range from approximately $0.0008 to $0.0018 per query — up to three times the cost of a RAG query in the worst case.

**Feature 3 — Agent Session** is the most expensive and the least predictable. Each iteration of the ReAct loop fires one Sonnet-class LLM call. A question requiring only RAG search resolves in two iterations. A multi-step question combining client history analysis with knowledge retrieval typically requires three to four iterations, and the message history grows with each step — meaning later iterations consume more input tokens than earlier ones. A two-iteration session costs roughly $0.004. A four-iteration session costs roughly $0.012. The same question asked on different days can produce different iteration counts depending on how the model reasons through the tool selection. This unbounded nature is the defining challenge of Agent cost management.

```
Feature     Cost Range          Predictability    LLM Calls
─────────────────────────────────────────────────────────────
RAG         $0.0006 – $0.0008   High              1
Analysis    $0.0008 – $0.0018   Medium            2
Agent       $0.0040 – $0.0160   Low               2 – 5+
```

---

## Design Solution — Per-Type Quota System

Because the three features have fundamentally different cost profiles, a single shared query pool would either undercharge for Agent usage or make RAG feel unnecessarily restricted. The solution is to meter each feature type against its own independent quota, so that consumption in one pool has no effect on the others.

Each plan carries three separate counters:

```
quota = {
    "rag"     : { limit: 500,  used: 0,  rollover: 0 },
    "analysis": { limit: 200,  used: 0,  rollover: 0 },
    "agent"   : { limit: 30,   used: 0,  rollover: 0 }
}
```

The ratio between these limits reflects the cost ratio between the features. Agent slots are priced at roughly ten times the cost of a RAG query, which is why the quota is set proportionally lower even within the same plan tier.

---

## Metering Layers

Enforcement runs across three sequential layers, each serving a distinct purpose.

**Layer 1 — Pre-flight Check (Redis)**
Before any LLM call is made, the system reads the relevant quota counter from Redis. This operation takes under one millisecond and costs nothing. If the counter shows the pool is exhausted, the request is rejected immediately and no downstream processing occurs. This layer prevents cost from being incurred on requests that would ultimately be blocked anyway.

```
incoming request → identify feature type
                 → read quota[type].remaining from Redis
                 → remaining > 0 ? proceed : reject with 429
```

**Layer 2 — Execution and Decrement (Application)**
If the pre-flight check passes, the request is processed normally. For RAG and Analysis, a single decrement of one credit occurs after the response is generated. For Agent, the counter is decremented once per iteration as the ReAct loop progresses, not as a lump sum at the end. This per-iteration accounting gives the system visibility into consumption in real time and enables the soft cap mechanism described below.

```
RAG / Analysis : decrement quota[type].used += 1  after response
Agent          : decrement quota["agent"].used += 1  after each iteration
```

**Layer 3 — Persistent Record (PostgreSQL)**
After each decrement, the event is written to a query cost table in the database. Redis holds the live counter for enforcement speed; PostgreSQL holds the authoritative record for billing, auditing, and monthly rollover calculation. If Redis and PostgreSQL diverge due to a failure, PostgreSQL is the source of truth.

```
query_cost_events
  coach_id | feature  | credits_used | timestamp    | request_id
  coach_01 | rag      | 1            | 2026-03-20   | req_abc
  coach_01 | analysis | 1            | 2026-03-20   | req_def
  coach_01 | agent    | 3            | 2026-03-20   | req_ghi  ← 3 iterations
```

---

## Handling Limit Reached

The approach differs depending on which feature type hits its limit, because the consequences of interruption are not equal across features.

**RAG and Analysis — Hard Boundary on Next Request**
Both features complete atomically within a single request. When the quota is exhausted, the boundary is clean: the current request is already complete, and the next request is blocked at the pre-flight layer. The coach receives a structured response indicating which pool is exhausted, how many days remain until reset, and options to top up or upgrade.

```
{
  "error"       : "quota_exhausted",
  "feature"     : "analysis",
  "used"        : 200,
  "limit"       : 200,
  "reset_in_days: 8,
  "options"     : ["top_up", "upgrade"]
}
```

**Agent — Two-Stage Boundary to Avoid Mid-Session Interruption**
Agent is the difficult case. Because a single coach question can span three or four iterations, a hard block at the quota boundary would terminate a reasoning loop mid-execution and return an incomplete response. This is a poor experience that undermines trust in the feature.

The solution is a soft cap at 80% of the remaining Agent quota. When the counter crosses this threshold during an active session, the system stops passing tools to the LLM and appends an instruction to the next message:

```
"You have reached the tool call limit for this session.
 Synthesize a final answer using the information already gathered.
 Do not request additional tool calls."
```

The model completes its response using whatever context has already been retrieved, returning a coherent — if potentially less thorough — answer. The coach is notified inline that the session was shortened due to quota, and the full block applies only to the next Agent request, never to one already in flight.

```
Agent quota: 30 total

Usage 1–23 : normal execution, tools fully available
Usage 24   : soft cap triggers (80% of 30)
             → tools disabled mid-reasoning
             → model synthesizes from current context
             → response delivered with quota warning
Usage 25–30: pre-flight check blocks new Agent requests
             → coach sees upgrade or top-up prompt
```

This two-stage design ensures that a coach who triggers an Agent session with their last available credit always receives a complete response, and that the system never leaves a reasoning loop in an undefined state.