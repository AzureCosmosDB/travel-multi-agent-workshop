# Agent Analytics and Optimization — Product Vision

> **Provenance**
> - **Author:** Mark Brown
> - **Original date:** June 9, 2026
> - **Source:** SharePoint (DocumentDB team) — Word document "Agent Analytics and Optimization"
> - **Captured into repo:** July 7, 2026
> - **Status:** Reference artifact. This is the north-star vision for the analytics initiative in this repository. It is preserved verbatim (reformatted to Markdown for fidelity); do not edit the content except to correct transcription errors. Design decisions derived from this vision are tracked separately as ADRs under `analytics/docs/adr/`.

---

## Executive Summary

AI applications are rapidly evolving from single-prompt experiences into complex agentic systems composed of collaborating agents, tools, memories, workflows, and long-running stateful processes.

As organizations deploy agentic applications into production, they need more than debugging tools and execution traces. They need a way to understand how agents behave over time, how memories influence outcomes, how workflows evolve, where costs accumulate, and which patterns drive business value.

More importantly, they need a way to use that intelligence to continuously improve their agent systems.

Agent Analytics and Optimization for Fabric enables organizations to analyze telemetry, state, memory, workflow, evaluation, and business outcome data from agentic systems at enterprise scale and transform those insights into measurable improvements.

The vision is to make Microsoft Fabric the analytical and optimization layer for agentic applications.

Together, Cosmos DB and Fabric provide a complete architecture for agent systems:

- Cosmos DB serves as the operational system of record.
- Fabric serves as the analytical and optimization system of record.

---

## Problem Statement

Current AI observability platforms primarily focus on debugging individual executions.

They answer questions such as:

- Why did this execution fail?
- What prompt was sent?
- Which tool was called?
- How many tokens were consumed?
- What happened during a specific workflow execution?

These capabilities are essential for developers.

However, organizations increasingly need to answer higher-level questions:

- Which agents deliver the highest business value?
- Which workflows produce the best outcomes?
- Which memories improve success rates?
- Which memories are stale or ineffective?
- How does agent behavior evolve over time?
- What is the cost per successful outcome?
- Which workflows should be optimized?
- Which patterns correlate with business success?

Even more importantly:

- How can these insights be used to improve agent behavior?
- Which optimizations should be applied?
- Which optimizations can be automated safely?
- How can agent systems continuously improve over time?

These questions require an analytics and optimization platform rather than a debugging tool.

---

## Vision

Agent Analytics and Optimization for Fabric enables organizations to continuously improve agentic systems through data-driven optimization.

The platform combines operational state from Cosmos DB with enterprise-scale analytics in Fabric to create a continuous learning loop for agent fleets.

```
Agents
   ↓
Operational State
   ↓
Cosmos DB
   ↓
Fabric Analytics
   ↓
Optimization Intelligence
   ↓
Agents
```

This pattern is similar to optimization systems that have been successfully applied for years in recommendation engines, search ranking systems, advertising platforms, and machine learning systems.

Those systems continuously learn from outcomes and improve future decisions.

Agent Analytics and Optimization for Fabric brings the same optimization model to agentic applications.

The goal is not simply to understand how agents behave.

The goal is to help agents become more effective over time.

Organizations should be able to continuously optimize:

- Agent quality
- Workflow efficiency
- Memory effectiveness
- Routing effectiveness
- Tool utilization
- Model selection
- Cost efficiency
- Business outcomes

through a combination of analytics, recommendations, governance, and automation.

---

## Optimization Maturity Model

Agent Analytics and Optimization for Fabric supports a progressive path from observation to autonomous optimization.

### Level 1: Visibility

Organizations gain visibility into agent behavior through dashboards, reports, semantic models, and analytical experiences.

Examples include:

- Agent performance analysis
- Workflow bottleneck identification
- Memory effectiveness analysis
- Cost optimization opportunities
- Quality and evaluation reporting

Humans identify opportunities and implement improvements.

### Level 2: Recommendations

The platform generates recommendations based on observed behavior.

Examples include:

- Routing recommendations
- Memory recommendations
- Cost recommendations
- Evaluation recommendations
- Workflow recommendations

Humans review and approve recommendations before implementation.

### Level 3: Assisted Optimization

The platform automatically generates proposed changes and impact analysis.

Examples include:

- Memory salience adjustments
- Retrieval weighting recommendations
- Routing threshold optimization
- Model selection optimization
- Tool usage optimization

Human reviewers approve or reject changes before deployment.

### Level 4: Autonomous Optimization

For approved optimization domains, the platform can automatically apply and validate improvements.

Initial autonomous optimization scenarios focus on lower-risk domains such as:

- Memory salience tuning
- Memory retention policies
- Retrieval weighting
- Routing thresholds
- Tool selection policies
- Model selection policies

All changes remain measurable, reversible, and auditable.

The platform continuously measures outcomes and validates whether changes improve quality, latency, cost, or business outcomes.

### Level 5: Adaptive Agent Systems

Organizations operate fleets of agents that continuously learn from operational outcomes.

Higher-risk optimizations remain human-governed, while lower-risk optimization domains can be continuously improved through automation.

The result is an ecosystem of agents that becomes more effective, more efficient, and more valuable over time.

---

## Key Principles

### Framework Agnostic

Agent Analytics and Optimization for Fabric provides a framework-agnostic model for agentic systems.

Rather than coupling analytics and optimization to a specific orchestration framework, the platform normalizes telemetry, workflow, memory, evaluation, and agent interaction data into a common analytical model.

Initial integrations focus on:

- LangGraph
- Microsoft Agent Framework
- OpenAI Agents SDK

The platform is designed for extensibility through:

- OpenTelemetry
- OpenInference
- Model Context Protocol (MCP)
- Future framework adapters

Organizations can adopt new frameworks without changing their analytics or optimization architecture.

### Operational State First

Modern agent systems generate far more than telemetry.

They generate persistent operational state including:

- Checkpoints
- Agent state
- Workflow state
- Long-term memory
- Conversation history
- Tool outputs
- Evaluation artifacts
- User context

Agent Analytics and Optimization for Fabric treats this operational state as a first-class analytical asset.

Cosmos DB serves as a foundational operational store for agentic applications and provides rich analytical data through Fabric Mirroring.

Rather than analyzing only what agents do, the platform analyzes what agents know, remember, learn, and persist over time.

### Analytics First

Analytics serves as the foundation for optimization.

The platform is not intended to replace developer observability or debugging tools.

Developer-focused tools are optimized for inspecting traces, prompt executions, and workflow failures.

Agent Analytics and Optimization for Fabric focuses on organizational intelligence, enabling teams to analyze agent behavior across millions of executions, workflows, memories, evaluations, and users.

The platform answers questions such as:

- Which agents deliver the highest business value?
- Which workflows produce the best outcomes?
- Which memories improve success rates?
- Where are cost and latency concentrated?
- How is quality evolving over time?

These insights become the basis for future optimization.

### Human-Governed Optimization

Not all optimization opportunities carry the same level of risk.

The platform distinguishes between optimization domains that are appropriate for autonomous improvement and those that require human oversight.

Lower-risk optimization domains include:

- Memory salience tuning
- Retrieval optimization
- Routing optimization
- Tool selection optimization
- Model selection optimization
- Cost optimization

Higher-risk optimization domains include:

- Prompt modifications
- Workflow redesign
- Agent instruction changes
- Agent capability changes
- Code generation
- Production deployment changes

These higher-risk domains remain human-governed, with Fabric providing recommendations, impact analysis, validation, and approval workflows.

### Open Analytics Schema

The platform is built on an open analytical schema representing the core execution primitives common across agent frameworks.

Core entities include:

- AgentRun
- AgentStep
- AgentTransition
- ToolInvocation
- MemoryEvent
- Checkpoint
- EvaluationResult
- TokenUsage
- UserSession
- WorkflowExecution

By standardizing on these primitives rather than framework-specific objects, the platform provides consistent analytics and optimization across current and future agent ecosystems.

---

## Architecture

### Operational Data Layer

Agent frameworks execute against Cosmos DB as the operational system of record.

Cosmos DB stores:

- Agent checkpoints
- Agent state
- Thread and session history
- Long-term memory
- Memory salience metadata
- Tool outputs
- Evaluation results
- Agent events
- Workflow state

This operational data provides a rich analytical foundation beyond traditional telemetry.

### Analytical and Optimization Layer

Fabric mirrors operational agent data from Cosmos DB into OneLake.

```
Agent Frameworks
  • LangGraph
  • Microsoft Agent Framework
  • OpenAI Agents SDK
  • Custom Frameworks
           ↓
Cosmos DB
  • Checkpoints
  • Agent State
  • Memory
  • Conversations
  • Tool Outputs
  • Evaluations
  • Agent Events
           ↓
Fabric Mirroring
           ↓
        OneLake
           ↓
Open Analytics Schema
           ↓
Analytics & Optimization
           ↓
Recommendations
           ↓
Optimization Actions
           ↓
Agent Systems
```

Additional telemetry from OpenTelemetry and OpenInference can be incorporated to enrich analytical models when available.

### Strategic Integration: Cosmos DB

Cosmos DB provides a unique opportunity to establish a rich analytical and optimization foundation for agentic systems.

Unlike traditional observability platforms that focus exclusively on traces and telemetry, Cosmos DB can persist the operational state of agent workflows.

Examples include:

- Checkpoints
- Agent state transitions
- Long-term memory
- Memory salience
- Conversation history
- Tool outputs
- Evaluation results
- Workflow state

Through Fabric Mirroring, this operational data becomes immediately available for analytics and optimization without requiring custom ETL pipelines.

This enables scenarios that are difficult or impossible to achieve using telemetry alone:

- Memory effectiveness analysis
- Memory lifecycle analytics
- Checkpoint health analysis
- Agent state evolution
- Workflow replay analytics
- Longitudinal behavior analysis
- Optimization policy generation
- Continuous agent improvement

### Agent Memory Toolkit

The Azure Cosmos DB Agent Memory Toolkit provides a reference implementation for durable agent memory built on Cosmos DB.

The toolkit manages both short-term and long-term memory, including conversation history, summaries, facts, user profiles, and other derived memory artifacts. These memory constructs provide rich operational state that can be mirrored into Fabric and analyzed using Agent Analytics and Optimization for Fabric.

This creates a natural foundation for advanced memory intelligence scenarios including:

- Memory effectiveness analysis
- Memory salience optimization
- Memory lifecycle management
- Memory decay analysis
- Memory reuse analysis
- Memory conflict detection
- Memory-driven outcome analysis

As organizations adopt the Agent Memory Toolkit, Fabric becomes the analytical layer that helps them understand not only what agents remember, but which memories contribute most to successful outcomes.

---

## Analytics Pillars

### Pillar 1: Agent Performance Analytics

Metrics include:

- Agent latency
- Success rates
- Failure rates
- Throughput
- Retry behavior
- Queue time
- Workflow duration

Example questions:

- Which agent is the bottleneck?
- Which workflow step causes most failures?
- How has latency changed over time?

### Pillar 2: Agent Collaboration Analytics

Metrics include:

- Agent-to-agent transitions
- Routing frequency
- Routing confidence
- Collaboration patterns
- Cyclic routing
- Handoff success rates

Example questions:

- Which agent pairings are most successful?
- Which routing decisions increase cost?
- Which collaboration patterns produce the best outcomes?

### Pillar 3: Cost Intelligence

Metrics include:

- Token consumption
- Model consumption
- Cost per workflow
- Cost per user
- Cost per agent
- Cost per successful outcome

Example questions:

- Which workflows are most expensive?
- Which agents deliver the highest ROI?
- Which models drive the highest costs?

### Pillar 4: Memory Intelligence

Memory is one of the most valuable and least understood components of agentic systems.

The platform aims to become the industry's leading analytics and optimization platform for agent memory.

Metrics include:

- Memory creation
- Retrieval frequency
- Reuse frequency
- Memory aging
- Memory decay
- Memory salience
- Memory conflicts
- Memory effectiveness

Example questions:

- Which memories are never used?
- Which memories contribute most to successful outcomes?
- What is the effective half-life of memory?
- Which memories should be consolidated or removed?

### Pillar 5: Evaluation Intelligence

Metrics include:

- Correctness
- Groundedness
- Relevance
- Helpfulness
- User satisfaction
- Human review scores
- Automated evaluator scores

Example questions:

- Which agents provide the highest quality responses?
- Has quality regressed after deployment?
- Which workflows perform best?

### Pillar 6: Workflow Intelligence

Metrics include:

- Workflow completion rates
- Abandonment rates
- Workflow duration
- Outcome quality
- Workflow cost
- User success rates

Example questions:

- Which workflows create the most business value?
- Which workflows should be redesigned?
- Which workflows fail most frequently?

---

## Differentiation

### Existing Market

Current AI observability vendors focus primarily on:

- Trace inspection
- Prompt debugging
- Execution monitoring
- Evaluation execution

These capabilities are valuable but primarily execution-centric.

### Fabric Differentiation

Agent Analytics and Optimization for Fabric provides:

- Enterprise-scale analytics
- Historical trend analysis
- Unified lake architecture
- Business intelligence integration
- Cross-framework reporting
- Agent collaboration analytics
- Advanced memory intelligence
- Correlation with enterprise business data
- Operational state analytics powered by Cosmos DB
- Recommendation-driven optimization
- Human-governed optimization workflows
- Progressive autonomous optimization

The platform answers not only:

> "What happened during this execution?"

but also:

> "What should we do next?"

and ultimately:

> "How can agent systems continuously improve over time?"

---

## Long-Term Outcome

The future of agent operations will look increasingly similar to the evolution of recommendation systems, search relevance systems, advertising optimization systems, and machine learning platforms.

These systems continuously learn from outcomes and improve future decisions.

Agent systems will follow the same pattern.

Cosmos DB provides the operational foundation for stateful agent systems.

Fabric provides the intelligence and optimization layer that enables organizations to understand, govern, optimize, and continuously improve those systems.

The ultimate goal is to establish Microsoft Fabric as the platform where agent systems not only report their behavior, but learn from it.

Agent telemetry, memory, workflow state, evaluations, and business outcomes become the foundation for continuous improvement, enabling agents to become more effective, more efficient, and more valuable with every execution.
