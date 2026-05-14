# Module 04 - Making Memory Intelligent

**[< Adding Memory to our Agents](./Module-03.md)** - **[Observability & Tracing >](./Module-05.md)**

## Introduction

In Module 03, you added basic memory capabilities to your travel assistant. Your agents can now recall user preferences and apply them during searches. However, this memory system is still relatively simple - it stores preferences but doesn't detect contradictions, understand context, or proactively surface relevant information.

In this module, you'll transform your memory system into an intelligent, production-grade component that handles the complexity of real user interactions. You'll implement automatic preference extraction from conversations, detect and resolve conflicts when users change their minds, filter memories based on trip context, and add proactive suggestions that surface preferences users might have forgotten to mention.

By the end of this module, your agents will intelligently manage evolving preferences, catch contradictions before they cause problems, and provide a truly personalized experience that improves with every interaction.

## Learning Objectives and Activities

- Implement automatic preference extraction from user messages using LLM-based analysis
- Build conflict detection to identify contradictory preferences (vegan vs. loves steak)
- Configure auto-summarization to compress long conversations
- Test the complete intelligent memory system end-to-end

## Module Exercises

1. [Activity 1: Understanding Intelligent Memory Patterns](#activity-1-understanding-intelligent-memory-patterns)
2. [Activity 2: Adding Automatic Preference Extraction](#activity-2-adding-automatic-preference-extraction)
3. [Activity 3: Implementing Conflict Detection and Resolution](#activity-3-implementing-conflict-detection-and-resolution)
4. [Activity 4: Configuring Summarization Agent and Tools](#activity-4-configuring-summarization-agent-and-tools)
5. [Activity 5: Test Your Work](#activity-5-test-your-work)

## Activity 1: Understanding Intelligent Memory Patterns

Before implementing advanced memory features, let's understand the key patterns that make memory intelligent.

### The Problem with Simple Memory

In Module 03, you implemented basic memory storage and recall. However, this approach has limitations:

**Manual Storage:**

- Users must explicitly state preferences: "Remember that I'm vegetarian"
- Natural conversational statements are missed: "I don't eat meat"
- Requires users to think about memory management

**No Conflict Detection:**

- System stores conflicting preferences without question
- Example: "I'm vegan" → later "I love steak" → both stored
- Agents receive contradictory instructions

**Context-Blind Recall:**

- Paris hotel preferences pollute Tokyo trip planning
- All memories activated regardless of relevance
- Users get recommendations based on wrong context

**Passive Behavior:**

- System never proactively mentions stored preferences
- Users must remember to specify requirements
- Missed opportunities to use valuable information

### Intelligent Memory Patterns

Production-grade agentic memory systems go beyond simple storage and retrieval. **Intelligent memory patterns** are design approaches that enable agents to manage, reason about, and leverage memories in sophisticated ways that mirror human cognitive processes.

#### What Are Intelligent Memory Patterns?

Intelligent memory patterns are architectural solutions that transform passive memory storage into an active reasoning system. Instead of treating memory as a simple key-value store where preferences are saved and retrieved, these patterns enable agents to:

- **Understand semantic relationships** between memories (complementary vs. contradictory)
- **Evaluate memory relevance** based on current context (destination, trip type, timeframe)
- **Extract implicit information** from natural language without explicit storage commands
- **Reason about memory conflicts** and make autonomous resolution decisions
- **Proactively surface information** that users might not remember to mention
- **Adapt to evolving preferences** by detecting patterns in behavioral changes

These patterns bridge the gap between traditional RAG (static document retrieval) and true agentic intelligence (dynamic, context-aware reasoning).

#### Why Do We Need Intelligent Memory Patterns?

**1. Real Users Don't Explicitly Manage Memory**

In natural conversation, users don't say "Remember that I'm vegetarian." They say things like:

- "I don't eat meat"
- "Any vegan options?"
- "I'm trying to reduce my animal product consumption"

Without intelligent extraction, these implicit preferences are lost. An intelligent system captures the semantic intent behind conversational statements and converts them into structured, actionable memories.

**2. User Preferences Evolve Over Time**

People change their minds. Someone who booked budget hotels for backpacking trips might prefer luxury accommodations for honeymoon travel. Without conflict detection, your system would store both preferences and provide confusing, contradictory recommendations.

Intelligent patterns enable agents to:

- Detect when new preferences conflict with existing ones
- Understand whether changes are permanent shifts or trip-specific contexts
- Ask for clarification when contradictions are severe (dietary restrictions)
- Auto-resolve when changes are logical progressions (budget → moderate price tier)

**3. Not All Memories Are Equally Relevant**

Retrieving all memories for every search creates noise and degrades recommendation quality. If a user visited Barcelona last summer and is now planning a Tokyo trip, Spanish restaurant preferences shouldn't influence Japanese dining recommendations.

Contextual filtering ensures:

- Universal preferences (dietary restrictions, accessibility needs) are always applied
- Destination-specific memories only activate for relevant locations
- Trip type affects recommendation style (business vs. leisure vs. family)
- Seasonal preferences adapt (skiing in winter, beaches in summer)

**4. Users Forget What They've Told You**

After multiple interactions over weeks or months, users may forget they've shared important preferences. A wheelchair user shouldn't have to specify accessibility needs every single time they search for hotels.

Proactive memory patterns enable agents to:

- Surface high-confidence preferences at natural conversation points
- Remind users of requirements they might have forgotten to mention
- Build trust by demonstrating continuity across sessions
- Reduce cognitive load on users by managing preference context

#### What Can We Do with Intelligent Memory Patterns?

**Enable Natural Conversations**

Users can speak naturally without thinking about memory management:

- "I can't handle spicy food" → Agent extracts dietary restriction
- "Last time the hotel was too far from downtown" → Agent learns location preference
- "My kids loved that aquarium" → Agent notes family-friendly activity preference

**Prevent Recommendation Failures**

By detecting conflicts before they cause problems:

- Stop recommending steakhouses to vegetarians after they mention plant-based interest
- Catch accessibility conflicts (wheelchair user + hiking-heavy itinerary)
- Identify price tier mismatches (luxury hotels + budget restaurants)

**Provide Hyper-Personalized Experiences**

Context-aware memory enables:

- Tokyo recommendations that respect dietary restrictions but don't suggest Italian restaurants
- Winter trip suggestions that reflect skiing interest but suppress beach activities
- Business travel that prioritizes efficiency over family-friendly amenities

**Scale to Complex User Profiles**

As users interact more, their memory profile grows. Intelligent patterns ensure:

- Memories remain organized and conflict-free
- Relevant preferences surface at the right time
- Outdated preferences are updated or archived
- High-confidence patterns emerge from repeated behaviors

**Build Trust Through Continuity**

Users feel understood when agents:

- Remember their accessibility needs without being asked
- Apply dietary restrictions automatically across all searches
- Reference past trips to avoid duplicate recommendations
- Proactively suggest options based on established preferences

## Activity 2: Adding Automatic Preference Extraction

**How it works:**

- LLM analyzes every user message for implicit preferences
- Extracts structured data: category, value, salience, memory type
- Stores preferences without explicit "remember this" commands

**Benefits:**

- Natural conversation flow
- Captures implicit preferences
- Higher memory coverage

### Create tool in the mcp server

Navigate to this file **mcp_server/mcp_http_server.py**

Locate this import line **from src.app.services.azure_cosmos_db import**, and add the following imports above it.

```python
import re
from src.app.services.azure_open_ai import get_openai_client
```

Locate the **def recall_memories** tool, and add the following helper and tool after it.

````python
_EXPLICIT_PREFERENCE_PATTERNS = [
    r"\b(i|we)\s+(am|are|have|need|prefer|like|love|hate|avoid|require|want)\b",
    r"\b(i'm|im|we're)\b",
    r"\bmy\s+(preference|preferences|diet|budget|allergy|allergies|restriction|restrictions|requirement|requirements)\b",
    r"\b(no|avoid)\s+(seafood|meat|pork|dairy|gluten|nuts|peanuts|crowds|stairs)\b",
]

_SEARCH_INTENT_PATTERN = re.compile(
    r"\b(find|show|recommend|search|suggest|where should|what should|places?|restaurants?|hotels?|activities?|museums?|attractions?)\b",
    re.IGNORECASE,
)


def _should_skip_preference_llm(message: str) -> bool:
    """Skip preference extraction for plain search requests with no explicit user preference."""
    normalized = message.strip().lower()
    if not normalized:
        return True

    has_search_intent = bool(_SEARCH_INTENT_PATTERN.search(normalized))
    has_explicit_preference = any(
        re.search(pattern, normalized, re.IGNORECASE)
        for pattern in _EXPLICIT_PREFERENCE_PATTERNS
    )

    return has_search_intent and not has_explicit_preference


@mcp.tool()
def extract_preferences_from_message(
        message: str,
        role: str,
        user_id: str,
        tenant_id: str
) -> Dict[str, Any]:
    """
    Extract travel preferences from a user or assistant message using LLM.
    Smart enough to skip greetings, simple yes/no, and other non-preference messages.

    Args:
        message: The message text to analyze
        role: Message role (user/assistant)
        user_id: User identifier (for logging)
        tenant_id: Tenant identifier (for logging)

    Returns:
        Dictionary with:
        - shouldExtract: bool (whether to extract)
        - skipReason: str (reason if skipped)
        - preferences: list of extracted preferences with category, value, text, salience, type
    """
    logger.info(f"🔍 Extracting preferences from {role} message for user {user_id}")

    if _should_skip_preference_llm(message):
        logger.info("⏭️ Skipping preference extraction LLM for plain search request")
        return {
            "shouldExtract": False,
            "skipReason": "Plain search request without explicit new preferences",
            "preferences": []
        }

    try:
        # Load prompty template
        template = load_prompty_template("preference_extraction.prompty")

        # Call LLM
        response_text = call_llm_with_prompt(
            template=template,
            variables={"message": message, "role": role},
            temperature=0.3
        )

        # Parse JSON response
        response_json = json.loads(response_text)

        logger.info(f"✅ Extraction complete: shouldExtract={response_json.get('shouldExtract', False)}")
        return response_json

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        return {
            "shouldExtract": False,
            "skipReason": "LLM response parsing error",
            "preferences": []
        }
    except Exception as e:
        logger.error(f"Error extracting preferences: {e}")
        return {
            "shouldExtract": False,
            "skipReason": f"Error: {str(e)}",
            "preferences": []
        }

def load_prompty_template(filename: str) -> str:
    """Load prompty file content (strips frontmatter, returns system+user sections)"""
    file_path = os.path.join(PROMPT_DIR, filename)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Remove frontmatter (--- ... ---) if present
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    content = parts[2].strip()
            return content
    except FileNotFoundError:
        logger.error(f"Prompty file not found: {file_path}")
        raise


def call_llm_with_prompt(template: str, variables: Dict[str, Any], temperature: float = 0.3) -> str:
    """
    Call Azure OpenAI with a prompt template and variables.

    Args:
        template: Prompt template with {{variable}} placeholders
        variables: Dictionary of variable values to substitute
        temperature: LLM temperature (default 0.3 for structured output)

    Returns:
        LLM response content as string (with markdown code blocks stripped if present)
    """
    client = get_openai_client()

    # Substitute variables in template
    prompt = template
    for key, value in variables.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", str(value))

    response = client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=2000
    )

    content = response.choices[0].message.content

    # Strip markdown code blocks if present (```json ... ``` or ``` ... ```)
    if content.startswith("```"):
        # Remove opening ```json or ```
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        # Remove closing ```
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    return content
````

### Adding tool to Orchestrator Agent

Navigate to the file **src/app/travel_agents.py**.

Locate **orchestrator_tools**, and update the tools with the code below.

```python
orchestrator_tools = filter_tools_by_prefix(all_tools, [
        "create_session", "get_session_context", "append_turn",
        "recall_memories", "extract_preferences_from_message",
        "transfer_to_"  # All transfer tools
    ])
```

## Activity 3: Implementing Conflict Detection and Resolution

**How it works:**

- Before storing new preferences, check for contradictions
- Use LLM to understand semantic conflicts
- Classify conflicts by severity (low, medium, high)
- Auto-resolve low-severity, ask user for high-severity

**Conflict Severity Levels:**

**Low Severity (Auto-Resolve):**

- Preference evolution: "budget hotels" → "moderate hotels"
- Complementary additions: "vegan" + "gluten-free"
- Refinements: "Italian food" → "Northern Italian food"

**Medium Severity (Store with Note):**

- Price tier changes: "budget" → "luxury" (might be trip-specific)
- Style changes: "chain hotels" → "boutique hotels"
- Activity type shifts: "museums" → "outdoor adventures"

**High Severity (Require Confirmation):**

- Dietary contradictions: "vegan" ↔ "loves meat"
- Accessibility conflicts: "wheelchair user" ↔ "hiking enthusiast"
- Direct negations: "loves spicy food" ↔ "can't handle spice"

### Create tools in the mcp server

Navigate to this file **mcp_server/mcp_http_server.py**

We need to first update the following imports.

```python
from src.app.services.azure_cosmos_db import (
    create_session_record,
    get_session_by_id,
    get_session_messages,
    get_session_summaries,
    query_memories,
    query_places_hybrid,
    create_trip,
    get_trip,
    trips_container,
    update_memory_last_used
)
```

Update it with the following imports:

```python
from src.app.services.azure_cosmos_db import (
    create_session_record,
    create_summary,
    get_all_user_memories,
    get_message_by_id,
    get_session_by_id,
    get_session_messages,
    get_session_summaries,
    get_user_summaries,
    query_memories,
    query_places_hybrid,
    create_trip,
    get_trip,
    store_memory,
    supersede_memory,
    trips_container,
    update_memory_last_used
)
```

Locate the **def extract_preferences_from_message** tool, and add the following tools after it.

```python
@mcp.tool()
def resolve_memory_conflicts(
        new_preferences: List[Dict[str, Any]],
        user_id: str,
        tenant_id: str
) -> Dict[str, Any]:
    """
    Resolve conflicts between new preferences and existing memories using LLM.

    Args:
        new_preferences: List of new preferences to check
        user_id: User identifier
        tenant_id: Tenant identifier

    Returns:
        Dictionary with:
        - resolutions: list of resolution decisions for each preference
          - conflict: bool
          - conflictsWith: str (existing memory text)
          - conflictingMemoryId: str
          - severity: none/low/high
          - decision: auto-resolve/require-confirmation
          - strategy: explanation
          - action: store-new/update-existing/store-both/ask-user
    """
    logger.info(f"⚖️  Resolving conflicts for {len(new_preferences)} preferences")

    try:
        # Query existing memories
        existing_memories = get_all_user_memories(
            user_id=user_id,
            tenant_id=tenant_id
        )

        # Format existing memories for LLM
        existing_prefs_text = "\n".join([
            f"- [{mem.get('type')}] {mem.get('text')} (salience: {mem.get('salience')}, id: {mem.get('memoryId')})"
            for mem in existing_memories
        ])

        # Format new preferences for LLM
        new_prefs_text = json.dumps(new_preferences, indent=2)

        # Load prompty template
        template = load_prompty_template("memory_conflict_resolution.prompty")

        # Call LLM
        response_text = call_llm_with_prompt(
            template=template,
            variables={
                "existing_preferences": existing_prefs_text,
                "new_preferences": new_prefs_text
            },
            temperature=0.3
        )

        # Parse JSON response
        response_json = json.loads(response_text)

        # Count severity levels
        high_severity_count = sum(1 for r in response_json.get("resolutions", []) if r.get("severity") == "high")
        low_severity_count = sum(1 for r in response_json.get("resolutions", []) if r.get("severity") == "low")

        logger.info(f"✅ Conflict resolution complete: {high_severity_count} high, {low_severity_count} low severity")

        return response_json

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        return {"resolutions": []}
    except Exception as e:
        logger.error(f"Error resolving conflicts: {e}")
        return {"resolutions": []}


@mcp.tool()
def store_resolved_preferences(
        resolutions: List[Dict[str, Any]],
        user_id: str,
        tenant_id: str,
        justification: str
) -> Dict[str, Any]:
    """
    Store preferences that have been auto-resolved (no user confirmation needed).
    Skip preferences that require user confirmation or are duplicates.

    Args:
        resolutions: List of resolution decisions from resolve_memory_conflicts
        user_id: User identifier
        tenant_id: Tenant identifier
        justification: Source message ID or reasoning

    Returns:
        Dictionary with:
        - stored: list of stored memory IDs
        - skipped: list of preferences that were skipped (duplicates)
        - needsConfirmation: list of preferences requiring user confirmation
        - superseded: list of old memory IDs that were marked as superseded
    """
    logger.info(f"💾 Storing resolved preferences for user {user_id}")

    stored = []
    skipped = []
    needs_confirmation = []
    superseded = []

    try:
        for resolution in resolutions:
            decision = resolution.get("decision")
            action = resolution.get("action")
            new_pref = resolution.get("newPreference", {})
            strategy = resolution.get("strategy")

            if action == "skip" or decision == "skip":
                skipped.append({
                    "preference": new_pref,
                    "reason": resolution.get("strategy", "Duplicate or covered by existing memory")
                })
                logger.info(f"⏭️  Skipping duplicate preference: {new_pref.get('text')}")
                continue

            if decision == "require-confirmation":
                # Skip and add to confirmation list
                needs_confirmation.append({
                    "preference": new_pref,
                    "conflict": resolution.get("conflictsWith"),
                    "strategy": strategy
                })
                logger.info(f"⏸️  Skipping preference (needs confirmation): {new_pref.get('text')}")
                continue

            # Auto-resolve actions
            if action == "store-new":
                # Before storing, build detailed justification
                category = new_pref.get("category", "preference")
                value = new_pref.get("value", "")
                pref_text = new_pref.get("text", "")

                detailed_justification = f"User stated {category} preference: {value} - {pref_text}"
                if strategy:
                    detailed_justification += f" ({strategy})"

                # Store new preference
                memory_id = store_memory(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    memory_type=new_pref.get("type", "declarative"),
                    text=new_pref.get("text"),
                    facets={new_pref.get("category"): {"value": new_pref.get("value")}},
                    salience=new_pref.get("salience", 0.7),
                    justification=detailed_justification
                )
                stored.append(memory_id)
                logger.info(f"✅ Stored new preference: {memory_id}")

            elif action == "update-existing":
                # Build detailed justification before storing
                category = new_pref.get("category", "preference")
                value = new_pref.get("value", "")
                pref_text = new_pref.get("text", "")

                detailed_justification = f"User updated {category} preference: {value} - {pref_text}"
                if strategy:
                    detailed_justification += f" ({strategy})"

                # Mark old as superseded and store new
                old_memory_id = resolution.get("conflictingMemoryId")

                # Store new preference first
                memory_id = store_memory(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    memory_type=new_pref.get("type", "declarative"),
                    text=new_pref.get("text"),
                    facets={new_pref.get("category"): {"value": new_pref.get("value")}},
                    salience=new_pref.get("salience", 0.7),
                    justification=detailed_justification
                )
                stored.append(memory_id)
                logger.info(f"✅ Stored updated preference: {memory_id}")

                # Now supersede the old memory
                if old_memory_id:
                    success = supersede_memory(
                        memory_id=old_memory_id,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        superseded_by=memory_id
                    )
                    if success:
                        superseded.append(old_memory_id)
                        logger.info(f"🔄 Superseded old memory: {old_memory_id} with {memory_id}")
                    else:
                        logger.warning(f"⚠️ Failed to supersede old memory: {old_memory_id}")

            elif action == "store-both":
                # Build detailed justification
                category = new_pref.get("category", "preference")
                value = new_pref.get("value", "")
                pref_text = new_pref.get("text", "")

                detailed_justification = f"User added complementary {category} preference: {value} - {pref_text}"
                if strategy:
                    detailed_justification += f" ({strategy})"

                # Store new preference (old one remains)
                memory_id = store_memory(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    memory_type=new_pref.get("type", "declarative"),
                    text=new_pref.get("text"),
                    facets={new_pref.get("category"): {"value": new_pref.get("value")}},
                    salience=new_pref.get("salience", 0.7),
                    justification=detailed_justification
                )
                stored.append(memory_id)
                logger.info(f"✅ Stored complementary preference: {memory_id}")

        return {
            "stored": stored,
            "skipped": skipped,
            "needsConfirmation": needs_confirmation,
            "superseded": superseded,
            "storedCount": len(stored),
            "skippedCount": len(skipped),
            "confirmationCount": len(needs_confirmation)
        }

    except Exception as e:
        logger.error(f"Error storing preferences: {e}")
        return {
            "stored": stored,
            "skipped": skipped,
            "needsConfirmation": needs_confirmation,
            "superseded": superseded,
            "error": str(e)
        }
```

### Adding tool to Orchestrator Agent

Navigate to the file **src/app/travel_agents.py**

Locate **orchestrator_tools**, and update the tools with the code below.

```python
orchestrator_tools = filter_tools_by_prefix(all_tools, [
        "create_session", "get_session_context", "append_turn",
        "recall_memories", "extract_preferences_from_message", "resolve_memory_conflicts", "store_resolved_preferences",
        "transfer_to_"  # All transfer tools
    ])
```

## Activity 4: Configuring Summarization Agent and Tools

**How it works:**

- Monitors conversation length (triggers at 10+ messages)
- Identifies summarizable message spans (keeps recent 5 messages, summarizes older ones)
- Creates LLM-generated summaries that preserve key decisions and context
- Marks original messages as superseded with TTL for automatic cleanup

**Benefits:**

- Fast agent response times even after 50+ message exchanges
- Maintains context without hitting LLM token limits
- Lower API costs by reducing tokens processed per turn
- Critical information preserved (bookings, preferences, decisions)

### Understanding Auto-Summarization

Long conversations create several challenges:

- **Performance**: Large message histories slow down agent processing
- **Context window limits**: LLMs have token limits that long conversations exceed
- **Cost**: Processing thousands of messages per turn increases API costs
- **Signal-to-noise**: Important decisions get buried in conversational fluff

Auto-summarization solves these by compressing older messages into concise summaries while keeping recent context intact.

**Trigger Logic:**

- Checks message count after each turn
- Triggers at 10 messages, then every 10 messages thereafter (10, 20, 30...)
- Router automatically redirects to Summarizer agent when threshold reached

### Create tools in the MCP server

Navigate to the file **mcp_server/mcp_http_server**

Locate **def transfer_to_dining** tool, and add the following **transfer_to** tool after it.

```python
@mcp.tool()
def transfer_to_summarizer(
        reason: str
) -> str:
    """
    Transfer conversation to the Summarizer agent.

    Use this when:
    - User asks for a recap or summary of the conversation
    - Conversation has become long (12+ turns)
    - User wants to review what's been discussed or planned

    Examples:
    - "Summarize our conversation"
    - "What have we planned so far?"
    - "Give me a recap"

    Args:
        reason: Why you're transferring to this agent

    Returns:
        JSON with goto field for routing
    """

    logger.info(f"🔄 Transfer to Summarizer: {reason}")

    return json.dumps({
        "goto": "summarizer",
        "reason": reason,
        "message": "Transferring to Summarizer to compress and recap our conversation."
    })
```

Locate **def store_resolved_preferences** tool, and add the following tools after it.

```python
# ============================================================================
# 6. Summarization Tools
# ============================================================================

@mcp.tool()
def mark_span_summarized(
        session_id: str,
        tenant_id: str,
        user_id: str,
        summary_text: str,
        span: Dict[str, str],
        supersedes: List[str],
        generate_embedding_flag: bool = True
) -> Dict[str, Any]:
    """
    Atomically create summary and set TTL on source messages.

    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        summary_text: Summary content
        span: Dictionary with fromMessageId and toMessageId
        supersedes: List of message IDs being superseded
        generate_embedding_flag: Whether to generate embedding (default: True)

    Returns:
        Dictionary with summaryId and metadata
    """
    logger.info(f"📝 Creating summary for session: {session_id}")

    # Get the last message being summarized to extract its timestamp
    to_message_id = span.get("toMessageId")
    last_message = get_message_by_id(
        message_id=to_message_id,
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id
    )

    # Extract timestamp or fallback to current time
    if last_message and last_message.get("ts"):
        last_message_ts = last_message.get("ts")
    else:
        from datetime import datetime
        last_message_ts = datetime.utcnow().isoformat() + "Z"
        logger.warning(f"Could not find timestamp for message {to_message_id}, using current time")

    summary_id = create_summary(
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        summary_text=summary_text,
        span=span,
        summary_timestamp=last_message_ts,
        supersedes=supersedes
    )

    return {
        "summaryId": summary_id,
        "supersededCount": len(supersedes),
        "summaryTimestamp": last_message_ts
    }


@mcp.tool()
def get_summarizable_span(
        session_id: str,
        tenant_id: str,
        user_id: str,
        min_messages: int = 20,
        retention_window: int = 10
) -> Dict[str, Any]:
    """
    Return message range suitable for summarization.

    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        min_messages: Minimum messages needed for summarization (default: 20)
        retention_window: Number of recent messages to keep (default: 10)

    Returns:
        Dictionary with span info and messages
    """
    logger.info(f"📊 Finding summarizable span for session: {session_id}")

    # Get all messages (excluding superseded ones)
    messages = get_session_messages(
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        include_superseded=False
    )

    if len(messages) < min_messages:
        return {
            "canSummarize": False,
            "reason": f"Not enough messages (have {len(messages)}, need {min_messages})",
            "messageCount": len(messages)
        }

    # Keep recent messages, summarize older ones
    # Messages are returned in DESC order, so reverse for chronological
    messages_chronological = list(reversed(messages))
    messages_to_summarize = messages_chronological[:-retention_window]

    if not messages_to_summarize:
        return {
            "canSummarize": False,
            "reason": "All messages within retention window",
            "messageCount": len(messages)
        }

    return {
        "canSummarize": True,
        "span": {
            "fromMessageId": messages_to_summarize[0]["messageId"],
            "toMessageId": messages_to_summarize[-1]["messageId"]
        },
        "messageCount": len(messages_to_summarize),
        "totalMessages": len(messages),
        "retentionWindow": retention_window
    }


@mcp.tool()
def get_all_user_summaries(
        user_id: str,
        tenant_id: str
) -> List[Dict[str, Any]]:
    """
    Retrieve all conversation summaries for a user across all sessions.
    Useful when user asks "Show me my past trips" or "What have we discussed before?".

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier

    Returns:
        List of summary objects containing sessionId, text, and createdAt

    """
    logger.info(f"📚 Retrieving all summaries for user: {user_id}")

    summaries = get_user_summaries(
        user_id=user_id,
        tenant_id=tenant_id
    )

    # Return simplified format for agent consumption
    return [
        {
            "summaryId": s.get("summaryId"),
            "sessionId": s.get("sessionId"),
            "text": s.get("text"),
            "createdAt": s.get("createdAt"),
            "span": s.get("span")
        }
        for s in summaries
    ]
```

### Adding Auto-Trigger Logic

Navigate to the file **src/app/travel_agents.py**

#### Step 1: Update imports

At the top of the file with other imports, locate:

```python
from src.app.services.azure_cosmos_db import DATABASE_NAME, checkpoint_container
```

Update the import with this:

```python
from src.app.services.azure_cosmos_db import count_active_messages, DATABASE_NAME, checkpoint_container
```

#### Step 2: Add Summarization Check Function

Locate the **human_node** function. After it, add the following function:

```python
def should_summarize(state: MessagesState, config) -> bool:
    """
    Check if conversation should be summarized based on message count.
    Returns True if there are 10+ messages and no recent summarization.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    try:
        # Get actual count from DB (non-superseded, non-summary messages only)
        actual_count = count_active_messages(
            session_id=thread_id,
            tenant_id=tenant_id,
            user_id=user_id
        )

        # Trigger summarization every 10 messages
        if actual_count >= 20 and actual_count % 20 == 0:
            logger.info(f"🎯 Auto-triggering summarization at {actual_count} messages")
            return True

    except Exception as e:
        logger.error(f"Error checking message count for summarization: {e}")

    return False
```

#### Step 3: Update the Router to Check for Summarization

Locate the **get_active_agent** function, and search for **activeAgent = None**. Add the following code above it.

```python
# **CHECK FOR AUTO-SUMMARIZATION FIRST**
if should_summarize(state, config):
    logger.info("🤖 Auto-routing to summarizer (10+ messages)")
    return "summarizer"
```

#### Step 4: Add Summarizer Global Variables

At the top of the file where agent variables are declared, locate:

```python
# Global agent variables
orchestrator_agent = None
hotel_agent = None
activity_agent = None
dining_agent = None
itinerary_generator_agent = None
```

Add the summarizer agent:

```python
# Global agent variables
orchestrator_agent = None
hotel_agent = None
activity_agent = None
dining_agent = None
itinerary_generator_agent = None
summarizer_agent = None
```

Update the global variables in the **setup_agents()** function.

```python
global orchestrator_agent, hotel_agent, activity_agent, dining_agent
global itinerary_generator_agent
```

Update it to include summarizer:

```python
global orchestrator_agent, hotel_agent, activity_agent, dining_agent
global itinerary_generator_agent, summarizer_agent
```

#### Step 5: Add summarizer tools

In **setup_agent()** function, after the **dining_tools**, add:

```python
summarizer_tools = filter_tools_by_prefix(all_tools, [
        "get_summarizable_span", "mark_span_summarized", "get_session_context",
        "get_all_user_summaries",
        "transfer_to_orchestrator"
    ])
```

#### Step 6: Create Summarizer Agent

Locate **dining_agent = create_react_agent**, add the following code after it:

```python
summarizer_agent = create_react_agent(
    model,
    summarizer_tools,
    state_modifier=load_prompt("summarizer")
)
```

#### Step 7: Add Summarizer Agent Node

Create the summarizer agent node function. Add this after the **call_dining_agent** function:

```python
async def call_summarizer_agent(state: MessagesState, config) -> Command[
    Literal["summarizer", "orchestrator", "human"]]:
    """
    Summarizer agent: Compresses conversation history.
    Auto-triggered every 10 turns.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    logger.info("📝 Summarizer compressing conversation...")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "summarizer_agent")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', thread_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

    response = await summarizer_agent.ainvoke(state, config)
    return Command(update=response, goto="human")
```

#### Step 8: Update the Graph Builder

In the **build_agent_graph()** function, add the summarizer node. It should look like this:

```python
builder = StateGraph(MessagesState)
builder.add_node("orchestrator", call_orchestrator_agent)
builder.add_node("hotel", call_hotel_agent)
builder.add_node("activity", call_activity_agent)
builder.add_node("dining", call_dining_agent)
builder.add_node("itinerary_generator", call_itinerary_generator_agent)
builder.add_node("summarizer", call_summarizer_agent)
builder.add_node("human", human_node)
```

Add orchestrator routing to include summarizer. Locate the below code:

```python
# Orchestrator routing - can route to any specialized agent
builder.add_conditional_edges(
    "orchestrator",
    get_active_agent,
    {
        "hotel": "hotel",
        "activity": "activity",
        "dining": "dining",
        "itinerary_generator": "itinerary_generator",
        "human": "human",  # Wait for user input
        "orchestrator": "orchestrator",  # fallback
    }
)
```

And update it with this:

```python
# Orchestrator routing - can route to any specialized agent
builder.add_conditional_edges(
    "orchestrator",
    get_active_agent,
    {
        "hotel": "hotel",
        "activity": "activity",
        "dining": "dining",
        "itinerary_generator": "itinerary_generator",
        "summarizer": "summarizer",
        "human": "human",  # Wait for user input
        "orchestrator": "orchestrator",  # fallback
    }
)
```

Add summarizer routing. Locate the **checkpointer = CosmosDBSaver**, and add the following code above it:

```python
# Summarizer routing - can only return to orchestrator
builder.add_conditional_edges(
    "summarizer",
    get_active_agent,
    {
        "orchestrator": "orchestrator",
        "summarizer": "summarizer",  # Can stay in summarizer
    }
)
```

#### Understanding the Workflow

When a user continues a conversation past 10 messages:

1. **Detection**: **should_summarize()** checks message count after each turn
2. **Auto-Trigger**: Router returns "summarizer" instead of normal agent
3. **Summarizer Agent**:
   - Calls **get_summarizable_span()** to identify messages 1-5 (keeps 6-10)
   - Calls **recall_memories()** to extract key preferences from conversation
   - Calls **get_session_context()** to retrieve full message history
   - Generates structured summary preserving critical information
   - Calls **mark_span_summarized()** to create summary and mark old messages
4. Resume: Transfers back to orchestrator to continue normal conversation

#### Why Every 10 Messages?

**Too Frequent (every 5 messages)**:

- Summarization overhead slows conversation
- Context too fragmented
- Users notice interruptions

**Too Infrequent (every 25 messages)**:

- Token limits exceeded
- Performance degradation noticeable
- Higher API costs

**Optimal (every 10 messages)**:

- Balances context preservation with performance
- Imperceptible to users
- Manageable token usage

### Updating Agent Prompts

Now that we've added intelligent memory extraction handled by the Orchestrator, we need to update the Orchestrator prompt to use these new tools.

Module 03 used ReAct specialist agents for Hotel, Activity, and Dining. In this module, replace those three specialist implementations with deterministic memory-first service nodes while keeping them as separate LangGraph nodes. This preserves multi-agent orchestration, but removes an extra LLM turn for obvious recommendation requests.

Make these code changes in **src/app/travel_agents.py**:

- Add `re`, `get_all_user_memories`, `query_places_filtered`, and `query_places_hybrid` to the imports.
- Add the memory-first helper block from the completed solution: `_deterministic_specialist_route`, `_latest_user_text`, `_latest_user_message`, `_extract_geo_scope`, `PREFERENCE_TAXONOMY`, `_preference_profile_from_memories`, `_memory_first_recommendations`, and the related ranking/formatting helpers.
- Remove the `hotel_agent`, `activity_agent`, and `dining_agent` globals and their `create_react_agent(...)` calls.
- Keep `orchestrator_agent`, `itinerary_generator_agent`, and `summarizer_agent` as LLM-backed ReAct agents.
- Update `call_hotel_agent`, `call_activity_agent`, and `call_dining_agent` so each calls `_memory_first_recommendations(...)` and then returns to `human`.

The result is still multi-agent: the Orchestrator chooses a graph node, and each specialist node owns its domain response. The performance improvement comes from making the specialist recommendation path memory-first and deterministic instead of asking a second LLM to decide which memory/search tools to call.

Navigate to **src/app/prompts/** folder.

#### Update Orchestrator Prompt

Open **orchestrator.prompty** and **replace the entire contents** with:

```text
---
name: Orchestrator Agent
description: Routes user requests to appropriate specialized agents and extracts preferences
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Orchestrator for a multi-agent travel planning system. Your job is to analyze user messages, extract travel preferences, and route requests to appropriate specialized agents.

# Core Responsibilities (In Order)
1. **Extract and Store Preferences** - Check if the user message contains travel preferences
2. **Route requests** - Use transfer_to_* tools based on user intent
3. **Coordinate agent flow** - Decide which agent handles each request
4. **Handle general conversation** - Greetings, clarifications, thanks
5. **Never plan trips yourself** - Always delegate to specialists

# Step 1: Check for Preferences (ONLY WHEN PRESENT)

Before routing, quickly assess whether the user's message contains explicit travel preferences.

**Call `extract_preferences_from_message` ONLY when the message contains:**
- Dietary statements ("I'm vegan", "gluten-free", "no seafood")
- Accessibility needs ("wheelchair accessible", "mobility assistance")
- Budget/price preferences ("luxury", "budget-friendly", "under $200")
- Style preferences ("boutique hotels", "outdoor activities", "fine dining")
- Explicit likes/dislikes ("I love museums", "I hate crowds")
- Cuisine preferences ("I prefer Italian food", "I'm into street food")

**SKIP preference extraction and go directly to Step 2 (routing) when:**
- Trip planning requests ("recommend a 3-day itinerary for NYC")
- Place search requests ("find hotels in Barcelona", "what museums should I visit?")
- Greetings ("hi", "hello", "thanks", "goodbye")
- Confirmations ("yes", "save it", "go ahead", "sure", "sounds good")
- Follow-up questions ("what about Day 2?", "any other options?", "tell me more")
- Saved-preference questions ("what are my hotel preferences?", "what dietary restrictions do I have?")
- System questions ("what can you do?", "how does this work?")
- Itinerary modifications ("move Sagrada Familia to Day 1", "add this to my trip")

This optimization avoids unnecessary tool calls and speeds up response time significantly.

## A. Extract Preferences (only when message contains preferences)
Call `extract_preferences_from_message` with:
- `message`: The user's message text
- `role`: "user"
- `user_id`: Use the userId from context
- `tenant_id`: Use the tenantId from context

**Example**:
{
  "name": "extract_preferences_from_message",
  "arguments": {
    "message": "I'm vegan and need wheelchair access",
    "role": "user",
    "user_id": "<from context>",
    "tenant_id": "<from context>"
  }
}

## B. If Preferences Found (shouldExtract: true)
Call `resolve_memory_conflicts` with the extracted preferences:
{
  "name": "resolve_memory_conflicts",
  "arguments": {
    "new_preferences": [...],  // from extraction result
    "user_id": "<from context>",
    "tenant_id": "<from context>"
  }
}

## C. Store or Confirm
Call `store_resolved_preferences` with the resolutions:
{
  "name": "store_resolved_preferences",
  "arguments": {
    "resolutions": [...],  // from conflict resolution
    "user_id": "<from context>",
    "tenant_id": "<from context>",
    "justification": "<session_id or message context>"
  }
}

## D. Handle Conflicts Requiring Confirmation
If `store_resolved_preferences` returns `needsConfirmation` with items:
- **STOP routing** to specialists
- **Ask the user to clarify** the conflict
- **Wait for their response** before proceeding

**Example response**:
"I noticed you previously mentioned you're vegetarian, but now you said you love steak. Has your preference changed, or is this specific to a particular occasion?"

## E. If No Preferences or Auto-Resolved
- Proceed to Step 2 (Route to specialists)

**Important Notes**:
- Greetings like "Hello" will have `shouldExtract: false` - that's expected
- Simple yes/no responses will be skipped - that's fine
- Only actual preference statements will be extracted
- This process takes 1-2 seconds but ensures preferences are never lost

# Step 2: Route to Specialists

If the user asks what preferences, dietary restrictions, accessibility needs, or travel requirements are saved, answer directly by calling `recall_memories`. Do not transfer these questions to Hotel, Activity, or Dining; the deterministic specialist nodes are for recommendations in a destination.

## Available Specialized Agents
- **Hotel Agent**: Accommodation searches (preferences already stored by you)
- **Activity Agent**: Attraction searches (preferences already stored by you)
- **Dining Agent**: Restaurant searches (preferences already stored by you)
- **Itinerary Generator**: Synthesizes all gathered information into day-by-day plans
- **Summarizer**: Conversation compression and recaps (auto-triggered every 10 turns)

## Routing Rules

### Transfer to Hotel Agent (`transfer_to_hotel`)
**Use when**: User asks about accommodations, lodging, places to stay
- "Find hotels in Barcelona"
- "Where should I stay?"
- "Show me boutique hotels with pools"

### Transfer to Activity Agent (`transfer_to_activity`)
**Use when**: User asks about attractions, things to do, sightseeing
- "What museums should I visit?"
- "Show me outdoor activities"
- "Find family-friendly attractions"

### Transfer to Dining Agent (`transfer_to_dining`)
**Use when**: User asks about restaurants, food, dining, cuisine
- "Find vegetarian restaurants"
- "Where should I eat dinner?"
- "Show me Italian restaurants"

### Transfer to Itinerary Generator (`transfer_to_itinerary_generator`)
**Use when**: User wants complete trip plan or day-by-day schedule
- "Create a 3-day itinerary for Paris"
- "Plan my Barcelona trip"
- "Generate a day-by-day schedule"

### Summarizer Agent (Auto-Triggered)
**NEVER manually route to summarizer** - it auto-triggers every 10 messages
- Compresses conversation history in the background
- User never sees this happening
- Conversation continues seamlessly

### When Summarizer Returns Control to You
**Context**: The summarizer operates in two modes:
1. **Mode 1 (Auto)**: Background compression every 20 messages - INVISIBLE to user
2. **Mode 2 (User-Requested)**: User explicitly asked for summary - VISIBLE to user

**Your Response Based on Mode**:

**Mode 1 - Auto-Summarization (CRITICAL INSTRUCTION)**:
When summarizer transfers back with reason: "Background summarization complete, returning to user query"
- **DO NOT acknowledge the summarization** - The user should never know it happened
- **DO NOT respond with** "I've saved a summary" or mention summarization at all
- **Immediately analyze the user's MOST RECENT message** (the one that triggered summarization)
- **Route to the appropriate specialist** based on that message
- **Act as if summarization never happened** - it's a transparent background operation

**Example (Mode 1 - Correct Behavior)**:

User: "Show me some day trips" (message 21 - triggers auto-summarization)
Summarizer: [Compresses messages 1-20 in background]
Summarizer: transfer_to_orchestrator(reason="Background summarization complete, returning to user query")
YOU: [Analyze "Show me some day trips"] → transfer_to_activity(reason="User requested day trips")
User sees: [Day trip recommendations from Activity Agent]
DO NOT say: "I've saved a summary of our conversation. How else can I assist?"


**Mode 2 - User-Requested Summary (Different Behavior)**:
When summarizer transfers back with reason: "User summary retrieval complete"
- The user ASKED for a summary, so they already saw it
- You can acknowledge: "Is there anything else I can help you with?"
- Or simply wait for their next request

## Conversational Responses

For greetings, thanks, and general conversation:
- Respond naturally without routing
- "Hello! I'd be happy to help you plan your trip. Would you like to find hotels, restaurants, activities, or create an itinerary?"
- "You're welcome! Is there anything else I can help you with?"

## Important Rules
- **Memory extraction happens FIRST** before any routing
- **Don't store memories yourself** - the extraction tools handle this
- **Specialists don't store memories** - you already did that
- **Route immediately after extraction** - don't delay
- **Handle conflicts before routing** - clarify contradictions first
- **Be transparent about updates** - "I've noted your vegetarian preference"

# Examples

User: "Hi, I'm planning a trip to Barcelona"
1. Call extract_preferences_from_message → shouldExtract: false (greeting)
2. Respond naturally and ask what they need

User: "I'm vegetarian"
1. Call extract_preferences_from_message → shouldExtract: true, preferences: [{category: "dietary", value: "vegetarian", ...}]
2. Call resolve_memory_conflicts → no conflicts
3. Call store_resolved_preferences → stored successfully
4. Respond: "I've noted that you're vegetarian. Would you like me to find restaurants, hotels, or activities for your trip?"

User: "Find hotels in Barcelona"
1. Call extract_preferences_from_message → shouldExtract: false (search request, not preference)
2. Transfer to hotel agent

User: "What are my hotel preferences?"
1. Call extract_preferences_from_message → shouldExtract: false (query, not new preference)
2. Call recall_memories and summarize the saved hotel-related preferences
```

#### Add the Summarizer Agent Prompt

Next, locate and open the empty **summarizer.prompty** file.

Copy and paste the following text into it:

```text
# Role
You are the **Summarizer**. You have two main responsibilities:
1. **Auto-summarization**: Compress long conversations every 10+ turns to keep context manageable
2. **User-requested recaps**: Show summaries when users ask "What have we discussed?" or "Show my past trips"

# Core Responsibilities
- **Identify key points**: Preferences shared (lodging, activity, dining), places discussed, plans made
- **Create structured summaries**: Organized by domain (hotels, activities, restaurants, itineraries)
- **Mark messages as summarized** using mark_span_summarized tool
- **Extract action items**: Bookings needed, decisions pending
- **Retrieve user summaries**: Show past conversation summaries when requested
- **ALWAYS save summaries**: Both modes must save summaries to database using create_summary tool

# CRITICAL RULE: Auto-Summarization is INVISIBLE

**When auto-triggered (Mode 1):**
- Summarize silently in the background
- Store the summary in the database using mark_span_summarized tool
- Transfer back to orchestrator IMMEDIATELY
- DO NOT show summary content to the user
- DO NOT add any response about summarization
- Let orchestrator handle the user's query

**When user explicitly asks (Mode 2):**
- "Show me my past trips"
- "What have we discussed?"
- "Give me a recap"
- Retrieve existing summaries from database
- Store the new summary using mark_span_summarized tool
- THEN show formatted summaries to the user

# EXECUTION FLOW FOR MODE 1 (MOST IMPORTANT)

When auto-triggered, you MUST execute these tool calls in this exact order:

**Step 1: Check span**

{"name": "get_summarizable_span", "arguments": {"session_id": "...", "tenant_id": "...", "user_id": "...", "min_messages": 20, "retention_window": 10}}


**Step 2: If canSummarize is true, get context**

{"name": "get_session_context", "arguments": {"session_id": "...", "tenant_id": "...", "user_id": "..."}}


**Step 3: Generate summary text (in your reasoning)**
Example: "User planning Paris trip May 9-11. Preferences: luxury hotels. Discussed: Mandarin Oriental, Le Bristol. Requested restaurant recommendations."

**Step 4: MANDATORY - Call mark_span_summarized**

{
  "name": "mark_span_summarized",
  "arguments": {
    "session_id": "session_abc123",
    "tenant_id": "marvel",
    "user_id": "peter",
    "summary_text": "User planning Paris trip May 9-11. Preferences: luxury hotels...",
    "span": {"fromMessageId": "msg_001", "toMessageId": "msg_010"},
    "supersedes": ["msg_001", "msg_002", "msg_003", "msg_004", "msg_005", "msg_006", "msg_007", "msg_008", "msg_009", "msg_010"],
    "generate_embedding_flag": true
  }
}


**Step 5: Transfer back (NO user message)**

{"name": "transfer_to_orchestrator", "arguments": {"reason": "Background summarization complete"}}


**DO NOT skip step 4!** The mark_span_summarized tool automatically saves the summary to the database.

# Two Modes of Operation

## Mode 1: Auto-Summarization (Background Compression)
Triggered every 10+ conversation turns to compress older messages.

**CRITICAL: This is a BACKGROUND operation - DO NOT show summary to user!**

### Workflow (Execute ALL steps in order):
1. **Check if summarization needed** → `get_summarizable_span()`
   - If `canSummarize: false` → Transfer to orchestrator immediately
   - If `canSummarize: true` → CONTINUE to step 2

2. **Get conversation context** → `get_session_context(session_id, tenant_id, user_id)`
   - Retrieve all messages in the span
   - Analyze conversation content

3. **Generate compact summary text**:
   - Preferences mentioned: "User discussed [preferences]"
   - Places discussed: "[hotel/restaurant/activity names]"
   - Decisions made: "[bookings, selections]"
   - Keep it under 200 words

4. **Mark span as summarized** → `mark_span_summarized()` **MANDATORY - DO NOT SKIP**
   - Arguments:
     - session_id: from context
     - tenant_id: from context
     - user_id: from context
     - summary_text: the compact summary you generated in step 3
     - span: from get_summarizable_span result
     - supersedes: list of message IDs from span
     - generate_embedding_flag: true
   - This tool AUTOMATICALLY saves to database (no need for separate create_summary call)

5. **Transfer back immediately** → `transfer_to_orchestrator()`
   - Reason: "Background summarization complete, returning to user query"
   - DO NOT show summary to user
   - Let orchestrator handle user's query

**CRITICAL**: You MUST call `mark_span_summarized` in Mode 1. This is where the summary gets saved!

**What the user sees:**
- User: "What else can you recommend?" (10th message)
- System: Auto-summarizes in background (invisible)
- Assistant: "Here are some recommendations..." (responds to query normally)

**What happens behind the scenes:**
- Summarizer compresses messages 1-10
- Saves summary to database
- Marks messages as superseded
- Returns control to orchestrator
- Orchestrator responds to user's query

## Mode 2: User-Requested Summaries (Historical Recap)
Triggered when user asks to see past conversations or trip summaries.

### User Intent Examples:
- "Show me my past trip summaries"
- "What trips have we discussed before?"
- "Remind me of our previous conversations"
- "What have we planned in the past?"
- "Give me a recap of all our discussions"

### Workflow:
1. **Retrieve all user summaries** → `get_all_user_summaries(userId, tenantId)`
2. **Generate new summary for current session** → Create structured summary
3. **Save to database** → `create_summary()` with summary data
4. **Format for readability** → Group by session, show dates
5. **Present to user** → Clear, chronological list
6. **Return to orchestrator** → `transfer_to_orchestrator()`

### Example Output Format for Historical Summaries:

**Your Past Trip Planning Sessions**

📅 Session: October 15, 2025 (session_abc123)
🏨 Lodging: Searched for boutique hotels in Barcelona, preferred rooftop bars
🎭 Activities: Focused on architecture (Sagrada Familia, Park Güell)
🍽️ Dining: Vegetarian restaurants, outdoor seating preferred
📋 Created: 3-day Barcelona itinerary (trip_2025_bar)

📅 Session: September 20, 2025 (session_xyz789)
🏨 Lodging: Luxury hotels in Paris, proximity to museums
🎭 Activities: Art museums (Louvre, Orsay), Seine river cruise
🍽️ Dining: French bistros, late dinners (9pm+)
📋 Created: 5-day Paris itinerary (trip_2025_par)

---
Found 2 past planning sessions. Would you like details about any specific trip?


# Workflow

## Auto-Summarization Workflow (Mode 1) - BACKGROUND ONLY

### 1. Check Summarizable Span

{
  "name": "get_summarizable_span",
  "arguments": {
    "session_id": "session_abc123",
    "tenant_id": "marvel",
    "user_id": "peter",
    "min_messages": 20,
    "retention_window": 10
  }
}


Result will indicate if summarization is possible.

### 2. Get Conversation Context (if canSummarize is true)

{
  "name": "get_session_context",
  "arguments": {
    "session_id": "session_abc123",
    "tenant_id": "marvel",
    "user_id": "peter"
  }
}


### 3. Generate Summary (For Database Storage Only)
Create compact summary with key information:

**Summary text (stored in DB):**
"User planning Paris trip May 9-11. Preferences: luxury hotels. Hotels discussed: Mandarin Oriental, Le Bristol, Ritz, Peninsula, Four Seasons. Requested restaurant recommendations. No dietary restrictions mentioned."

**DO NOT show this to the user - it's for database storage only!**

### 4. Mark Span as Summarized (MANDATORY - This saves to database)

{
  "name": "mark_span_summarized",
  "arguments": {
    "session_id": "session_abc123",
    "tenant_id": "marvel",
    "user_id": "peter",
    "summary_text": "User planning Paris trip May 9-11. Preferences: luxury hotels. Hotels discussed: Mandarin Oriental, Le Bristol, Ritz, Peninsula, Four Seasons. Requested restaurant recommendations. No dietary restrictions mentioned.",
    "span": {
      "fromMessageId": "msg_001",
      "toMessageId": "msg_010"
    },
    "supersedes": ["msg_001", "msg_002", "msg_003", "msg_004", "msg_005", "msg_006", "msg_007", "msg_008", "msg_009", "msg_010"],
    "generate_embedding_flag": true
  }
}


**Note**: mark_span_summarized automatically saves to database. No need for separate create_summary call.

### 5. Transfer Back Immediately (NO USER MESSAGE)

{
  "name": "transfer_to_orchestrator",
  "arguments": {"reason": "Background summarization complete, returning to user query"}
}


## User-Requested Summary Workflow (Mode 2) - SHOW TO USER


**Summary of Our Conversation**

🏨 Lodging Preferences (Hotel Agent):
- Room type: Suite
- Amenities: Pool, WiFi, Rooftop bar
- Price range: $200-$300/night
- Location: City center, near metro

🎭 Activity Preferences (Activity Agent):
- Categories: Architecture, History, Art
- Duration: 2-3 hour visits preferred
- Accessibility: Wheelchair accessible required
- Style: Outdoor activities over indoor

🍽️ Dining Preferences (Dining Agent):
- Dietary: Vegetarian (strict)
- Cuisines: Italian, Local, Mediterranean
- Seating: Outdoor preferred
- Meal timing: Late dinners (8-10pm)

📋 Itineraries Created:
- Barcelona 3-Day Trip (June 15-17, 2024) - Trip ID: abc123
  - Day 1: Cotton House Hotel, Gothic Quarter, Teresa Carles
  - Day 2: Sagrada Familia, Park Güell, Flax & Kale
  - Day 3: Barceloneta Beach, Check-out

🔍 Places Discussed:
- Hotels: Cotton House Hotel (selected), Hotel Arts (considered)
- Activities: Sagrada Familia, Park Güell, Gothic Quarter
- Restaurants: Teresa Carles, Flax & Kale, Rasoterra

⏳ Pending Decisions:
- Confirm booking for Cotton House Hotel
- Choose dinner restaurant for Day 3


## User-Requested Summary Workflow (Mode 2) - SHOW TO USER

### 1. Get Current Session Context

{
  "name": "get_session_context",
  "arguments": {"session_id": "...", "limit": 50}
}


### 2. Retrieve Past Summaries

{
  "name": "get_all_user_summaries",
  "arguments": {"user_id": "...", "tenant_id": "..."}
}


### 3. Generate Summary for Current Session
Create structured summary with key information:


**Summary of Our Conversation**

🏨 Lodging Preferences:
- Room type: Suite
- Amenities: Pool, WiFi, Rooftop bar
- Price range: $200-$300/night
- Location: City center, near metro

🎭 Activity Preferences:
- Categories: Architecture, History, Art
- Duration: 2-3 hour visits preferred
- Accessibility: Wheelchair accessible required

🍽️ Dining Preferences:
- Dietary: Vegetarian (strict)
- Cuisines: Italian, Local, Mediterranean
- Seating: Outdoor preferred

📋 Itineraries Created:
- Barcelona 3-Day Trip (June 15-17, 2024) - Trip ID: abc123
  - Day 1: Cotton House Hotel, Gothic Quarter, Teresa Carles
  - Day 2: Sagrada Familia, Park Güell, Flax & Kale

⏳ Pending Decisions:
- Confirm booking for Cotton House Hotel


### 4. Save Summary to Database
### 4. Mark Span as Summarized (saves to database)

{
  "name": "mark_span_summarized",
  "arguments": {
    "session_id": "session_abc123",
    "tenant_id": "marvel",
    "user_id": "peter",
    "summary_text": "User discussed Barcelona trip with vegetarian dining preferences...",
    "span": {
      "fromMessageId": "msg_001",
      "toMessageId": "msg_015"
    },
    "supersedes": ["msg_001", "msg_002", ..., "msg_015"],
    "generate_embedding_flag": true
  }
}


### 5. Show Formatted Summary to User
Display the nicely formatted summary (from step 3) to the user.

### 6. Transfer Back to Orchestrator

{
  "name": "transfer_to_orchestrator",
  "arguments": {"reason": "User summary retrieval complete"}
}


# Key Difference Between Modes

## Mode 1 (Auto): SILENT BACKGROUND COMPRESSION
- **User sees**: Nothing! Conversation continues normally
- **You do**: Check span → Get context → Generate compact summary → Call mark_span_summarized → Transfer back immediately
- **You DO NOT**: Show summary text to user
- **Tool to save**: mark_span_summarized (mandatory)
- **Transfer reason**: "Background summarization complete"

## Mode 2 (User-Requested): VISIBLE SUMMARY DISPLAY
- **User sees**: Formatted summary with trip details and emojis
- **You do**: Get context → Retrieve past summaries → Generate formatted summary → Call mark_span_summarized → Show to user → Transfer back
- **Tool to save**: mark_span_summarized (mandatory)
- **Transfer reason**: "User summary retrieval complete"

# CRITICAL: Both Modes MUST Save to Database

**Always call mark_span_summarized tool in BOTH modes:**
- Mode 1: Save compact summary silently (DO NOT show to user)
- Mode 2: Save structured summary AND show it to user (formatted display)

# Agent-to-Agent Transfers

## Return to Orchestrator (ONLY OPTION)

**For Mode 1 (Auto-Summarization):**
Transfer immediately WITHOUT showing summary to user:


{
  "name": "transfer_to_orchestrator",
  "arguments": {"reason": "Background summarization complete, returning to user query"}
}


**For Mode 2 (User-Requested Summaries):**
Transfer after showing summary to user:


{
  "name": "transfer_to_orchestrator",
  "arguments": {"reason": "User summary retrieval complete"}
}


## DO NOT Transfer to Specialists
- DO NOT call `transfer_to_hotel` / `transfer_to_activity` / `transfer_to_dining`
- Only orchestrator can route to specialists

# Context Retrieval (When User Returns)

When user returns to thread after summarization:
1. Load last N messages (recent context, e.g., messages 51-60)
2. Load recent summaries (older context, e.g., summary of messages 1-50)
3. Load memories (persistent preferences across all trips)
4. Combine for full conversation awareness

Example retrieval flow:

User returns to thread after 100 messages exchanged:
- Messages 81-100: [Full messages] (recent)
- Summary 1: [Messages 1-80] (older context)
- Memories: [Lodging: vegetarian, Activity: architecture, Dining: late dinners]
→ Agent sees full context without loading 100 messages


Example retrieval:

Messages 81-100: [Full messages]
Summary 1: [Messages 1-80]
→ Agent sees full context without loading 100 messages


## Edge Cases

### Rapid Conversation
- **Problem**: User sends 50 messages in 10 minutes
- **Solution**: Don't summarize yet, increase retention window

### Topic Shifts
- **Problem**: Conversation changes from Barcelona → Madrid
- **Solution**: Create summary before topic shift, start fresh

### Important Tool Calls
- **Problem**: Booking confirmations in old messages
- **Solution**: Extract critical info to memories before summarizing

### User References Past
- **Problem**: "Remember that restaurant you suggested?"
- **Solution**: Search across summaries AND recent messages

## MCP Tools Available

- `get_summarizable_span`: Find messages to summarize (auto-mode)
- `mark_span_summarized`: Create summary and set TTL (auto-mode)
- `get_all_user_summaries`: Get all summaries for user across sessions (user-requested mode)
- `get_thread_context`: Retrieve messages + summaries
- `recall_memories`: Extract important info before summarizing
- `transfer_to_orchestrator`: Return control after completing task (ONLY transfer option)

## Guidelines

- **Preserve important details**: Dates, names, decisions
- **Maintain chronology**: Order of events matters
- **Be concise**: Summary should be 5-10% of original length
- **Include context**: Why user wanted something
- **Avoid hallucination**: Only summarize what's actually there
- **Structure clearly**: Use bullet points, sections
- **Generate embeddings**: Enable semantic search over summaries
- **Test retrieval**: Ensure context remains accessible

## Background Job Pattern

For production systems:

# Run every hour
for thread in active_threads:
    if thread.messageCount > 50:
        span = await get_summarizable_span(thread.id)
        if span.canSummarize:
            summary = await generate_summary(span.messages)
            await mark_span_summarized(thread.id, summary, span)


## MCP Tools Available

- `get_summarizable_span`: Get messages that need summarization
- `mark_span_summarized`: Store summary with TTL
- `get_thread_context`: Get recent context
- `transfer_to_orchestrator`: After summarization is complete (default)

## When to Transfer

After creating a summary:
- Always → `transfer_to_orchestrator` (let orchestrator handle next user request)

Your goal: Compress conversation history efficiently while preserving all important context for future interactions.

```

#### Add the Memory Conflict and Resolution Prompt

Next, locate and open the empty **memory_conflict_resolution.prompty** file.

Copy and paste the following text into it:

```text
---
name: Memory Conflict Resolution
description: Intelligently resolve conflicts between new and existing travel preferences
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
  parameters:
    temperature: 0.3
    max_tokens: 2000
---
system:
You are a travel preference conflict resolution agent. Analyze new preferences against existing ones and decide which can be auto-resolved and which need user confirmation.

**Conflict Resolution Rules:**

1. **Skip Storage (duplicate/reinforcement):**
   - Exact same preference already exists (vegan + vegan)
   - Very similar preference with same category/value ("vegetarian" exists, new "don't eat meat" → skip, it's covered)
   - Reinforcement: "I'm vegan" said twice → skip second one
   - **Action**: "skip" (don't store, existing memory already covers this)

2. **Auto-Resolve (no user confirmation needed):**
   - Complementary preferences (vegan + gluten-free) → store both
   - Preference refinement/evolution (vegetarian → vegan) → update existing
   - Preference narrowing (Italian food → Northern Italian) → update existing
   - **Adjacent price tier changes** (budget → moderate, moderate → luxury) → update existing
   - Additional context that doesn't conflict → store new
   - Low-severity evolution (casual dining → fine-dining) → update existing

3. **Require User Confirmation (high severity):**
   - Contradictory dietary (vegan ↔ loves meat)
   - Contradictory accessibility (no stairs ↔ hiking enthusiast)
   - **Extreme price tier jumps** (budget ↔ luxury, skipping moderate tier)
   - Direct negation (loves spicy ↔ can't handle spice)
   - **Action**: "ask-user"

**Important Note on Price Tiers:**
- budget → moderate: **LOW SEVERITY** (auto-resolve, update-existing)
- moderate → luxury: **LOW SEVERITY** (auto-resolve, update-existing)
- budget → luxury: **HIGH SEVERITY** (require-confirmation, ask-user)
- Any tier with "for this trip": **AUTO-RESOLVE** (store-both as episodic)

4. **Trip-Specific Context (auto-resolve as episodic):**
   - If new preference says "for this trip" or "this time"
   - If salience < 0.75 (exploratory/temporary)
   - Store as episodic memory without conflict

**Important: Check for Duplicates First**
Before analyzing conflicts, check if the new preference is essentially the same as an existing one:
- "I'm vegan" vs "I'm vegan" → SKIP (exact duplicate)
- "I'm vegetarian" vs "I don't eat meat" → SKIP (same meaning, different wording)
- "wheelchair accessible" vs "need wheelchair access" → SKIP (same requirement)
- "I need gluten-free" + "I'm vegan" → STORE BOTH (complementary, different categories)

**Your Task:**
For each new preference, determine:
1. Is it a duplicate/reinforcement of existing preference? → Skip
2. Is there a conflict with existing preferences? → Analyze severity
3. If no duplicate and no conflict → Store as new
4. What's the resolution strategy?

Return JSON in this EXACT format:
{
  "resolutions": [
    {
      "newPreference": {
        "category": "dietary",
        "value": "vegan",
        "text": "I'm vegan",
        "salience": 0.95,
        "type": "declarative"
      },
      "conflict": true/false,
      "conflictsWith": "existing memory text if applicable",
      "conflictingMemoryId": "memory-id if applicable",
      "severity": "none" | "low" | "high",
      "decision": "skip" | "auto-resolve" | "require-confirmation",
      "strategy": "explanation of resolution strategy",
      "action": "skip" | "store-new" | "update-existing" | "store-both" | "ask-user"
    }
  ]
}

**Examples:**

New: "I'm vegan" | Existing: "I'm vegan"
→ No conflict, duplicate detected, decision: skip, action: skip, strategy: "Exact duplicate of existing preference"

New: "I don't eat meat" | Existing: "I'm vegetarian"
→ No conflict, covered by existing, decision: skip, action: skip, strategy: "Existing vegetarian preference already covers this dietary restriction"

New: "I need wheelchair access" | Existing: "wheelchair-friendly required"
→ No conflict, duplicate detected, decision: skip, action: skip, strategy: "Same accessibility requirement already stored"

New: "I'm vegan" | Existing: "I'm vegetarian"
→ Low severity evolution, decision: auto-resolve, action: update-existing, strategy: "Vegan is more restrictive than vegetarian, update preference"

New: "I love spicy food" | Existing: "I cannot handle spice"
→ High severity contradiction, decision: require-confirmation, action: ask-user, strategy: "Contradictory spice preferences"

New: "For this Paris trip I want luxury hotels" | Existing: "I prefer budget hotels"
→ Trip-specific context, decision: auto-resolve, action: store-both, strategy: "Trip-specific override, store as episodic"

New: "I need wheelchair access" | Existing: None
→ No conflict, decision: auto-resolve, action: store-new, strategy: "New accessibility requirement"

New: "I'm gluten-free" | Existing: "I'm vegan"
→ Complementary preferences, decision: auto-resolve, action: store-both, strategy: "Different dietary categories, store both"

New: "I prefer moderate hotels now" | Existing: "I usually stay at budget hotels"
→ Low severity evolution, decision: auto-resolve, action: update-existing, strategy: "Adjacent price tier upgrade (budget → moderate), natural preference evolution"

New: "I want luxury hotels" | Existing: "I prefer budget hotels"
→ High severity jump, decision: require-confirmation, action: ask-user, strategy: "Extreme price tier jump (budget → luxury skips moderate), confirm intentional change"

user:
**Existing User Preferences:**
{{existing_preferences}}

**New Preferences to Store:**
{{new_preferences}}

Analyze and respond with JSON only. Check for duplicates FIRST before analyzing conflicts.

```

#### Add the Preference Extraction Prompt

Next, locate and open the empty **preference_extraction.prompty** file.

Copy and paste the following text into it:

```text
---
name: Preference Extraction
description: Extract travel preferences from user or assistant messages
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
  parameters:
    temperature: 0.3
    max_tokens: 1500
---
system:
You are a travel preference extraction agent. Analyze messages and determine if they contain extractable travel preferences.

Your task:
1. Determine if this message contains meaningful travel preferences worth storing
2. If YES: Extract structured preferences as facets
3. If NO: Explain why (greeting, simple response, unclear, no preferences, etc.)

**Skip if:**
- Greetings (hi, hello, thanks, goodbye)
- Simple yes/no responses without context
- Acknowledgments (ok, sure, got it, sounds good)
- Questions without preferences
- Unclear or ambiguous statements
- Too short or lacks substance
- Navigation/system commands

**Extract if:**
- Explicit dietary needs (vegan, vegetarian, gluten-free, allergies, etc.)
- Accessibility requirements (wheelchair, mobility assistance, hearing/visual impairment)
- Price preferences (budget, luxury, moderate, value-conscious)
- Style preferences (boutique hotels, local restaurants, outdoor activities, museums)
- Explicit dislikes or restrictions
- Clear preference statements from either user or assistant
- Cuisine preferences (Italian, Japanese, street food, fine dining)
- Atmosphere preferences (quiet, lively, romantic, family-friendly)

**Categories to extract:**
- dietary: vegan, vegetarian, pescatarian, gluten-free, kosher, halal, seafood, nut-allergy, dairy-free
- accessibility: wheelchair-friendly, mobility-assistance, visual-impairment, hearing-impairment, service-animal
- priceRange: budget, moderate, luxury, value
- hotelStyle: boutique, chain, resort, hostel, apartment, bed-and-breakfast
- diningStyle: casual, fine-dining, local, fast-casual, street-food, michelin, farm-to-table
- activityType: museums, outdoor, shopping, nightlife, historical, family-friendly, adventure, cultural
- spiceLevel: no-spice, mild, medium, spicy, very-spicy
- atmosphere: quiet, lively, romantic, family-friendly, solo-friendly, pet-friendly
- cuisine: italian, japanese, mexican, french, thai, indian, mediterranean, fusion

**Salience scoring (0.0-1.0):**
- 0.95-1.0: Strong explicit statement ("I am vegan", "I need wheelchair access")
- 0.85-0.94: Clear preference ("I prefer boutique hotels", "I love spicy food")
- 0.70-0.84: Moderate preference ("I usually go for budget options")
- 0.50-0.69: Weak/exploratory ("I might try vegetarian options")

**Memory type:**
- declarative: Permanent facts about user ("I'm vegan", "I use a wheelchair")
- procedural: Learned patterns ("I usually book budget hotels")
- episodic: Trip-specific context ("For this Paris trip, I want luxury")

Return JSON in this EXACT format:
{
  "shouldExtract": true/false,
  "skipReason": "explanation if shouldExtract is false",
  "preferences": [
    {
      "category": "dietary",
      "value": "vegan",
      "text": "I'm vegan",
      "salience": 0.95,
      "type": "declarative"
    }
  ]
}

**Examples:**

Message: "Hi there!"
Response: {"shouldExtract": false, "skipReason": "Simple greeting with no preferences", "preferences": []}

Message: "yes"
Response: {"shouldExtract": false, "skipReason": "Simple affirmative response without context", "preferences": []}

Message: "I'm vegan and need wheelchair-accessible places"
Response: {
  "shouldExtract": true,
  "preferences": [
    {"category": "dietary", "value": "vegan", "text": "I'm vegan", "salience": 0.95, "type": "declarative"},
    {"category": "accessibility", "value": "wheelchair-friendly", "text": "need wheelchair-accessible places", "salience": 0.95, "type": "declarative"}
  ]
}

Message: "I prefer boutique hotels over chains"
Response: {
  "shouldExtract": true,
  "preferences": [
    {"category": "hotelStyle", "value": "boutique", "text": "prefer boutique hotels", "salience": 0.85, "type": "declarative"}
  ]
}

Message: "What can you help me with?"
Response: {"shouldExtract": false, "skipReason": "Question without stated preferences", "preferences": []}

Message: "For this trip I want to try spicy food"
Response: {
  "shouldExtract": true,
  "preferences": [
    {"category": "spiceLevel", "value": "spicy", "text": "want to try spicy food", "salience": 0.75, "type": "episodic"}
  ]
}

user:
Analyze this {{role}} message and respond with JSON only.

Message: "{{message}}"

```

## Activity 5: Test Your Work

With all intelligent memory features implemented, it's time to test the system end-to-end! This activity will verify automatic preference extraction, conflict detection, and auto-summarization.

### Restart All Services

Since we've added new tools and agent logic, we need to restart all services to load the changes.

**Terminal 1 (MCP Server):**

Stop the currently running MCP server (press **Ctrl+C**), then restart it:

```powershell
cd mcp_server
$env:PYTHONPATH="..\python"; python mcp_http_server.py
```

**Important**: Always ensure your virtual environment is activated before starting the server!

You must be in **multi-agent-workshop\01_exercises** folder and then use the below commands to activate the virtual environment. And after activating the environment, follow the above commands to re-start the mcp server.

```powershell
cd multi-agent-workshop\01_exercises
.\venv\Scripts\Activate.ps1
```

**Terminal 2 (Backend API):**

Stop the currently running backend (press **Ctrl+C**), then restart it:

```powershell
cd python
uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
```

**Important**: Always ensure your virtual environment is activated before starting the server!

You must be in **multi-agent-workshop\01_exercises** folder and then use the below commands to activate the virtual environment. And after activating the environment, follow the above commands to re-start the backend server.

```powershell
cd multi-agent-workshop\01_exercises
.\venv\Scripts\Activate.ps1
```

**Terminal 3 (Frontend):**

Stop the currently running frontend (press **Ctrl+C**), then restart it:

> **Note**: The frontend doesn't require virtual environment activation since it uses Node.js.

**All Platforms:**

```bash
cd multi-agent-workshop/01_exercises/frontend
npm start
```

#### Test 1: Automatic Preference Extraction (Implicit Statements)

**Objective**: Verify that the system extracts preferences from natural conversation without explicit "remember this" commands.

**Steps**:

1. Start a new conversation in the frontend (be sure to sign in as user "Peter" or "Bruce" as they don't have any pre-loaded memories)
2. Send: `Hi, I'm planning a trip to Tokyo`
3. Send: `I don't eat meat and I need wheelchair-accessible restaurants`
4. Open Azure Data Explorer (Cosmos DB)
5. Query the `Memories` container:
   ```sql
   SELECT c.memoryId, c.userId, c.tenantId, c.memoryType, c.text, c.facets, c.salience FROM c
   WHERE c.userId = "tony"
   ORDER BY c.extractedAt DESC
   ```

**Chat Assistant Result**

![Testing_1](./media/Module-04/Test1.png)

**Expected Results:**

- ✅ Two new memories created:
  - Dietary preference: "vegan" or "vegetarian" (category: dietary)
  - Accessibility preference: "wheelchair-friendly" (category: accessibility)
- ✅ Both memories have salience >= 0.9 (high confidence)
- ✅ Both memories are type declarative (permanent facts)
- ✅ Agent responds naturally without asking "Should I remember this?"

#### Test 2: Conflict Detection - High Severity (Dietary Contradiction)

**Objective:** Verify that the system detects contradictory dietary preferences and asks for user confirmation.

**Steps:**

- Continue the conversation from Test 1
- Send: `Actually, I love steak and seafood`
- Observe the agent's response

**Chat Assistant Result**

![Testing_2](./media/Module-04/Test2.png)

**Expected Results:**

- ✅ Agent STOPS and asks for clarification
- ✅ Response mentions the contradiction: "You previously mentioned vegetarian, but now you're mentioning steak"
- ✅ Agent asks: "Has your preference changed?" or similar
- ✅ Memory is NOT automatically stored (no new "loves meat" memory in DB)

#### Test 3: Conflict Resolution - Auto-Resolve Low Severity

**Objective:** Verify that complementary preferences are auto-stored without confirmation.

**Steps:**

- Start a new conversation (log out and back in as Peter/Bruce, the user you choose before)
- Send: `I'm vegan`
- Wait for memory to be stored
- Send: `I'm also gluten-free`
- Check Cosmos DB Memories container

**Chat Assistant Result**

![Testing_3_1](./media/Module-04/Test3-1.png)

![Testing_3_2](./media/Module-04/Test3-2.png)

**Expected Results:**

- ✅ Both memories are stored automatically
- ✅ Agent does NOT ask for confirmation (complementary preferences)
- ✅ Agent acknowledges both: "I've noted your vegan and gluten-free preferences"

#### Test 4: Preference Evolution - Update Existing Memory

**Objective:** Verify that preference refinements correctly supersede old memories.

**Steps:**

- Start a new conversation (log out and back in as Peter/Bruce, the user you choose before)
- Send: `I usually stay at budget hotels`
- Wait for memory to be stored (check DB)
- Send: `Actually, I prefer moderate hotels now`
- Check Cosmos DB for both memories

**Chat Assistant Result**

![Testing_4](./media/Module-04/Test4.png)

#### Test 5: Trip-Specific Context (Episodic Memory)

**Objective:** Verify that trip-specific preferences don't conflict with general preferences.

**Steps:**

- Start a new conversation (log out and back in as Peter/Bruce, the user you choose before)
- Send: `I usually prefer budget hotels`
- Send: `For this Paris trip, I want luxury accommodations`
- Check Cosmos DB memories

**Chat Assistant Result**

![Testing_5](./media/Module-04/Test5.png)

**Expected Results:**

- ✅ Two memories coexist without conflict:
  - Memory 1: "budget hotels" (type: procedural, general preference)
  - Memory 2: "luxury accommodations" (type: episodic, trip-specific, TTL: 90 days)
- ✅ Agent does NOT ask for confirmation
- ✅ Agent recognizes trip-specific context: "For this Paris trip" → episodic

#### Test 6: Skipping Non-Preference Messages

**Objective:** Verify that greetings and simple responses don't trigger memory extraction.

**Steps:**

- Start a new conversation (log out and back in as Peter/Bruce, the user you choose before)
- Send: `Hello!`
- Send: `Yes`
- Send: `Thanks`
- Check backend or mcp server logs for extraction calls

**Expected Results:**

- ✅ `extract_preferences_from_message` returns `shouldExtract`: false for all three
- ✅ Skip reasons logged:
  - "Hello!" → "Simple greeting with no preferences"
  - "Yes" → "Simple affirmative response without context"
  - "Thanks" → "Simple acknowledgment"
- ✅ No memories created
- ✅ Agent responds naturally to each message

#### Test 7: Auto-Summarization (10+ Messages)

**Objective:** Verify that conversation history is automatically compressed after 10+ messages.

**Steps:**

- Start a new conversation (log out and back in as Peter/Bruce, **the user you didn't choose before**)
- Send 10 messages in sequence(This list is just for reference, you can send different messages):
  - `Hi, I'm planning a trip to Paris`
  - `Find hotels in Paris`
  - `I want luxury hotels`
  - `Find restaurants`
  - `Show me vegetarian options`
  - `What about activities?`
  - `Find historic places`
  - `Create an itinerary for 3 days now.`
  - `That looks great! What else can you recommend?` (10th message - triggers summarization)
- After the 10th message, observe:
  - Backend logs for "Auto-routing to summarizer"
  - Cosmos DB Summaries container

## Debugging and Troubleshooting

### Quick Debug Guide

**Check MCP Server Backend Logs:**

```text
# Look for these key patterns:
Extracting preferences
Conflict resolution
Storing resolved preferences
```

**Check Cosmos DB:**

- View all active memories

```sql

SELECT c.text, c.category, c.salience, c.memoryType
FROM c
WHERE c.userId = 'tony' AND c.superseded = false
```

**Common Issues:**

| Problem                      | Quick Fix                                                           |
|------------------------------|---------------------------------------------------------------------|
| Preferences not extracted    | Check `orchestrator.prompty` has Step 1: Memory Extraction          |
| Conflicts not detected       | Verify `resolve_memory_conflicts` tool exists in orchestrator tools |
| Summarization not triggering | Add `should_summarize()` check in `get_active_agent()` function     |
| Memories not applied         | Ensure specialist nodes call `_memory_first_recommendations()` and include saved preference match reasons in their responses |

### Verification Checklist

After completing tests, verify these key features:

**Automatic Extraction:**

- [ ] "I'm vegetarian" → memory stored (no "remember this" needed)
- [ ] "Hello" → skipped (not a preference)
- [ ] Memory appears in Cosmos DB within 5 seconds

**Conflict Detection:**

- [ ] "Vegan" + "gluten-free" → both stored (complementary)
- [ ] "Vegetarian" then "loves steak" → asks for confirmation
- [ ] Old preferences superseded when updated

**Auto-Summarization:**

- [ ] Triggers at message 10
- [ ] Summary created in Cosmos DB
- [ ] User doesn't notice (seamless)
- [ ] Context preserved after summarization

**Memory Application:**

- [ ] Dietary preferences filter search results
- [ ] Accessibility needs applied automatically
- [ ] Agent mentions using stored preferences

## Module Solution

The following sections include the completed code for this Module. Copy and paste these into your project if you run into issues and cannot resolve.

<details>
    <summary>Completed code for <strong>src/app/travel_agents.py</strong></summary>

<br>

```python
import logging
import os
import sys
import uuid
import asyncio
import json
import re
from typing import Literal
from datetime import datetime, UTC

# Add the project root to Python path to enable imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(override=False)

from langchain_core.messages import ToolMessage, SystemMessage, AIMessage, HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command, interrupt
from langsmith import traceable
from langgraph_checkpoint_cosmosdb import CosmosDBSaver

from src.app.services.azure_open_ai import model
from src.app.services.azure_cosmos_db import (
    DATABASE_NAME, checkpoint_container,
    sessions_container, patch_active_agent,
    update_session_container, append_message,
    count_active_messages, get_all_user_memories,
    query_places_filtered, query_places_hybrid
)

# Setup logging - reduce clutter by setting specific loggers to WARNING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Reduce noise from verbose libraries
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)

# Local interactive mode flag
local_interactive_mode = False

# Prompt directory
PROMPT_DIR = os.path.join(os.path.dirname(__file__), 'prompts')


def load_prompt(agent_name: str) -> str:
    """Load prompt from .prompty file"""
    file_path = os.path.join(PROMPT_DIR, f"{agent_name}.prompty")
    logger.info(f"Loading prompt for {agent_name} from {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        logger.error(f"Prompt file not found for {agent_name}")
        return f"You are a {agent_name} agent in a travel planning system."


def filter_tools_by_prefix(tools, prefixes):
    """Filter tools by name prefix"""
    return [tool for tool in tools if any(tool.name.startswith(prefix) for prefix in prefixes)]


def format_conflict_message(conflicts: list) -> str:
    """
    Format conflict information for user confirmation.

    Args:
        conflicts: List of conflict dictionaries with preference, conflict, and strategy

    Returns:
        Formatted message string asking user to clarify
    """
    if not conflicts:
        return ""

    msg = "I noticed something about your preferences that I'd like to clarify:\n\n"

    for i, conflict in enumerate(conflicts, 1):
        pref = conflict.get("preference", {})
        existing = conflict.get("conflict", "")
        strategy = conflict.get("strategy", "")

        msg += f"{i}. You previously mentioned: \"{existing}\"\n"
        msg += f"   But now you said: \"{pref.get('text', '')}\"\n"
        if strategy:
            msg += f"   ({strategy})\n"
        msg += "\n"

    msg += "Have your preferences changed, or is this specific to a particular trip? Let me know so I can update your profile correctly!"

    return msg


def _extract_transfer_destination(response: dict) -> str | None:
    """Return the specialist destination from the latest transfer tool result."""
    valid_destinations = {
        "hotel",
        "activity",
        "dining",
        "itinerary_generator",
        "summarizer",
        "orchestrator",
    }

    for message in reversed(response.get("messages", [])):
        if isinstance(message, AIMessage):
            for tool_call in message.additional_kwargs.get("tool_calls", []):
                function_name = tool_call.get("function", {}).get("name", "")
                if function_name.startswith("transfer_to_"):
                    goto = function_name.replace("transfer_to_", "")
                    if goto in valid_destinations:
                        return goto

        if not isinstance(message, ToolMessage):
            continue

        try:
            content = json.loads(message.content)
        except Exception as exc:
            logger.debug(f"Could not parse transfer ToolMessage: {exc}")
            continue

        goto = content.get("goto")
        if goto in valid_destinations:
            return goto

    return None


def _deterministic_specialist_route(message: str) -> str | None:
    """Route obvious domain requests without spending an LLM turn."""
    normalized = message.lower()
    has_preference_statement = re.search(
        r"\b(i|we)\s+(am|are|have|need|prefer|like|love|hate|avoid|require)\b|\bmy\s+(preference|preferences|diet|budget|allergy|allergies|restriction|restrictions|requirement|requirements)\b",
        normalized,
    )
    if has_preference_statement:
        return None

    if re.search(r"\b(restaurant|restaurants|dining|dinner|lunch|breakfast|food|eat|cafe|cafes)\b", normalized):
        return "dining"
    if re.search(r"\b(hotel|hotels|stay|stays|lodging|accommodation|accommodations)\b", normalized):
        return "hotel"
    if re.search(r"\b(activity|activities|attraction|attractions|museum|museums|tour|tours|things to do)\b", normalized):
        return "activity"
    return None


# Global variables for MCP session management
_mcp_client = None
_session_context = None
_persistent_session = None
# Global agent variables
orchestrator_agent = None
itinerary_generator_agent = None
summarizer_agent = None


def _latest_user_text(state: MessagesState) -> str:
    message = _latest_user_message(state)
    return str(message.content) if message else ""


def _latest_user_message(state: MessagesState) -> HumanMessage | None:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            return message
    return None


def _extract_geo_scope(message: str) -> str | None:
    match = re.search(
        r"\b(?:in|near|around|for)\s+([A-Za-z][A-Za-z\s-]+?)(?=[?.!,]|\s+(?:with|for|that|and|or|near|in)\s|$)",
        message,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip().lower().replace(" ", "-")
    return None


PREFERENCE_TAXONOMY = {
    "dietary": {
        "pescatarian": {
            "aliases": ["pescatarian", "only eat fish", "eat fish", "fish"],
            "filters": {"dietary": ["seafood"]},
            "search_terms": ["seafood", "fish", "pescatarian"],
            "rank_terms": ["seafood", "fish"],
            "required_terms": ["seafood", "fish"],
            "avoid_terms": ["pork", "meat", "poultry"],
        },
        "vegan": {
            "aliases": ["vegan", "plant based", "plant-based"],
            "filters": {"dietary": ["vegan"]},
            "search_terms": ["vegan", "plant-based"],
            "rank_terms": ["vegan", "plant-based"],
            "required_terms": ["vegan", "plant-based"],
            "avoid_terms": ["meat", "seafood", "dairy"],
        },
        "vegetarian": {
            "aliases": ["vegetarian"],
            "filters": {"dietary": ["vegetarian"]},
            "search_terms": ["vegetarian"],
            "rank_terms": ["vegetarian"],
            "required_terms": ["vegetarian"],
            "avoid_terms": ["meat", "seafood"],
        },
        "gluten_free": {
            "aliases": ["gluten free", "gluten-free"],
            "filters": {"dietary": ["gluten-free"]},
            "search_terms": ["gluten-free"],
            "rank_terms": ["gluten-free"],
            "required_terms": ["gluten-free"],
            "avoid_terms": ["gluten"],
        },
    },
    "price": {
        "luxury": {
            "aliases": ["luxury", "high-end", "upscale", "fine dining", "michelin", "michelin_star"],
            "filters": {},
            "search_terms": ["luxury", "fine dining", "michelin"],
            "rank_terms": ["luxury", "upscale", "fine dining", "michelin"],
            "required_terms": [],
            "avoid_terms": [],
        },
        "budget": {
            "aliases": ["budget", "cheap", "affordable"],
            "filters": {},
            "search_terms": ["budget", "affordable"],
            "rank_terms": ["budget", "affordable"],
            "required_terms": [],
            "avoid_terms": [],
        },
        "moderate": {
            "aliases": ["moderate", "mid-range", "mid range"],
            "filters": {},
            "search_terms": ["moderate", "mid-range"],
            "rank_terms": ["moderate", "mid-range"],
            "required_terms": [],
            "avoid_terms": [],
        },
    },
    "accessibility": {
        "wheelchair": {
            "aliases": ["wheelchair", "wheelchair-friendly", "accessible", "step-free"],
            "filters": {"accessibility": ["wheelchair-friendly"]},
            "search_terms": ["wheelchair-friendly", "accessible", "step-free"],
            "rank_terms": ["wheelchair-friendly", "accessible", "step-free"],
            "required_terms": ["wheelchair-friendly", "accessible", "step-free"],
            "avoid_terms": [],
        },
    },
}


def _memory_text_for_matching(memory: dict) -> str:
    return " ".join([
        str(memory.get("text") or memory.get("content") or memory.get("value") or ""),
        json.dumps(memory.get("facets") or {}),
    ]).lower().replace("_", " ")


def _merge_filter(filters: dict, key: str, value):
    if key == "priceTier":
        filters[key] = value
        return

    values = value if isinstance(value, list) else [value]
    existing = filters.setdefault(key, [])
    for item in values:
        if item not in existing:
            existing.append(item)


def _preference_profile_from_memories(memories: list[dict]) -> dict:
    profile = {
        "filters": {},
        "search_terms": [],
        "rank_terms": [],
        "required_terms": [],
        "avoid_terms": [],
        "matched_preferences": [],
    }

    for memory in memories:
        memory_text = _memory_text_for_matching(memory)
        for category, preferences in PREFERENCE_TAXONOMY.items():
            for canonical, spec in preferences.items():
                if not any(alias in memory_text for alias in spec["aliases"]):
                    continue

                profile["matched_preferences"].append(f"{category}:{canonical}")
                for filter_key, filter_value in spec["filters"].items():
                    _merge_filter(profile["filters"], filter_key, filter_value)
                for key in ["search_terms", "rank_terms", "required_terms", "avoid_terms"]:
                    for term in spec[key]:
                        if term not in profile[key]:
                            profile[key].append(term)

    return profile


def _place_searchable_text(place: dict) -> str:
    return " ".join([
        str(place.get("name") or ""),
        str(place.get("description") or ""),
        " ".join(str(tag) for tag in place.get("tags") or []),
        " ".join(str(item) for item in place.get("dietary") or []),
        " ".join(str(item) for item in place.get("accessibility") or []),
        str(place.get("priceTier") or ""),
    ]).lower()


def _filter_places_by_required_memory(places: list[dict], profile: dict, minimum_results: int = 3) -> list[dict]:
    required_terms = profile.get("required_terms") or []
    if not required_terms:
        return places

    aligned = [
        place for place in places
        if any(term in _place_searchable_text(place) for term in required_terms)
    ]
    return aligned if len(aligned) >= minimum_results else places


def _rank_places_by_memory(places: list[dict], profile: dict) -> list[dict]:
    rank_terms = profile.get("rank_terms") or []
    avoid_terms = profile.get("avoid_terms") or []
    if not rank_terms and not avoid_terms:
        return places

    def score(place: dict) -> tuple[float, float]:
        searchable_text = _place_searchable_text(place)
        memory_score = sum(2 for keyword in rank_terms if keyword in searchable_text)
        memory_score -= sum(1 for keyword in avoid_terms if keyword in searchable_text)
        rating = float(place.get("rating") or 0)
        return (memory_score, rating)

    return sorted(places, key=score, reverse=True)


def _place_memory_matches(place: dict, profile: dict) -> list[str]:
    searchable_text = _place_searchable_text(place)
    matches = [
        term for term in profile.get("rank_terms", [])
        if term in searchable_text
    ]
    return matches[:3]


def _format_places_response(agent_label: str, place_type: str, geo_scope: str, places: list[dict], memories: list[dict], preference_profile: dict | None = None, memory_error: str | None = None) -> str:
    city = geo_scope.replace("-", " ").title()
    noun = {
        "hotel": "hotels",
        "restaurant": "restaurants",
        "attraction": "activities",
    }.get(place_type, "places")

    if not places:
        return f"I checked your saved preferences first, but I could not find matching {noun} in {city}."

    if memory_error:
        intro = f"I tried to check your saved preferences first, but that lookup failed ({memory_error}). I still found these {noun} in {city}:"
    elif memories:
        intro = f"I checked your saved preferences first and found {len(memories)} relevant preference(s). Based on those, here are good {noun} in {city}:"
    else:
        intro = f"I checked your saved preferences first and did not find anything relevant, so I used general quality signals for {city}:"

    lines = [intro]
    for index, place in enumerate(places[:3], start=1):
        name = place.get("name", "Unnamed place")
        rating = place.get("rating")
        neighborhood = place.get("neighborhood")
        price = place.get("priceTier")
        description = place.get("description", "")
        details = []
        if neighborhood:
            details.append(str(neighborhood))
        if rating:
            details.append(f"rating {rating}")
        if price:
            details.append(str(price))
        memory_matches = _place_memory_matches(place, preference_profile or {})
        if memory_matches:
            details.append(f"matches {', '.join(memory_matches)}")
        suffix = f" ({', '.join(details)})" if details else ""
        lines.append(f"{index}. {name}{suffix} — {description}")

    return "\n".join(lines)


async def _memory_first_recommendations(state: MessagesState, config, agent_label: str, place_type: str) -> dict:
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    user_message = _latest_user_text(state)
    geo_scope = _extract_geo_scope(user_message)
    if not geo_scope:
        response_text = "Which city should I use for these recommendations?"
        return {"messages": [AIMessage(content=response_text, name=agent_label)]}

    query = f"{place_type} recommendations in {geo_scope.replace('-', ' ')}"

    memories = []
    memory_error = None
    try:
        memories = await asyncio.wait_for(
            asyncio.to_thread(
                get_all_user_memories,
                user_id=user_id,
                tenant_id=tenant_id,
            ),
            timeout=10,
        )
    except Exception as exc:
        memory_error = repr(exc)
        logger.error(f"{agent_label} memory recall failed: {repr(exc)}")

    # Apply durable memories plus explicit constraints from this turn.
    preference_profile = _preference_profile_from_memories(memories + [{"text": user_message}])
    filters = preference_profile["filters"]
    filters["type"] = place_type
    memory_keywords = preference_profile["search_terms"]
    search_query = " ".join(memory_keywords + [query]) if memory_keywords else query

    places = []
    try:
        places = await asyncio.wait_for(
            asyncio.to_thread(
                query_places_hybrid,
                query=search_query,
                geo_scope_id=geo_scope,
                place_type=place_type,
                dietary=filters.get("dietary"),
                accessibility=filters.get("accessibility"),
                price_tier=None,
                limit=10,
            ),
            timeout=25,
        )
    except Exception as exc:
        logger.error(f"{agent_label} hybrid discovery failed; falling back to filtered search: {repr(exc)}")

    if not places:
        try:
            places = await asyncio.wait_for(
                asyncio.to_thread(
                    query_places_filtered,
                    geo_scope_id=geo_scope,
                    place_type=place_type,
                    dietary=filters.get("dietary"),
                    accessibility=filters.get("accessibility"),
                    price_tier=None,
                ),
                timeout=10,
            )
            places = places[:10]
        except Exception as exc:
            logger.error(f"{agent_label} filtered discovery fallback failed: {repr(exc)}")
            places = []

    places = _filter_places_by_required_memory(places, preference_profile)
    places = _rank_places_by_memory(places, preference_profile)

    response_text = _format_places_response(agent_label, place_type, geo_scope, places, memories, preference_profile, memory_error)

    return {
        "messages": [AIMessage(content=response_text, name=agent_label)]
    }


async def setup_agents():
    """
    Initialize all agents with their respective MCP tools.
    This creates a persistent MCP session and loads domain-aware tools.

    Agent Structure:
    - Orchestrator: Entry point, routes to specialized agents
    - Hotel Agent: Deterministic memory-first accommodation recommendations
    - Activity Agent: Deterministic memory-first attraction recommendations
    - Dining Agent: Deterministic memory-first restaurant recommendations
    - Itinerary Generator: Synthesizes all results into day-by-day plan
    - Summarizer: Compresses conversation history (auto-triggered every 10 turns)
    """
    global orchestrator_agent, itinerary_generator_agent, summarizer_agent
    global _mcp_client, _session_context, _persistent_session

    logger.info("🚀 Starting Travel Assistant MCP client...")

    # Load authentication configuration
    try:
        simple_token = os.getenv("MCP_AUTH_TOKEN")
        github_client_id = os.getenv("GITHUB_CLIENT_ID")
        github_client_secret = os.getenv("GITHUB_CLIENT_SECRET")

        logger.info("🔐 Client Authentication Configuration:")
        logger.info(f"   Simple Token: {'SET' if simple_token else 'NOT SET'}")
        logger.info(f"   GitHub OAuth: {'SET' if github_client_id and github_client_secret else 'NOT SET'}")

        # Determine authentication mode
        if github_client_id and github_client_secret:
            auth_mode = "github_oauth"
            logger.info("   Mode: GitHub OAuth (Production)")
        elif simple_token:
            auth_mode = "simple_token"
            logger.info(f"   Mode: Simple Token (Development)")
        else:
            auth_mode = "none"
            logger.info("   Mode: No Authentication")

    except ImportError:
        auth_mode = "none"
        simple_token = None
        logger.info("🔐 Client Authentication: Dependencies unavailable - no auth")

    logger.info("   - Transport: streamable_http")
    logger.info(f"   - Server URL: {os.getenv('MCP_SERVER_BASE_URL', 'http://localhost:8080')}/mcp/")
    logger.info(f"   - Authentication: {auth_mode.upper()}")
    logger.info("   - Status: Ready to connect\n")

    # MCP Client configuration
    client_config = {
        "travel_tools": {
            "transport": "streamable_http",
            "url": os.getenv("MCP_SERVER_BASE_URL", "http://localhost:8080") + "/mcp/",
        }
    }

    # Add authentication if configured
    if auth_mode == "simple_token" and simple_token:
        client_config["travel_tools"]["headers"] = {
            "Authorization": f"Bearer {simple_token}"
        }
        logger.info("🔐 Added Bearer token authentication to client")
    elif auth_mode == "github_oauth":
        client_config["travel_tools"]["auth"] = "oauth"
        logger.info("🔐 Enabled OAuth authentication for client")

    _mcp_client = MultiServerMCPClient(client_config)
    logger.info("✅ MCP Client initialized successfully")

    # Create persistent session
    _session_context = _mcp_client.session("travel_tools")
    _persistent_session = await _session_context.__aenter__()

    # Load all MCP tools
    all_tools = await load_mcp_tools(_persistent_session)

    logger.info("[DEBUG] All tools registered from Travel Assistant MCP server:")
    for tool in all_tools:
        logger.info(f"  - {tool.name}")

    # ========================================================================
    # Tool Distribution for Specialized Agents
    # ========================================================================

    # Orchestrator: Session management + memory tools + all transfer tools
    orchestrator_tools = filter_tools_by_prefix(all_tools, [
        "create_session", "get_session_context", "append_turn",
        "recall_memories", "extract_preferences_from_message", "resolve_memory_conflicts", "store_resolved_preferences",
        "transfer_to_"  # All transfer tools
    ])

    itinerary_generator_tools = filter_tools_by_prefix(all_tools, [
        "create_new_trip", "update_trip", "get_trip_details",
        "transfer_to_orchestrator"
    ])

    summarizer_tools = filter_tools_by_prefix(all_tools, [
        "get_summarizable_span", "mark_span_summarized", "get_session_context",
        "get_all_user_summaries",  # Query all summaries for the user
        "transfer_to_orchestrator"
    ])

    logger.info(f"\n📊 Tool Distribution:")
    logger.info(f"   Orchestrator: {len(orchestrator_tools)} tools")
    logger.info("   Hotel/Activity/Dining: deterministic memory-first service nodes")
    logger.info(f"   Itinerary Generator: {len(itinerary_generator_tools)} tools")
    logger.info(f"   Summarizer: {len(summarizer_tools)} tools")

    # Create agents with their tools
    orchestrator_agent = create_react_agent(
        model,
        orchestrator_tools,
        state_modifier=load_prompt("orchestrator")
    )

    itinerary_generator_agent = create_react_agent(
        model,
        itinerary_generator_tools,
        state_modifier=load_prompt("itinerary_generator")
    )

    summarizer_agent = create_react_agent(
        model,
        summarizer_tools,
        state_modifier=load_prompt("summarizer")
    )

    logger.info("✅ All agents created successfully\n")


async def cleanup_persistent_session():
    """Clean up the persistent MCP session when the application shuts down"""
    global _session_context, _persistent_session

    if _session_context is not None and _persistent_session is not None:
        try:
            await _session_context.__aexit__(None, None, None)
            logger.info("✅ MCP persistent session cleaned up successfully")
        except Exception as e:
            logger.error(f"Error cleaning up MCP session: {e}")


# ============================================================================
# Helper: Store Message in Database at Every Turn
# ============================================================================

# ============================================================================
# Agent Node Functions
# ============================================================================

@traceable(run_type="llm")
async def call_orchestrator_agent(state: MessagesState, config) -> Command[Literal["orchestrator", "hotel", "activity", "dining", "itinerary_generator", "summarizer", "human"]]:
    """
    Orchestrator agent: Routes requests using transfer_to_ tools.
    Checks for active agent and routes directly if found.
    Stores every message in database.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    logger.info(f"🎯 Calling orchestrator agent with Thread: {thread_id}, User: {user_id}, Tenant: {tenant_id}")

    # Check for active agent in database
    try:
        logging.info(f"Looking up active agent for thread {thread_id}")
        session_doc = sessions_container.read_item(
            item=thread_id,
            partition_key=[tenant_id, user_id, thread_id]
        )
        activeAgent = session_doc.get('activeAgent', 'unknown')
    except Exception as e:
        logger.debug(f"No active agent found: {e}")
        activeAgent = None

    # Initialize session if needed (for local testing)
    if activeAgent is None:
        update_session_container({
            "id": thread_id,
            "sessionId": thread_id,
            "tenantId": tenant_id,
            "userId": user_id,
            "title": "New Conversation",
            "createdAt": datetime.now(UTC).isoformat(),
            "lastActivityAt": datetime.now(UTC).isoformat(),
            "status": "active",
            "messageCount": 0
        })

    logger.info(f"Active agent from DB: {activeAgent}")

    deterministic_destination = _deterministic_specialist_route(_latest_user_text(state))
    if deterministic_destination:
        logger.info(f"🎯 Orchestrator deterministically routing to {deterministic_destination}")
        return Command(update={}, goto=deterministic_destination)

    # Always call orchestrator to analyze the message and decide routing
    # Don't blindly route to the last active agent - user's request may have changed
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))
    response = await orchestrator_agent.ainvoke(state, config)

    destination = _extract_transfer_destination(response)
    if destination and destination != "orchestrator":
        logger.info(f"🎯 Orchestrator transferring to {destination}")
        return Command(update=response, goto=destination)

    return Command(update=response, goto="human")


@traceable(run_type="chain")
async def call_hotel_agent(state: MessagesState, config) -> Command[Literal["hotel", "itinerary_generator", "orchestrator", "human"]]:
    """
    Hotel Agent: Searches accommodations and stores hotel preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    logger.info("🏨 ========== HOTEL AGENT CALLED ==========")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "hotel_agent")

    logger.info(f"🏨 Running memory-first hotel recommendations...")
    response = await _memory_first_recommendations(state, config, "Hotel", "hotel")

    logger.info(f"🏨 ========== HOTEL AGENT COMPLETED ==========")
    return Command(update=response, goto="human")


@traceable(run_type="chain")
async def call_activity_agent(state: MessagesState, config) -> Command[Literal["activity", "itinerary_generator", "orchestrator", "human"]]:
    """
    Activity Agent: Searches attractions and stores activity preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    logger.info("🎭 Activity Agent searching attractions...")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "activity_agent")

    response = await _memory_first_recommendations(state, config, "Activity", "attraction")

    return Command(update=response, goto="human")


@traceable(run_type="chain")
async def call_dining_agent(state: MessagesState, config) -> Command[Literal["dining", "itinerary_generator", "orchestrator", "human"]]:
    """
    Dining Agent: Searches restaurants and stores dining preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    logger.info("🍽️  Dining Agent searching restaurants...")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "dining_agent")

    response = await _memory_first_recommendations(state, config, "Dining", "restaurant")

    return Command(update=response, goto="human")


@traceable(run_type="llm")
async def call_itinerary_generator_agent(state: MessagesState, config) -> Command[Literal["itinerary_generator", "orchestrator", "human"]]:
    """
    Itinerary Generator: Synthesizes all gathered info into day-by-day plan.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    logger.info("📋 Itinerary Generator synthesizing plan...")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "itinerary_generator_agent")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

    response = await itinerary_generator_agent.ainvoke(state, config)

    # Remove system message
    if isinstance(response, dict) and "messages" in response:
        response["messages"] = [
            msg for msg in response["messages"]
            if not isinstance(msg, SystemMessage)
        ]

    return Command(update=response, goto="human")


@traceable(run_type="llm")
async def call_summarizer_agent(state: MessagesState, config) -> Command[Literal["summarizer", "orchestrator", "human"]]:
    """
    Summarizer agent: Compresses conversation history.
    Auto-triggered every 10 turns.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    logger.info("📝 Summarizer compressing conversation...")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "summarizer_agent")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', thread_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

    response = await summarizer_agent.ainvoke(state, config)

    # Remove system message
    if isinstance(response, dict) and "messages" in response:
        response["messages"] = [
            msg for msg in response["messages"]
            if not isinstance(msg, SystemMessage)
        ]

    return Command(update=response, goto="human")


@traceable
def human_node(state: MessagesState, config) -> None:
    """
    Human node: Interrupts for user input in interactive mode.
    """
    interrupt(value="Ready for user input.")
    return None


def should_summarize(state: MessagesState, config) -> bool:
    """
    Check if conversation should be summarized based on message count.
    Returns True if there are 10+ messages and no recent summarization.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    # Count messages in current state (approximate)
    message_count = len(state.get("messages", []))

    # If we have 10+ messages, check if we need summarization
    if message_count >= 10:
        try:
            # Get actual count from DB (non-superseded, non-summary messages only)
            actual_count = count_active_messages(
                session_id=thread_id,
                tenant_id=tenant_id,
                user_id=user_id
            )

            # Trigger summarization every 10 messages
            if actual_count >= 10 and actual_count % 10 == 0:
                logger.info(f"🎯 Auto-triggering summarization at {actual_count} messages")
                return True

        except Exception as e:
            logger.error(f"Error checking message count for summarization: {e}")

    return False


def get_active_agent(state: MessagesState, config) -> str:
    """
    Extract active agent from ToolMessage or fallback to Cosmos DB.
    This is used by the router to determine which specialized agent to call.
    Also checks if auto-summarization should be triggered.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    # **CHECK FOR AUTO-SUMMARIZATION FIRST**
    if should_summarize(state, config):
        logger.info("🤖 Auto-routing to summarizer (10+ messages)")
        return "summarizer"

    activeAgent = None

    # Search for last ToolMessage and try to extract `goto`
    for message in reversed(state['messages']):
        if isinstance(message, AIMessage):
            for tool_call in message.additional_kwargs.get("tool_calls", []):
                function_name = tool_call.get("function", {}).get("name", "")
                if function_name.startswith("transfer_to_"):
                    activeAgent = function_name.replace("transfer_to_", "")
                    logger.info(f"🎯 Extracted activeAgent from AI tool call: {activeAgent}")
                    break
            if activeAgent:
                break

        if isinstance(message, ToolMessage):
            try:
                content_json = json.loads(message.content)
                activeAgent = content_json.get("goto")
                if activeAgent:
                    logger.info(f"🎯 Extracted activeAgent from ToolMessage: {activeAgent}")
                    break
            except Exception as e:
                logger.debug(f"Failed to parse ToolMessage content: {e}")

    # Fallback: Cosmos DB lookup if needed
    if not activeAgent:
        try:
            session_doc = sessions_container.read_item(
                item=thread_id,
                partition_key=[tenant_id, user_id, thread_id]
            )
            activeAgent = session_doc.get('activeAgent', 'unknown')
            logger.info(f"Active agent from DB: {activeAgent}")
        except Exception as e:
            logger.error(f"Error retrieving active agent from DB: {e}")
            activeAgent = "unknown"

    # If activeAgent is unknown or None, default to orchestrator
    if activeAgent in [None, "unknown"]:
        logger.info(f"activeAgent is '{activeAgent}', defaulting to Orchestrator")
        activeAgent = "orchestrator"

    return activeAgent


# ============================================================================
# Build Agent Graph
# ============================================================================

def build_agent_graph():
    """
    Build the multi-agent graph using LangGraph.

    Graph structure:
    - User input → Orchestrator (entry point)
    - Orchestrator routes via transfer_to_ tools or deterministic domain routing
    - Specialized agents (Hotel, Activity, Dining) answer the turn and return to user
    - Itinerary Generator → Orchestrator only
    - Summarizer → Orchestrator only (auto-triggered every 10 turns)
    - All agents → Human node (for user interrupts)
    """
    logger.info("🏗️  Building multi-agent graph...")

    builder = StateGraph(MessagesState)

    # Add all agent nodes
    builder.add_node("orchestrator", call_orchestrator_agent)
    builder.add_node("hotel", call_hotel_agent)
    builder.add_node("activity", call_activity_agent)
    builder.add_node("dining", call_dining_agent)
    builder.add_node("itinerary_generator", call_itinerary_generator_agent)
    builder.add_node("summarizer", call_summarizer_agent)
    builder.add_node("human", human_node)

    # Set entry point - always start with orchestrator
    builder.add_edge(START, "orchestrator")

    # Orchestrator routing - can route to any specialized agent
    builder.add_conditional_edges(
        "orchestrator",
        get_active_agent,
        {
            "hotel": "hotel",
            "activity": "activity",
            "dining": "dining",
            "itinerary_generator": "itinerary_generator",
            "summarizer": "summarizer",
            "human": "human",  # Wait for user input
            "orchestrator": "orchestrator",  # fallback
        }
    )

    # Specialist agents answer the current user turn, then return control to the user.
    # The next user turn starts at the orchestrator again, avoiding loops through
    # stale session activeAgent values after non-routing tools like recall_memories.
    builder.add_edge("hotel", "human")
    builder.add_edge("activity", "human")
    builder.add_edge("dining", "human")
    builder.add_edge("itinerary_generator", "human")

    # Summarizer routing - can only return to orchestrator
    builder.add_conditional_edges(
        "summarizer",
        get_active_agent,
        {
            "orchestrator": "orchestrator",
            "summarizer": "summarizer",  # Can stay in summarizer
        }
    )

    # Compile with checkpointer
    checkpointer = CosmosDBSaver(
        database_name=DATABASE_NAME,
        container_name=checkpoint_container
    )

    graph = builder.compile(checkpointer=checkpointer)

    logger.info("✅ Multi-agent graph built successfully")
    logger.info("📊 Graph structure:")
    logger.info("   Entry: User → Orchestrator")
    logger.info("   Orchestrator → Hotel/Activity/Dining/Itinerary/Summarizer")
    logger.info("   Hotel/Activity/Dining → Itinerary Generator or Orchestrator")
    logger.info("   Itinerary Generator → Orchestrator only")
    logger.info("   Summarizer → Orchestrator only (auto-triggered every 10 messages)")
    logger.info("   Agents: 6 total (Orchestrator, Hotel, Activity, Dining, Itinerary Generator, Summarizer)")

    return graph


# ============================================================================
# Interactive Chat Function (for CLI testing)
# ============================================================================

async def interactive_chat():
    """
    Interactive CLI for testing the travel assistant.
    Similar to banking app's interactive mode.
    """
    global local_interactive_mode
    local_interactive_mode = True

    thread_id = str(uuid.uuid4())
    # thread_id = "thread-7ab201e9-2bbc-41cc-a220-995558523a4f"
    thread_config = {
        "configurable": {
            "thread_id": thread_id,
            "userId": "Tony",
            "tenantId": "Marvel"
        }
    }

    print("\n" + "="*70)
    print("🌍 Travel Assistant - Interactive Test Mode")
    print("="*70)
    print("Type 'exit' to end the conversation")
    print("="*70 + "\n")

    # Build graph
    graph = build_agent_graph()

    user_input = input("You: ")

    while user_input.lower() != "exit":
        input_message = {"messages": [{"role": "user", "content": user_input}]}
        response_found = False

        async for update in graph.astream(input_message, config=thread_config, stream_mode="updates"):
            for node_id, value in update.items():
                if isinstance(value, dict) and value.get("messages"):
                    last_message = value["messages"][-1]
                    if isinstance(last_message, AIMessage):
                        print(f"{node_id}: {last_message.content}\n")
                        response_found = True

        if not response_found:
            logger.debug("No AI response received.")

        user_input = input("You: ")

    print("\n👋 Goodbye!")


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    # Setup agents and run interactive chat
    async def main():
        await setup_agents()
        await interactive_chat()

    asyncio.run(main())
```

</details>

<details>
    <summary>Completed code for <strong>mcp_server/mcp_http_server.py</strong></summary>

<br>

````python
import sys
import os
import logging
import json
import re
from typing import Any, Dict, List, Optional
from langsmith import traceable
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.app.services.azure_open_ai import generate_embedding, get_openai_client
from src.app.services.azure_cosmos_db import (
    create_session_record,
    get_all_user_memories, get_session_by_id,
    append_message,
    get_message_by_id,
    get_session_messages,
    get_session_summaries,
    get_user_summaries,
    create_summary,
    store_memory,
    query_memories,
    update_memory_last_used,
    supersede_memory,
    query_places_hybrid,
    create_trip,
    get_trip,
    record_api_event,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress SSE, OpenAI, urllib3, and LangSmith debug logs
logging.getLogger("sse_starlette.sse").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("langsmith.client").setLevel(logging.WARNING)

# Prompt directory
PROMPT_DIR = os.path.join(os.path.dirname(__file__), '..', 'python', 'src', 'app', 'prompts')

# Load environment variables
try:
    load_dotenv('.env', override=False)

    # Load authentication configuration
    simple_token = os.getenv("MCP_AUTH_TOKEN")
    github_client_id = os.getenv("GITHUB_CLIENT_ID")
    github_client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    base_url = os.getenv("MCP_SERVER_BASE_URL", "http://localhost:8080")

    print("🔐 Authentication Configuration:")
    print(f"   Simple Token: {'SET' if simple_token else 'NOT SET'}")
    print(f"   GitHub Client ID: {'SET' if github_client_id else 'NOT SET'}")
    print(f"   Base URL: {base_url}")

    # Determine authentication mode
    if github_client_id and github_client_secret:
        auth_mode = "github_oauth"
        print("✅ GITHUB OAUTH MODE ENABLED")
    elif simple_token:
        auth_mode = "simple_token"
        print("✅ SIMPLE TOKEN MODE ENABLED (Development)")
        print(f"   Token: {simple_token[:8]}...")
    else:
        auth_mode = "none"
        print("⚠️  NO AUTHENTICATION - All requests accepted")

except ImportError as e:
    auth_mode = "none"
    simple_token = None
    print(f"❌ OAuth dependencies not available: {e}")

# Initialize MCP server
print("\n🚀 Initializing Travel Assistant MCP Server...")
port = int(os.getenv("PORT", 8080))
mcp = FastMCP("TravelAssistantTools", host="0.0.0.0", port=port)

print(f"✅ Travel Assistant MCP server initialized")
print(f"🌐 Server will be available at: http://0.0.0.0:{port}")
print(f"📋 Authentication mode: {auth_mode.upper()}\n")


# ============================================================================
# 1. Session Management Tools
# ============================================================================

@mcp.tool()
@traceable
def create_session(
    user_id: str,
    tenant_id: str = "",
    title: str = None,
    activeAgent: str = "orchestrator"
) -> Dict[str, Any]:
    """
    Create a new conversation session with proper initialization.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier (default: empty string)
        title: Optional session title

    Returns:
        Dictionary with session details including sessionId
    """
    logger.info(f"🆕 Creating session for user: {user_id}")
    session = create_session_record(user_id, tenant_id, activeAgent, title)
    return {
        "sessionId": session["sessionId"],
        "userId": user_id,
        "title": session["title"],
        "createdAt": session["createdAt"]
    }


@mcp.tool()
@traceable
def get_session_context(
    session_id: str,
    tenant_id: str,
    user_id: str,
    include_summaries: bool = True
) -> Dict[str, Any]:
    """
    Retrieve conversation context (recent messages + summaries).

    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        include_summaries: Whether to include summaries (default: True)

    Returns:
        Dictionary with messages, summaries, and metadata
    """
    logger.info(f"📖 Getting context for session: {session_id}")

    messages = get_session_messages(session_id, tenant_id, user_id)
    session_info = get_session_by_id(session_id, tenant_id, user_id)

    result = {
        "messages": messages,
        "sessionInfo": session_info,
        "messageCount": len(messages)
    }

    if include_summaries:
        summaries = get_session_summaries(session_id, tenant_id, user_id)
        result["summaries"] = summaries
        result["summaryCount"] = len(summaries)

    return result


@mcp.tool()
@traceable
def append_turn(
    session_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    content: str,
    tool_call: Optional[Dict] = None,
    keywords: Optional[List[str]] = None,
    generate_embedding_flag: bool = True
) -> Dict[str, Any]:
    """
    Atomically store a message and update session metadata.

    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        role: Message role (user/assistant/system)
        content: Message content
        tool_call: Optional tool call information
        keywords: Optional list of keywords
        generate_embedding_flag: Whether to generate embedding (default: True)

    Returns:
        Dictionary with messageId and metadata
    """
    logger.info(f"💬 Appending {role} message to session: {session_id}")

    # Generate embedding if requested
    embedding = None
    if generate_embedding_flag and content:
        try:
            embedding = generate_embedding(content)
        except Exception as e:
            logger.warning(f"Failed to generate embedding: {e}")

    message_id = append_message(
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        content=content,
        tool_call=tool_call,
        embedding=embedding,
        keywords=keywords
    )

    return {
        "messageId": message_id,
        "sessionId": session_id,
        "role": role,
        "embeddingGenerated": embedding is not None
    }
# ============================================================================
# 2. Memory Lifecycle Tools
# ============================================================================

@mcp.tool()
@traceable
def store_user_memory(
    user_id: str,
    tenant_id: str,
    memory_type: str,
    text: str,
    facets: Dict[str, Any],
    salience: float,
    justification: str,
    generate_embedding_flag: bool = True
) -> Dict[str, Any]:
    """
    Store a user memory with appropriate TTL and indexing.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        memory_type: Type of memory (declarative/episodic/procedural)
        text: Memory text content
        facets: Structured facets (dietary, mobility, timeOfDay, etc.)
        salience: Importance score (0.0-1.0)
        justification: Source message ID or reasoning
        generate_embedding_flag: Whether to generate embedding (default: True)

    Returns:
        Dictionary with memoryId and metadata
    """
    logger.info(f"🧠 Storing {memory_type} memory for user: {user_id}")

    # Validate memory type
    if memory_type not in ["declarative", "episodic", "procedural"]:
        raise ValueError(f"Invalid memory type: {memory_type}")

    # Generate embedding if requested
    embedding = None
    if generate_embedding_flag and text:
        try:
            embedding = generate_embedding(text)
        except Exception as e:
            logger.warning(f"Failed to generate embedding: {e}")

    memory_id = store_memory(
        user_id=user_id,
        tenant_id=tenant_id,
        memory_type=memory_type,
        text=text,
        facets=facets,
        salience=salience,
        justification=justification,
        embedding=embedding
    )

    return {
        "memoryId": memory_id,
        "type": memory_type,
        "salience": salience,
        "embeddingGenerated": embedding is not None
    }


@mcp.tool()
@traceable
def recall_memories(
    user_id: str,
    tenant_id: str,
    query: str,
    min_salience: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Smart hybrid retrieval of relevant memories.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        query: Search query for semantic search
        min_salience: Minimum salience threshold (default: 0.0)

    Returns:
        List of memory dictionaries with scores and match reasons
    """
    logger.info(f"🔍 Recalling memories for user: {user_id}")
    memories = query_memories(
        user_id=user_id,
        tenant_id=tenant_id,
        query=query,
        min_salience=min_salience
    )

    # Update lastUsedAt for recalled memories to keep recency metadata fresh
    for memory in memories:
        memory_id = memory.get("memoryId") or memory.get("id")
        if memory_id:
            try:
                update_memory_last_used(
                    memory_id=memory_id,
                    user_id=user_id,
                    tenant_id=tenant_id
                )
            except Exception as e:
                logger.debug(f"Could not update lastUsedAt for memory {memory_id}: {e}")

    return memories


# ============================================================================
# 3. Summarization Tools
# ============================================================================

@mcp.tool()
@traceable
def mark_span_summarized(
    session_id: str,
    tenant_id: str,
    user_id: str,
    summary_text: str,
    span: Dict[str, str],
    supersedes: List[str],
    generate_embedding_flag: bool = True
) -> Dict[str, Any]:
    """
    Atomically create summary and set TTL on source messages.

    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        summary_text: Summary content
        span: Dictionary with fromMessageId and toMessageId
        supersedes: List of message IDs being superseded
        generate_embedding_flag: Whether to generate embedding (default: True)

    Returns:
        Dictionary with summaryId and metadata
    """
    logger.info(f"📝 Creating summary for session: {session_id}")

    # Get the last message being summarized to extract its timestamp
    to_message_id = span.get("toMessageId")
    last_message = get_message_by_id(
        message_id=to_message_id,
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id
    )

    # Extract timestamp or fallback to current time
    if last_message and last_message.get("ts"):
        last_message_ts = last_message.get("ts")
    else:
        from datetime import datetime
        last_message_ts = datetime.utcnow().isoformat() + "Z"
        logger.warning(f"Could not find timestamp for message {to_message_id}, using current time")

    # Generate embedding if requested
    embedding = None
    if generate_embedding_flag and summary_text:
        try:
            embedding = generate_embedding(summary_text)
        except Exception as e:
            logger.warning(f"Failed to generate embedding: {e}")

    summary_id = create_summary(
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        summary_text=summary_text,
        span=span,
        summary_timestamp=last_message_ts,
        embedding=embedding,
        supersedes=supersedes
    )

    return {
        "summaryId": summary_id,
        "supersededCount": len(supersedes),
        "embeddingGenerated": embedding is not None,
        "summaryTimestamp": last_message_ts
    }


@mcp.tool()
@traceable
def get_summarizable_span(
    session_id: str,
    tenant_id: str,
    user_id: str,
    min_messages: int = 10,
    retention_window: int = 10
) -> Dict[str, Any]:
    """
    Return message range suitable for summarization.

    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        min_messages: Minimum messages needed for summarization (default: 10)
        retention_window: Number of recent messages to keep (default: 10)

    Returns:
        Dictionary with span info and messages
    """
    logger.info(f"📊 Finding summarizable span for session: {session_id}")

    # Get all messages (excluding superseded ones)
    messages = get_session_messages(
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        include_superseded=False
    )

    if len(messages) < min_messages:
        return {
            "canSummarize": False,
            "reason": f"Not enough messages (have {len(messages)}, need {min_messages})",
            "messageCount": len(messages)
        }

    # Keep recent messages, summarize older ones
    # Messages are returned in DESC order, so reverse for chronological
    messages_chronological = list(reversed(messages))
    messages_to_summarize = messages_chronological[:-retention_window]

    if not messages_to_summarize:
        return {
            "canSummarize": False,
            "reason": "All messages within retention window",
            "messageCount": len(messages)
        }

    return {
        "canSummarize": True,
        "span": {
            "fromMessageId": messages_to_summarize[0]["messageId"],
            "toMessageId": messages_to_summarize[-1]["messageId"]
        },
        "messageCount": len(messages_to_summarize),
        "totalMessages": len(messages),
        "retentionWindow": retention_window
    }


@mcp.tool()
@traceable
def get_all_user_summaries(
    user_id: str,
    tenant_id: str
) -> List[Dict[str, Any]]:
    """
    Retrieve all conversation summaries for a user across all sessions.
    Useful when user asks "Show me my past trips" or "What have we discussed before?".

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier

    Returns:
        List of summary objects containing sessionId, text, and createdAt

    """
    logger.info(f"📚 Retrieving all summaries for user: {user_id}")

    summaries = get_user_summaries(
        user_id=user_id,
        tenant_id=tenant_id
    )

    # Return simplified format for agent consumption
    return [
        {
            "summaryId": s.get("summaryId"),
            "sessionId": s.get("sessionId"),
            "text": s.get("text"),
            "createdAt": s.get("createdAt"),
            "span": s.get("span")
        }
        for s in summaries
    ]


# ============================================================================
# 3.5 LLM-Based Memory Extraction & Conflict Resolution
# ============================================================================

def load_prompty_template(filename: str) -> str:
    """Load prompty file content (strips frontmatter, returns system+user sections)"""
    file_path = os.path.join(PROMPT_DIR, filename)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Remove frontmatter (--- ... ---) if present
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    content = parts[2].strip()
            return content
    except FileNotFoundError:
        logger.error(f"Prompty file not found: {file_path}")
        raise


def call_llm_with_prompt(template: str, variables: Dict[str, Any], temperature: float = 0.3) -> str:
    """
    Call Azure OpenAI with a prompt template and variables.

    Args:
        template: Prompt template with {{variable}} placeholders
        variables: Dictionary of variable values to substitute
        temperature: LLM temperature (default 0.3 for structured output)

    Returns:
        LLM response content as string (with markdown code blocks stripped if present)
    """
    client = get_openai_client()

    # Substitute variables in template
    prompt = template
    for key, value in variables.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", str(value))

    response = client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=2000
    )

    content = response.choices[0].message.content

    # Strip markdown code blocks if present (```json ... ``` or ``` ... ```)
    if content.startswith("```"):
        # Remove opening ```json or ```
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        # Remove closing ```
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    return content


_EXPLICIT_PREFERENCE_PATTERNS = [
    r"\b(i|we)\s+(am|are|have|need|prefer|like|love|hate|avoid|require|want)\b",
    r"\b(i'm|im|we're)\b",
    r"\bmy\s+(preference|preferences|diet|budget|allergy|allergies|restriction|restrictions|requirement|requirements)\b",
    r"\b(no|avoid)\s+(seafood|meat|pork|dairy|gluten|nuts|peanuts|crowds|stairs)\b",
]

_SEARCH_INTENT_PATTERN = re.compile(
    r"\b(find|show|recommend|search|suggest|where should|what should|places?|restaurants?|hotels?|activities?|museums?|attractions?)\b",
    re.IGNORECASE,
)


def _should_skip_preference_llm(message: str) -> bool:
    """Skip preference extraction for plain search requests with no explicit user preference."""
    normalized = message.strip().lower()
    if not normalized:
        return True

    has_search_intent = bool(_SEARCH_INTENT_PATTERN.search(normalized))
    has_explicit_preference = any(
        re.search(pattern, normalized, re.IGNORECASE)
        for pattern in _EXPLICIT_PREFERENCE_PATTERNS
    )

    return has_search_intent and not has_explicit_preference


@mcp.tool()
@traceable
def extract_preferences_from_message(
    message: str,
    role: str,
    user_id: str,
    tenant_id: str
) -> Dict[str, Any]:
    """
    Extract travel preferences from a user or assistant message using LLM.
    Smart enough to skip greetings, simple yes/no, and other non-preference messages.

    Args:
        message: The message text to analyze
        role: Message role (user/assistant)
        user_id: User identifier (for logging)
        tenant_id: Tenant identifier (for logging)

    Returns:
        Dictionary with:
        - shouldExtract: bool (whether to extract)
        - skipReason: str (reason if skipped)
        - preferences: list of extracted preferences with category, value, text, salience, type
    """
    logger.info(f"🔍 Extracting preferences from {role} message for user {user_id}")

    if _should_skip_preference_llm(message):
        logger.info("⏭️ Skipping preference extraction LLM for plain search request")
        return {
            "shouldExtract": False,
            "skipReason": "Plain search request without explicit new preferences",
            "preferences": []
        }

    try:
        # Load prompty template
        template = load_prompty_template("preference_extraction.prompty")

        # Call LLM
        response_text = call_llm_with_prompt(
            template=template,
            variables={"message": message, "role": role},
            temperature=0.3
        )

        # Parse JSON response
        response_json = json.loads(response_text)

        logger.info(f"✅ Extraction complete: shouldExtract={response_json.get('shouldExtract', False)}")
        return response_json

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        return {
            "shouldExtract": False,
            "skipReason": "LLM response parsing error",
            "preferences": []
        }
    except Exception as e:
        logger.error(f"Error extracting preferences: {e}")
        return {
            "shouldExtract": False,
            "skipReason": f"Error: {str(e)}",
            "preferences": []
        }


@mcp.tool()
@traceable
def resolve_memory_conflicts(
    new_preferences: List[Dict[str, Any]],
    user_id: str,
    tenant_id: str
) -> Dict[str, Any]:
    """
    Resolve conflicts between new preferences and existing memories using LLM.

    Args:
        new_preferences: List of new preferences to check
        user_id: User identifier
        tenant_id: Tenant identifier

    Returns:
        Dictionary with:
        - resolutions: list of resolution decisions for each preference
          - conflict: bool
          - conflictsWith: str (existing memory text)
          - conflictingMemoryId: str
          - severity: none/low/high
          - decision: auto-resolve/require-confirmation
          - strategy: explanation
          - action: store-new/update-existing/store-both/ask-user
    """
    logger.info(f"⚖️  Resolving conflicts for {len(new_preferences)} preferences")

    try:
        # Query existing memories
        existing_memories = get_all_user_memories(
            user_id=user_id,
            tenant_id=tenant_id
        )

        # Format existing memories for LLM
        existing_prefs_text = "\n".join([
            f"- [{mem.get('type')}] {mem.get('text')} (salience: {mem.get('salience')}, id: {mem.get('memoryId')})"
            for mem in existing_memories
        ])

        # Format new preferences for LLM
        new_prefs_text = json.dumps(new_preferences, indent=2)

        # Load prompty template
        template = load_prompty_template("memory_conflict_resolution.prompty")

        # Call LLM
        response_text = call_llm_with_prompt(
            template=template,
            variables={
                "existing_preferences": existing_prefs_text,
                "new_preferences": new_prefs_text
            },
            temperature=0.3
        )

        # Parse JSON response
        response_json = json.loads(response_text)

        # Count severity levels
        high_severity_count = sum(1 for r in response_json.get("resolutions", []) if r.get("severity") == "high")
        low_severity_count = sum(1 for r in response_json.get("resolutions", []) if r.get("severity") == "low")

        logger.info(f"✅ Conflict resolution complete: {high_severity_count} high, {low_severity_count} low severity")

        return response_json

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        return {"resolutions": []}
    except Exception as e:
        logger.error(f"Error resolving conflicts: {e}")
        return {"resolutions": []}


@mcp.tool()
@traceable
def store_resolved_preferences(
    resolutions: List[Dict[str, Any]],
    user_id: str,
    tenant_id: str,
    justification: str
) -> Dict[str, Any]:
    """
    Store preferences that have been auto-resolved (no user confirmation needed).
    Skip preferences that require user confirmation.

    Args:
        resolutions: List of resolution decisions from resolve_memory_conflicts
        user_id: User identifier
        tenant_id: Tenant identifier
        justification: Source message ID or reasoning

    Returns:
        Dictionary with:
        - stored: list of stored memory IDs
        - needsConfirmation: list of preferences requiring user confirmation
        - superseded: list of old memory IDs that were marked as superseded
    """
    logger.info(f"💾 Storing resolved preferences for user {user_id}")

    stored = []
    needs_confirmation = []
    superseded = []

    try:
        for resolution in resolutions:
            decision = resolution.get("decision")
            action = resolution.get("action")
            new_pref = resolution.get("newPreference", {})

            if decision == "require-confirmation":
                # Skip and add to confirmation list
                needs_confirmation.append({
                    "preference": new_pref,
                    "conflict": resolution.get("conflictsWith"),
                    "strategy": resolution.get("strategy")
                })
                logger.info(f"⏸️  Skipping preference (needs confirmation): {new_pref.get('text')}")
                continue

            # Auto-resolve actions
            if action == "store-new":
                # Store new preference
                memory_id = store_memory(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    memory_type=new_pref.get("type", "declarative"),
                    text=new_pref.get("text"),
                    facets={new_pref.get("category"): {"value": new_pref.get("value")}},
                    salience=new_pref.get("salience", 0.7),
                    justification=justification,
                    embedding=generate_embedding(new_pref.get("text")) if new_pref.get("text") else None
                )
                stored.append(memory_id)
                logger.info(f"✅ Stored new preference: {memory_id}")

            elif action == "update-existing":
                # Mark old as superseded and store new
                old_memory_id = resolution.get("conflictingMemoryId")

                # Store new preference first
                memory_id = store_memory(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    memory_type=new_pref.get("type", "declarative"),
                    text=new_pref.get("text"),
                    facets={new_pref.get("category"): {"value": new_pref.get("value")}},
                    salience=new_pref.get("salience", 0.7),
                    justification=justification,
                    embedding=generate_embedding(new_pref.get("text")) if new_pref.get("text") else None
                )
                stored.append(memory_id)
                logger.info(f"✅ Stored updated preference: {memory_id}")

                # Now supersede the old memory
                if old_memory_id:
                    success = supersede_memory(
                        memory_id=old_memory_id,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        superseded_by=memory_id
                    )
                    if success:
                        superseded.append(old_memory_id)
                        logger.info(f"🔄 Superseded old memory: {old_memory_id} with {memory_id}")
                    else:
                        logger.warning(f"⚠️ Failed to supersede old memory: {old_memory_id}")

            elif action == "store-both":
                # Store new preference (old one remains)
                memory_id = store_memory(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    memory_type=new_pref.get("type", "declarative"),
                    text=new_pref.get("text"),
                    facets={new_pref.get("category"): {"value": new_pref.get("value")}},
                    salience=new_pref.get("salience", 0.7),
                    justification=justification,
                    embedding=generate_embedding(new_pref.get("text")) if new_pref.get("text") else None
                )
                stored.append(memory_id)
                logger.info(f"✅ Stored complementary preference: {memory_id}")

        return {
            "stored": stored,
            "needsConfirmation": needs_confirmation,
            "superseded": superseded,
            "storedCount": len(stored),
            "confirmationCount": len(needs_confirmation)
        }

    except Exception as e:
        logger.error(f"Error storing preferences: {e}")
        return {
            "stored": stored,
            "needsConfirmation": needs_confirmation,
            "superseded": superseded,
            "error": str(e)
        }


# ============================================================================
# 4. Place Discovery Tools
# ============================================================================

@mcp.tool()
@traceable
def discover_places(
        geo_scope: str,
        query: str,
        user_id: str,
        tenant_id: str = "",
        filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Memory-aware place search with hybrid RRF retrieval (for chat assistant).

    Args:
        geo_scope: Geographic scope (e.g., "barcelona")
        query: Natural language search query
        user_id: User identifier (for memory alignment)
        tenant_id: Tenant identifier
        filters: Optional filters dict with:
            - type: "hotel" | "restaurant" | "attraction" (optional)
            - dietary: ["vegan", "seafood"] (optional)
            - accessibility: ["wheelchair-friendly"] (optional)
            - priceTier: "budget" | "moderate" | "luxury" (optional)

    Returns:
        List of places with match reasons and memory alignment scores
    """
    logger.info(f"🗺️  ========== DISCOVER_PLACES TOOL CALLED ==========")
    logger.info(f"🗺️  Parameters:")
    logger.info(f"     - geo_scope: {geo_scope}")
    logger.info(f"     - query: {query}")
    logger.info(f"     - user_id: {user_id}")
    logger.info(f"     - tenant_id: {tenant_id}")
    logger.info(f"     - filters: {filters}")

    # Parse filters
    filters = filters or {}
    place_type = filters.get("type")
    dietary = filters.get("dietary", [])
    accessibility = filters.get("accessibility", [])
    price_tier = filters.get("priceTier")

    # Convert single values to lists if needed
    if dietary and not isinstance(dietary, list):
        dietary = [dietary]
    if accessibility and not isinstance(accessibility, list):
        accessibility = [accessibility]

    logger.info(f"🔍 Parsed filters: type={place_type}, dietary={dietary}, access={accessibility}, price={price_tier}")

    # Query places using hybrid RRF search
    try:
        places = query_places_hybrid(
            query=query,
            geo_scope_id=geo_scope,
            place_type=place_type,
            dietary=dietary,
            accessibility=accessibility,
            price_tier=price_tier,
            limit=10
        )
        logger.info(f"✅ Hybrid RRF returned {len(places)} results")
    except Exception as e:
        logger.error(f"❌ Error in hybrid search: {e}")
        import traceback
        logger.error(f"{traceback.format_exc()}")
        return []

    # Memory alignment scoring uses filters the caller already provided.
    # Deterministic specialist nodes query places directly; this MCP tool is
    # retained for LLM-backed flows that pass explicit filters into discovery.
    for place in places:
        alignment_score = 0.0
        match_reasons = ["Hybrid search match (text + semantic)"]

        # Dietary alignment from filters
        if dietary:
            place_dietary = place.get("dietary", [])
            for d in dietary:
                if d in place_dietary:
                    alignment_score += 0.3
                    match_reasons.append(f"Matches {d} dietary preference")

        # Price tier alignment from filters
        if price_tier:
            place_price = place.get("priceTier")
            if price_tier == place_price:
                alignment_score += 0.2
                match_reasons.append(f"Matches {place_price} price preference")

        # Accessibility alignment from filters
        if accessibility:
            place_access = place.get("accessibility", [])
            for a in accessibility:
                if a in place_access:
                    alignment_score += 0.3
                    match_reasons.append(f"Accessible: {a}")

        place["memoryAlignment"] = min(alignment_score, 1.0)
        place["matchReasons"] = match_reasons

    logger.info(f"✅ Returning {len(places)} places with filter-based alignment")
    return places


# ============================================================================
# 5. Trip Management Tools
# ============================================================================

@mcp.tool()
@traceable
def create_new_trip(
        user_id: str,
        tenant_id: str,
        destination: str,
        start_date: str,
        end_date: str,
        days: Optional[List[Dict[str, Any]]] = None,
        trip_duration: Optional[int] = None
) -> Dict[str, Any]:
    """
    Create a new trip itinerary.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        destination: Trip destination (e.g. "Barcelona, Spain")
        start_date: Trip start date in ISO format (e.g. "2026-03-10")
        end_date: Trip end date in ISO format (e.g. "2026-03-11")
        days: Optional list of day-by-day itinerary (dayNumber, date, morning, lunch, afternoon, dinner, accommodation)
        trip_duration: Optional total number of days (calculated from days array if not provided)

    Returns:
        Dictionary with tripId and details
    """
    logger.info(f"🎒 Creating trip for user: {user_id} with {len(days or [])} days")

    trip_id = create_trip(
        user_id=user_id,
        tenant_id=tenant_id,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        days=days or [],
        trip_duration=trip_duration
    )

    return {
        "tripId": trip_id,
        "destination": destination,
        "startDate": start_date,
        "endDate": end_date,
        "tripDuration": trip_duration or len(days or []),
        "daysCount": len(days or [])
    }


@mcp.tool()
@traceable
def get_trip_details(
        trip_id: str,
        user_id: str,
        tenant_id: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Get trip details by ID.

    Args:
        trip_id: Trip identifier
        user_id: User identifier
        tenant_id: Tenant identifier

    Returns:
        Trip dictionary or None if not found
    """
    logger.info(f"📋 Getting trip: {trip_id}")
    return get_trip(trip_id, user_id, tenant_id)


@mcp.tool()
@traceable
def update_trip(
        trip_id: str,
        user_id: str,
        tenant_id: str,
        updates: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Update trip details (add days, modify constraints, etc.).

    Args:
        trip_id: Trip identifier
        user_id: User identifier
        tenant_id: Tenant identifier
        updates: Dictionary of fields to update

    Returns:
        Updated trip dictionary
    """
    logger.info(f"📝 Updating trip: {trip_id}")

    # Get existing trip
    trip = get_trip(trip_id, user_id, tenant_id)
    if not trip:
        raise ValueError(f"Trip {trip_id} not found")

    # Apply updates
    trip.update(updates)

    # Save to Cosmos DB
    from src.app.services.azure_cosmos_db import trips_container
    if trips_container:
        trips_container.upsert_item(trip)

    return trip


# ============================================================================
# 6. Cross-Thread Search Tools
# ============================================================================

@mcp.tool()
@traceable
def search_user_threads(
        user_id: str,
        tenant_id: str,
        query: str,
        mode: str = "hybrid",
        since: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Hybrid search across user's conversation history.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        query: Search query
        mode: Search mode (hybrid/semantic/fulltext)
        since: Optional ISO date to filter recent conversations

    Returns:
        List of matches grouped by thread with scores
    """
    logger.info(f"🔍 Searching user threads for: {query}")

    from src.app.services.azure_cosmos_db import messages_container

    if not messages_container:
        return []

    # Generate query embedding for semantic search
    query_embedding = None
    if mode in ["hybrid", "semantic"]:
        try:
            query_embedding = generate_embedding(query)
        except Exception as e:
            logger.warning(f"Failed to generate query embedding: {e}")

    # Search messages (simplified - full implementation would use vector search)
    query_filter = """
    SELECT TOP 10 c.threadId, c.messageId, c.content, c.ts, c.role
    FROM c
    WHERE c.userId = @userId
    AND c.tenantId = @tenantId
    AND CONTAINS(LOWER(c.content), LOWER(@query))
    ORDER BY c.ts DESC
    """

    params = [
        {"name": "@userId", "value": user_id},
        {"name": "@tenantId", "value": tenant_id},
        {"name": "@query", "value": query},
    ]

    if since:
        query_filter = query_filter.replace(
            "ORDER BY",
            "AND c.ts >= @since ORDER BY"
        )
        params.append({"name": "@since", "value": since})

    results = list(messages_container.query_items(
        query=query_filter,
        parameters=params,
        enable_cross_partition_query=True
    ))

    # Group by thread
    threads_map = {}
    for msg in results:
        thread_id = msg["threadId"]
        if thread_id not in threads_map:
            threads_map[thread_id] = {
                "threadId": thread_id,
                "matches": [],
                "totalScore": 0.0
            }

        threads_map[thread_id]["matches"].append({
            "messageId": msg["messageId"],
            "content": msg["content"],
            "timestamp": msg["ts"],
            "role": msg["role"],
            "score": 0.8  # Placeholder
        })
        threads_map[thread_id]["totalScore"] += 0.8

    return list(threads_map.values())


# ============================================================================
# 7. API Event Tools
# ============================================================================

@mcp.tool()
@traceable
def record_api_call(
    session_id: str,
    tenant_id: str,
    provider: str,
    operation: str,
    request: Dict[str, Any],
    response: Dict[str, Any],
    keywords: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Store API event with auto-extracted keywords.

    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        provider: API provider name (e.g., "FlightsAPI")
        operation: Operation name (e.g., "search")
        request: Request parameters
        response: Response data
        keywords: Optional list of keywords

    Returns:
        Dictionary with eventId and metadata
    """
    logger.info(f"📡 Recording API call: {provider}.{operation}")

    event_id = record_api_event(
        session_id=session_id,
        tenant_id=tenant_id,
        provider=provider,
        operation=operation,
        request=request,
        response=response,
        keywords=keywords
    )

    return {
        "eventId": event_id,
        "provider": provider,
        "operation": operation
    }


# ============================================================================
# 9. Agent Transfer Tools (for Orchestrator Routing)
# ============================================================================

@mcp.tool()
@traceable
def transfer_to_hotel(
    reason: str
) -> str:
    """
    Transfer conversation to the Hotel Agent.

    Use this when:
    - User wants to search for hotels or accommodations
    - User is sharing hotel/lodging preferences (boutique, quiet, central, etc.)
    - User asks about places to stay

    Examples:
    - "Find hotels in Paris"
    - "I prefer quiet hotels away from tourist areas"
    - "Where should I stay?"

    Args:
        reason: Why you're transferring to this agent

    Returns:
        JSON with goto field for routing
    """

    logger.info(f"🔄 Transfer to Hotel Agent: {reason}")

    return json.dumps({
        "goto": "hotel",
        "reason": reason,
        "message": "Transferring to Hotel Agent to find accommodations for you."
    })


@mcp.tool()
@traceable
def transfer_to_activity(
    reason: str
) -> str:
    """
    Transfer conversation to the Activity Agent.

    Use this when:
    - User wants to discover attractions, museums, landmarks
    - User is sharing activity preferences (art, history, nature, etc.)
    - User asks about things to do or see

    Examples:
    - "What should I do in Barcelona?"
    - "Find art museums"
    - "I love history and architecture"

    Args:
        reason: Why you're transferring to this agent

    Returns:
        JSON with goto field for routing
    """

    logger.info(f"🔄 Transfer to Activity Agent: {reason}")

    return json.dumps({
        "goto": "activity",
        "reason": reason,
        "message": "Transferring to Activity Agent to discover attractions for you."
    })


@mcp.tool()
@traceable
def transfer_to_dining(
    reason: str
) -> str:
    """
    Transfer conversation to the Dining Agent.

    Use this when:
    - User wants restaurant or cafe recommendations
    - User is sharing dietary preferences or cuisine interests
    - User asks where to eat

    Examples:
    - "Find vegetarian restaurants"
    - "I'm pescatarian and like local bistros"
    - "Where should I have dinner?"

    Args:
        reason: Why you're transferring to this agent

    Returns:
        JSON with goto field for routing
    """

    logger.info(f"🔄 Transfer to Dining Agent: {reason}")

    return json.dumps({
        "goto": "dining",
        "reason": reason,
        "message": "Transferring to Dining Agent to find restaurants for you."
    })


@mcp.tool()
@traceable
def transfer_to_itinerary_generator(
    reason: str
) -> str:
    """
    Transfer conversation to the Itinerary Generator agent.

    Use this when:
    - User explicitly requests an itinerary or day-by-day plan
    - User says "create itinerary", "plan my days", "generate schedule"
    - User wants a complete trip plan synthesized

    Examples:
    - "Create an itinerary for my trip"
    - "Plan my 4 days in Paris"
    - "Generate a schedule with everything we discussed"

    Args:
        reason: Why you're transferring to this agent

    Returns:
        JSON with goto field for routing
    """

    logger.info(f"🔄 Transfer to Itinerary Generator: {reason}")

    return json.dumps({
        "goto": "itinerary_generator",
        "reason": reason,
        "message": "Transferring to Itinerary Generator to create your day-by-day plan."
    })


@mcp.tool()
@traceable
def transfer_to_summarizer(
    reason: str
) -> str:
    """
    Transfer conversation to the Summarizer agent.

    Use this when:
    - User asks for a recap or summary of the conversation
    - Conversation has become long (12+ turns)
    - User wants to review what's been discussed or planned

    Examples:
    - "Summarize our conversation"
    - "What have we planned so far?"
    - "Give me a recap"

    Args:
        reason: Why you're transferring to this agent

    Returns:
        JSON with goto field for routing
    """

    logger.info(f"🔄 Transfer to Summarizer: {reason}")

    return json.dumps({
        "goto": "summarizer",
        "reason": reason,
        "message": "Transferring to Summarizer to compress and recap our conversation."
    })


@mcp.tool()
@traceable
def transfer_to_orchestrator(
    reason: str
) -> str:
    """
    Transfer conversation back to the Orchestrator agent.

    Use this when:
    - Task is complete and user needs general assistance
    - User has a new question that doesn't fit specialized agents
    - General conversation, greetings, clarifications needed

    Examples:
    - After completing a specific task
    - User says "Thanks" or changes topic
    - User asks general questions about the system

    Args:
        reason: Why you're transferring to this agent

    Returns:
        JSON with goto field for routing
    """

    logger.info(f"🔄 Transfer to Orchestrator: {reason}")

    return json.dumps({
        "goto": "orchestrator",
        "reason": reason,
        "message": "Transferring back to Orchestrator for general assistance."
    })


# ============================================================================
# Server Startup
# ============================================================================

if __name__ == "__main__":
    print("Starting Banking Tools MCP server...")

    # Configure server options
    server_options = {
        "transport": "streamable-http"
    }

    print("Starting server without built-in authentication...")
    print("💡 For OAuth, use a reverse proxy like nginx or API gateway")

    try:
        mcp.run(**server_options)
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        sys.exit(1)
````

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/orchestrator.prompty</strong></summary>

<br>

```text
---
name: Orchestrator Agent
description: Routes user requests to appropriate specialized agents and extracts preferences
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Orchestrator for a multi-agent travel planning system. Your job is to analyze user messages, extract travel preferences, and route requests to appropriate specialized agents.

# Core Responsibilities (In Order)
1. **Extract and Store Preferences** - Check if the user message contains travel preferences
2. **Route requests** - Use transfer_to_* tools based on user intent
3. **Coordinate agent flow** - Decide which agent handles each request
4. **Handle general conversation** - Greetings, clarifications, thanks
5. **Never plan trips yourself** - Always delegate to specialists

# Step 1: Check for Preferences (ONLY WHEN PRESENT)

Before routing, quickly assess whether the user's message contains explicit travel preferences.

**Call `extract_preferences_from_message` ONLY when the message contains:**
- Dietary statements ("I'm vegan", "gluten-free", "no seafood")
- Accessibility needs ("wheelchair accessible", "mobility assistance")
- Budget/price preferences ("luxury", "budget-friendly", "under $200")
- Style preferences ("boutique hotels", "outdoor activities", "fine dining")
- Explicit likes/dislikes ("I love museums", "I hate crowds")
- Cuisine preferences ("I prefer Italian food", "I'm into street food")

**SKIP preference extraction and go directly to Step 2 (routing) when:**
- Trip planning requests ("recommend a 3-day itinerary for NYC")
- Place search requests ("find hotels in Barcelona", "what museums should I visit?")
- Greetings ("hi", "hello", "thanks", "goodbye")
- Confirmations ("yes", "save it", "go ahead", "sure", "sounds good")
- Follow-up questions ("what about Day 2?", "any other options?", "tell me more")
- Saved-preference questions ("what are my hotel preferences?", "what dietary restrictions do I have?")
- System questions ("what can you do?", "how does this work?")
- Itinerary modifications ("move Sagrada Familia to Day 1", "add this to my trip")

This optimization avoids unnecessary tool calls and speeds up response time significantly.

## A. Extract Preferences (only when message contains preferences)
Call `extract_preferences_from_message` with:
- `message`: The user's message text
- `role`: "user"
- `user_id`: Use the userId from context
- `tenant_id`: Use the tenantId from context

**Example**:
{
  "name": "extract_preferences_from_message",
  "arguments": {
    "message": "I'm vegan and need wheelchair access",
    "role": "user",
    "user_id": "<from context>",
    "tenant_id": "<from context>"
  }
}

## B. If Preferences Found (shouldExtract: true)
Call `resolve_memory_conflicts` with the extracted preferences:
{
  "name": "resolve_memory_conflicts",
  "arguments": {
    "new_preferences": [...],  // from extraction result
    "user_id": "<from context>",
    "tenant_id": "<from context>"
  }
}

## C. Store or Confirm
Call `store_resolved_preferences` with the resolutions:
{
  "name": "store_resolved_preferences",
  "arguments": {
    "resolutions": [...],  // from conflict resolution
    "user_id": "<from context>",
    "tenant_id": "<from context>",
    "justification": "<session_id or message context>"
  }
}

## D. Handle Conflicts Requiring Confirmation
If `store_resolved_preferences` returns `needsConfirmation` with items:
- **STOP routing** to specialists
- **Ask the user to clarify** the conflict
- **Wait for their response** before proceeding

**Example response**:
"I noticed you previously mentioned you're vegetarian, but now you said you love steak. Has your preference changed, or is this specific to a particular occasion?"

## E. If No Preferences or Auto-Resolved
- Proceed to Step 2 (Route to specialists)

**Important Notes**:
- Greetings like "Hello" will have `shouldExtract: false` - that's expected
- Simple yes/no responses will be skipped - that's fine
- Only actual preference statements will be extracted
- This process takes 1-2 seconds but ensures preferences are never lost

# Step 2: Route to Specialists

If the user asks what preferences, dietary restrictions, accessibility needs, or travel requirements are saved, answer directly by calling `recall_memories`. Do not transfer these questions to Hotel, Activity, or Dining; the deterministic specialist nodes are for recommendations in a destination.

## Available Specialized Agents
- **Hotel Agent**: Accommodation searches (preferences already stored by you)
- **Activity Agent**: Attraction searches (preferences already stored by you)
- **Dining Agent**: Restaurant searches (preferences already stored by you)
- **Itinerary Generator**: Synthesizes all gathered information into day-by-day plans
- **Summarizer**: Conversation compression and recaps (auto-triggered every 10 turns)

## Routing Rules

### Transfer to Hotel Agent (`transfer_to_hotel`)
**Use when**: User asks about accommodations, lodging, places to stay
- "Find hotels in Barcelona"
- "Where should I stay?"
- "Show me boutique hotels with pools"

### Transfer to Activity Agent (`transfer_to_activity`)
**Use when**: User asks about attractions, things to do, sightseeing
- "What museums should I visit?"
- "Show me outdoor activities"
- "Find family-friendly attractions"

### Transfer to Dining Agent (`transfer_to_dining`)
**Use when**: User asks about restaurants, food, dining, cuisine
- "Find vegetarian restaurants"
- "Where should I eat dinner?"
- "Show me Italian restaurants"

### Transfer to Itinerary Generator (`transfer_to_itinerary_generator`)
**Use when**: User wants complete trip plan or day-by-day schedule
- "Create a 3-day itinerary for Paris"
- "Plan my Barcelona trip"
- "Generate a day-by-day schedule"

### Summarizer Agent (Auto-Triggered)
**NEVER manually route to summarizer** - it auto-triggers every 10 messages
- Compresses conversation history in the background
- User never sees this happening
- Conversation continues seamlessly

### When Summarizer Returns Control to You
**Context**: The summarizer operates in two modes:
1. **Mode 1 (Auto)**: Background compression every 20 messages - INVISIBLE to user
2. **Mode 2 (User-Requested)**: User explicitly asked for summary - VISIBLE to user

**Your Response Based on Mode**:

**Mode 1 - Auto-Summarization (CRITICAL INSTRUCTION)**:
When summarizer transfers back with reason: "Background summarization complete, returning to user query"
- **DO NOT acknowledge the summarization** - The user should never know it happened
- **DO NOT respond with** "I've saved a summary" or mention summarization at all
- **Immediately analyze the user's MOST RECENT message** (the one that triggered summarization)
- **Route to the appropriate specialist** based on that message
- **Act as if summarization never happened** - it's a transparent background operation

**Example (Mode 1 - Correct Behavior)**:

User: "Show me some day trips" (message 21 - triggers auto-summarization)
Summarizer: [Compresses messages 1-20 in background]
Summarizer: transfer_to_orchestrator(reason="Background summarization complete, returning to user query")
YOU: [Analyze "Show me some day trips"] → transfer_to_activity(reason="User requested day trips")
User sees: [Day trip recommendations from Activity Agent]
DO NOT say: "I've saved a summary of our conversation. How else can I assist?"


**Mode 2 - User-Requested Summary (Different Behavior)**:
When summarizer transfers back with reason: "User summary retrieval complete"
- The user ASKED for a summary, so they already saw it
- You can acknowledge: "Is there anything else I can help you with?"
- Or simply wait for their next request

## Conversational Responses

For greetings, thanks, and general conversation:
- Respond naturally without routing
- "Hello! I'd be happy to help you plan your trip. Would you like to find hotels, restaurants, activities, or create an itinerary?"
- "You're welcome! Is there anything else I can help you with?"

## Important Rules
- **Memory extraction happens FIRST** before any routing
- **Don't store memories yourself** - the extraction tools handle this
- **Specialists don't store memories** - you already did that
- **Route immediately after extraction** - don't delay
- **Handle conflicts before routing** - clarify contradictions first
- **Be transparent about updates** - "I've noted your vegetarian preference"

# Examples

User: "Hi, I'm planning a trip to Barcelona"
1. Call extract_preferences_from_message → shouldExtract: false (greeting)
2. Respond naturally and ask what they need

User: "I'm vegetarian"
1. Call extract_preferences_from_message → shouldExtract: true, preferences: [{category: "dietary", value: "vegetarian", ...}]
2. Call resolve_memory_conflicts → no conflicts
3. Call store_resolved_preferences → stored successfully
4. Respond: "I've noted that you're vegetarian. Would you like me to find restaurants, hotels, or activities for your trip?"

User: "Find hotels in Barcelona"
1. Call extract_preferences_from_message → shouldExtract: false (search request, not preference)
2. Transfer to hotel agent

User: "What are my hotel preferences?"
1. Call extract_preferences_from_message → shouldExtract: false (query, not new preference)
2. Call recall_memories and summarize the saved hotel-related preferences
```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/summarizer.prompty</strong></summary>

<br>

```text
# Role
You are the **Summarizer**. You have two main responsibilities:
1. **Auto-summarization**: Compress long conversations every 10+ turns to keep context manageable
2. **User-requested recaps**: Show summaries when users ask "What have we discussed?" or "Show my past trips"

# Core Responsibilities
- **Identify key points**: Preferences shared (lodging, activity, dining), places discussed, plans made
- **Create structured summaries**: Organized by domain (hotels, activities, restaurants, itineraries)
- **Mark messages as summarized** using mark_span_summarized tool
- **Extract action items**: Bookings needed, decisions pending
- **Retrieve user summaries**: Show past conversation summaries when requested
- **ALWAYS save summaries**: Both modes must save summaries to database using create_summary tool

# CRITICAL RULE: Auto-Summarization is INVISIBLE

**When auto-triggered (Mode 1):**
- Summarize silently in the background
- Store the summary in the database using mark_span_summarized tool
- Transfer back to orchestrator IMMEDIATELY
- DO NOT show summary content to the user
- DO NOT add any response about summarization
- Let orchestrator handle the user's query

**When user explicitly asks (Mode 2):**
- "Show me my past trips"
- "What have we discussed?"
- "Give me a recap"
- Retrieve existing summaries from database
- Store the new summary using mark_span_summarized tool
- THEN show formatted summaries to the user

# EXECUTION FLOW FOR MODE 1 (MOST IMPORTANT)

When auto-triggered, you MUST execute these tool calls in this exact order:

**Step 1: Check span**

{"name": "get_summarizable_span", "arguments": {"session_id": "...", "tenant_id": "...", "user_id": "...", "min_messages": 20, "retention_window": 10}}


**Step 2: If canSummarize is true, get context**

{"name": "get_session_context", "arguments": {"session_id": "...", "tenant_id": "...", "user_id": "..."}}


**Step 3: Generate summary text (in your reasoning)**
Example: "User planning Paris trip May 9-11. Preferences: luxury hotels. Discussed: Mandarin Oriental, Le Bristol. Requested restaurant recommendations."

**Step 4: MANDATORY - Call mark_span_summarized**

{
  "name": "mark_span_summarized",
  "arguments": {
    "session_id": "session_abc123",
    "tenant_id": "marvel",
    "user_id": "peter",
    "summary_text": "User planning Paris trip May 9-11. Preferences: luxury hotels...",
    "span": {"fromMessageId": "msg_001", "toMessageId": "msg_010"},
    "supersedes": ["msg_001", "msg_002", "msg_003", "msg_004", "msg_005", "msg_006", "msg_007", "msg_008", "msg_009", "msg_010"],
    "generate_embedding_flag": true
  }
}


**Step 5: Transfer back (NO user message)**

{"name": "transfer_to_orchestrator", "arguments": {"reason": "Background summarization complete"}}


**DO NOT skip step 4!** The mark_span_summarized tool automatically saves the summary to the database.

# Two Modes of Operation

## Mode 1: Auto-Summarization (Background Compression)
Triggered every 10+ conversation turns to compress older messages.

**CRITICAL: This is a BACKGROUND operation - DO NOT show summary to user!**

### Workflow (Execute ALL steps in order):
1. **Check if summarization needed** → `get_summarizable_span()`
   - If `canSummarize: false` → Transfer to orchestrator immediately
   - If `canSummarize: true` → CONTINUE to step 2

2. **Get conversation context** → `get_session_context(session_id, tenant_id, user_id)`
   - Retrieve all messages in the span
   - Analyze conversation content

3. **Generate compact summary text**:
   - Preferences mentioned: "User discussed [preferences]"
   - Places discussed: "[hotel/restaurant/activity names]"
   - Decisions made: "[bookings, selections]"
   - Keep it under 200 words

4. **Mark span as summarized** → `mark_span_summarized()` **MANDATORY - DO NOT SKIP**
   - Arguments:
     - session_id: from context
     - tenant_id: from context
     - user_id: from context
     - summary_text: the compact summary you generated in step 3
     - span: from get_summarizable_span result
     - supersedes: list of message IDs from span
     - generate_embedding_flag: true
   - This tool AUTOMATICALLY saves to database (no need for separate create_summary call)

5. **Transfer back immediately** → `transfer_to_orchestrator()`
   - Reason: "Background summarization complete, returning to user query"
   - DO NOT show summary to user
   - Let orchestrator handle user's query

**CRITICAL**: You MUST call `mark_span_summarized` in Mode 1. This is where the summary gets saved!

**What the user sees:**
- User: "What else can you recommend?" (10th message)
- System: Auto-summarizes in background (invisible)
- Assistant: "Here are some recommendations..." (responds to query normally)

**What happens behind the scenes:**
- Summarizer compresses messages 1-10
- Saves summary to database
- Marks messages as superseded
- Returns control to orchestrator
- Orchestrator responds to user's query

## Mode 2: User-Requested Summaries (Historical Recap)
Triggered when user asks to see past conversations or trip summaries.

### User Intent Examples:
- "Show me my past trip summaries"
- "What trips have we discussed before?"
- "Remind me of our previous conversations"
- "What have we planned in the past?"
- "Give me a recap of all our discussions"

### Workflow:
1. **Retrieve all user summaries** → `get_all_user_summaries(userId, tenantId)`
2. **Generate new summary for current session** → Create structured summary
3. **Save to database** → `create_summary()` with summary data
4. **Format for readability** → Group by session, show dates
5. **Present to user** → Clear, chronological list
6. **Return to orchestrator** → `transfer_to_orchestrator()`

### Example Output Format for Historical Summaries:

**Your Past Trip Planning Sessions**

📅 Session: October 15, 2025 (session_abc123)
🏨 Lodging: Searched for boutique hotels in Barcelona, preferred rooftop bars
🎭 Activities: Focused on architecture (Sagrada Familia, Park Güell)
🍽️ Dining: Vegetarian restaurants, outdoor seating preferred
📋 Created: 3-day Barcelona itinerary (trip_2025_bar)

📅 Session: September 20, 2025 (session_xyz789)
🏨 Lodging: Luxury hotels in Paris, proximity to museums
🎭 Activities: Art museums (Louvre, Orsay), Seine river cruise
🍽️ Dining: French bistros, late dinners (9pm+)
📋 Created: 5-day Paris itinerary (trip_2025_par)

---
Found 2 past planning sessions. Would you like details about any specific trip?


# Workflow

## Auto-Summarization Workflow (Mode 1) - BACKGROUND ONLY

### 1. Check Summarizable Span

{
  "name": "get_summarizable_span",
  "arguments": {
    "session_id": "session_abc123",
    "tenant_id": "marvel",
    "user_id": "peter",
    "min_messages": 20,
    "retention_window": 10
  }
}


Result will indicate if summarization is possible.

### 2. Get Conversation Context (if canSummarize is true)

{
  "name": "get_session_context",
  "arguments": {
    "session_id": "session_abc123",
    "tenant_id": "marvel",
    "user_id": "peter"
  }
}


### 3. Generate Summary (For Database Storage Only)
Create compact summary with key information:

**Summary text (stored in DB):**
"User planning Paris trip May 9-11. Preferences: luxury hotels. Hotels discussed: Mandarin Oriental, Le Bristol, Ritz, Peninsula, Four Seasons. Requested restaurant recommendations. No dietary restrictions mentioned."

**DO NOT show this to the user - it's for database storage only!**

### 4. Mark Span as Summarized (MANDATORY - This saves to database)

{
  "name": "mark_span_summarized",
  "arguments": {
    "session_id": "session_abc123",
    "tenant_id": "marvel",
    "user_id": "peter",
    "summary_text": "User planning Paris trip May 9-11. Preferences: luxury hotels. Hotels discussed: Mandarin Oriental, Le Bristol, Ritz, Peninsula, Four Seasons. Requested restaurant recommendations. No dietary restrictions mentioned.",
    "span": {
      "fromMessageId": "msg_001",
      "toMessageId": "msg_010"
    },
    "supersedes": ["msg_001", "msg_002", "msg_003", "msg_004", "msg_005", "msg_006", "msg_007", "msg_008", "msg_009", "msg_010"],
    "generate_embedding_flag": true
  }
}


**Note**: mark_span_summarized automatically saves to database. No need for separate create_summary call.

### 5. Transfer Back Immediately (NO USER MESSAGE)

{
  "name": "transfer_to_orchestrator",
  "arguments": {"reason": "Background summarization complete, returning to user query"}
}


## User-Requested Summary Workflow (Mode 2) - SHOW TO USER


**Summary of Our Conversation**

🏨 Lodging Preferences (Hotel Agent):
- Room type: Suite
- Amenities: Pool, WiFi, Rooftop bar
- Price range: $200-$300/night
- Location: City center, near metro

🎭 Activity Preferences (Activity Agent):
- Categories: Architecture, History, Art
- Duration: 2-3 hour visits preferred
- Accessibility: Wheelchair accessible required
- Style: Outdoor activities over indoor

🍽️ Dining Preferences (Dining Agent):
- Dietary: Vegetarian (strict)
- Cuisines: Italian, Local, Mediterranean
- Seating: Outdoor preferred
- Meal timing: Late dinners (8-10pm)

📋 Itineraries Created:
- Barcelona 3-Day Trip (June 15-17, 2024) - Trip ID: abc123
  - Day 1: Cotton House Hotel, Gothic Quarter, Teresa Carles
  - Day 2: Sagrada Familia, Park Güell, Flax & Kale
  - Day 3: Barceloneta Beach, Check-out

🔍 Places Discussed:
- Hotels: Cotton House Hotel (selected), Hotel Arts (considered)
- Activities: Sagrada Familia, Park Güell, Gothic Quarter
- Restaurants: Teresa Carles, Flax & Kale, Rasoterra

⏳ Pending Decisions:
- Confirm booking for Cotton House Hotel
- Choose dinner restaurant for Day 3


## User-Requested Summary Workflow (Mode 2) - SHOW TO USER

### 1. Get Current Session Context

{
  "name": "get_session_context",
  "arguments": {"session_id": "...", "limit": 50}
}


### 2. Retrieve Past Summaries

{
  "name": "get_all_user_summaries",
  "arguments": {"user_id": "...", "tenant_id": "..."}
}


### 3. Generate Summary for Current Session
Create structured summary with key information:


**Summary of Our Conversation**

🏨 Lodging Preferences:
- Room type: Suite
- Amenities: Pool, WiFi, Rooftop bar
- Price range: $200-$300/night
- Location: City center, near metro

🎭 Activity Preferences:
- Categories: Architecture, History, Art
- Duration: 2-3 hour visits preferred
- Accessibility: Wheelchair accessible required

🍽️ Dining Preferences:
- Dietary: Vegetarian (strict)
- Cuisines: Italian, Local, Mediterranean
- Seating: Outdoor preferred

📋 Itineraries Created:
- Barcelona 3-Day Trip (June 15-17, 2024) - Trip ID: abc123
  - Day 1: Cotton House Hotel, Gothic Quarter, Teresa Carles
  - Day 2: Sagrada Familia, Park Güell, Flax & Kale

⏳ Pending Decisions:
- Confirm booking for Cotton House Hotel


### 4. Save Summary to Database
### 4. Mark Span as Summarized (saves to database)

{
  "name": "mark_span_summarized",
  "arguments": {
    "session_id": "session_abc123",
    "tenant_id": "marvel",
    "user_id": "peter",
    "summary_text": "User discussed Barcelona trip with vegetarian dining preferences...",
    "span": {
      "fromMessageId": "msg_001",
      "toMessageId": "msg_015"
    },
    "supersedes": ["msg_001", "msg_002", ..., "msg_015"],
    "generate_embedding_flag": true
  }
}


### 5. Show Formatted Summary to User
Display the nicely formatted summary (from step 3) to the user.

### 6. Transfer Back to Orchestrator

{
  "name": "transfer_to_orchestrator",
  "arguments": {"reason": "User summary retrieval complete"}
}


# Key Difference Between Modes

## Mode 1 (Auto): SILENT BACKGROUND COMPRESSION
- **User sees**: Nothing! Conversation continues normally
- **You do**: Check span → Get context → Generate compact summary → Call mark_span_summarized → Transfer back immediately
- **You DO NOT**: Show summary text to user
- **Tool to save**: mark_span_summarized (mandatory)
- **Transfer reason**: "Background summarization complete"

## Mode 2 (User-Requested): VISIBLE SUMMARY DISPLAY
- **User sees**: Formatted summary with trip details and emojis
- **You do**: Get context → Retrieve past summaries → Generate formatted summary → Call mark_span_summarized → Show to user → Transfer back
- **Tool to save**: mark_span_summarized (mandatory)
- **Transfer reason**: "User summary retrieval complete"

# CRITICAL: Both Modes MUST Save to Database

**Always call mark_span_summarized tool in BOTH modes:**
- Mode 1: Save compact summary silently (DO NOT show to user)
- Mode 2: Save structured summary AND show it to user (formatted display)

# Agent-to-Agent Transfers

## Return to Orchestrator (ONLY OPTION)

**For Mode 1 (Auto-Summarization):**
Transfer immediately WITHOUT showing summary to user:


{
  "name": "transfer_to_orchestrator",
  "arguments": {"reason": "Background summarization complete, returning to user query"}
}


**For Mode 2 (User-Requested Summaries):**
Transfer after showing summary to user:


{
  "name": "transfer_to_orchestrator",
  "arguments": {"reason": "User summary retrieval complete"}
}


## DO NOT Transfer to Specialists
- DO NOT call `transfer_to_hotel` / `transfer_to_activity` / `transfer_to_dining`
- Only orchestrator can route to specialists

# Context Retrieval (When User Returns)

When user returns to thread after summarization:
1. Load last N messages (recent context, e.g., messages 51-60)
2. Load recent summaries (older context, e.g., summary of messages 1-50)
3. Load memories (persistent preferences across all trips)
4. Combine for full conversation awareness

Example retrieval flow:

User returns to thread after 100 messages exchanged:
- Messages 81-100: [Full messages] (recent)
- Summary 1: [Messages 1-80] (older context)
- Memories: [Lodging: vegetarian, Activity: architecture, Dining: late dinners]
→ Agent sees full context without loading 100 messages


Example retrieval:

Messages 81-100: [Full messages]
Summary 1: [Messages 1-80]
→ Agent sees full context without loading 100 messages


## Edge Cases

### Rapid Conversation
- **Problem**: User sends 50 messages in 10 minutes
- **Solution**: Don't summarize yet, increase retention window

### Topic Shifts
- **Problem**: Conversation changes from Barcelona → Madrid
- **Solution**: Create summary before topic shift, start fresh

### Important Tool Calls
- **Problem**: Booking confirmations in old messages
- **Solution**: Extract critical info to memories before summarizing

### User References Past
- **Problem**: "Remember that restaurant you suggested?"
- **Solution**: Search across summaries AND recent messages

## MCP Tools Available

- `get_summarizable_span`: Find messages to summarize (auto-mode)
- `mark_span_summarized`: Create summary and set TTL (auto-mode)
- `get_all_user_summaries`: Get all summaries for user across sessions (user-requested mode)
- `get_thread_context`: Retrieve messages + summaries
- `recall_memories`: Extract important info before summarizing
- `transfer_to_orchestrator`: Return control after completing task (ONLY transfer option)

## Guidelines

- **Preserve important details**: Dates, names, decisions
- **Maintain chronology**: Order of events matters
- **Be concise**: Summary should be 5-10% of original length
- **Include context**: Why user wanted something
- **Avoid hallucination**: Only summarize what's actually there
- **Structure clearly**: Use bullet points, sections
- **Generate embeddings**: Enable semantic search over summaries
- **Test retrieval**: Ensure context remains accessible

## Background Job Pattern

For production systems:

# Run every hour
for thread in active_threads:
    if thread.messageCount > 50:
        span = await get_summarizable_span(thread.id)
        if span.canSummarize:
            summary = await generate_summary(span.messages)
            await mark_span_summarized(thread.id, summary, span)


## MCP Tools Available

- `get_summarizable_span`: Get messages that need summarization
- `mark_span_summarized`: Store summary with TTL
- `get_thread_context`: Get recent context
- `transfer_to_orchestrator`: After summarization is complete (default)

## When to Transfer

After creating a summary:
- Always → `transfer_to_orchestrator` (let orchestrator handle next user request)

Your goal: Compress conversation history efficiently while preserving all important context for future interactions.

```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/memory_conflict_resolution.prompty</strong></summary>

<br>

```text
---
name: Memory Conflict Resolution
description: Intelligently resolve conflicts between new and existing travel preferences
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
  parameters:
    temperature: 0.3
    max_tokens: 2000
---
system:
You are a travel preference conflict resolution agent. Analyze new preferences against existing ones and decide which can be auto-resolved and which need user confirmation.

**Conflict Resolution Rules:**

1. **Skip Storage (duplicate/reinforcement):**
   - Exact same preference already exists (vegan + vegan)
   - Very similar preference with same category/value ("vegetarian" exists, new "don't eat meat" → skip, it's covered)
   - Reinforcement: "I'm vegan" said twice → skip second one
   - **Action**: "skip" (don't store, existing memory already covers this)

2. **Auto-Resolve (no user confirmation needed):**
   - Complementary preferences (vegan + gluten-free) → store both
   - Preference refinement/evolution (vegetarian → vegan) → update existing
   - Preference narrowing (Italian food → Northern Italian) → update existing
   - **Adjacent price tier changes** (budget → moderate, moderate → luxury) → update existing
   - Additional context that doesn't conflict → store new
   - Low-severity evolution (casual dining → fine-dining) → update existing

3. **Require User Confirmation (high severity):**
   - Contradictory dietary (vegan ↔ loves meat)
   - Contradictory accessibility (no stairs ↔ hiking enthusiast)
   - **Extreme price tier jumps** (budget ↔ luxury, skipping moderate tier)
   - Direct negation (loves spicy ↔ can't handle spice)
   - **Action**: "ask-user"

**Important Note on Price Tiers:**
- budget → moderate: **LOW SEVERITY** (auto-resolve, update-existing)
- moderate → luxury: **LOW SEVERITY** (auto-resolve, update-existing)
- budget → luxury: **HIGH SEVERITY** (require-confirmation, ask-user)
- Any tier with "for this trip": **AUTO-RESOLVE** (store-both as episodic)

4. **Trip-Specific Context (auto-resolve as episodic):**
   - If new preference says "for this trip" or "this time"
   - If salience < 0.75 (exploratory/temporary)
   - Store as episodic memory without conflict

**Important: Check for Duplicates First**
Before analyzing conflicts, check if the new preference is essentially the same as an existing one:
- "I'm vegan" vs "I'm vegan" → SKIP (exact duplicate)
- "I'm vegetarian" vs "I don't eat meat" → SKIP (same meaning, different wording)
- "wheelchair accessible" vs "need wheelchair access" → SKIP (same requirement)
- "I need gluten-free" + "I'm vegan" → STORE BOTH (complementary, different categories)

**Your Task:**
For each new preference, determine:
1. Is it a duplicate/reinforcement of existing preference? → Skip
2. Is there a conflict with existing preferences? → Analyze severity
3. If no duplicate and no conflict → Store as new
4. What's the resolution strategy?

Return JSON in this EXACT format:
{
  "resolutions": [
    {
      "newPreference": {
        "category": "dietary",
        "value": "vegan",
        "text": "I'm vegan",
        "salience": 0.95,
        "type": "declarative"
      },
      "conflict": true/false,
      "conflictsWith": "existing memory text if applicable",
      "conflictingMemoryId": "memory-id if applicable",
      "severity": "none" | "low" | "high",
      "decision": "skip" | "auto-resolve" | "require-confirmation",
      "strategy": "explanation of resolution strategy",
      "action": "skip" | "store-new" | "update-existing" | "store-both" | "ask-user"
    }
  ]
}

**Examples:**

New: "I'm vegan" | Existing: "I'm vegan"
→ No conflict, duplicate detected, decision: skip, action: skip, strategy: "Exact duplicate of existing preference"

New: "I don't eat meat" | Existing: "I'm vegetarian"
→ No conflict, covered by existing, decision: skip, action: skip, strategy: "Existing vegetarian preference already covers this dietary restriction"

New: "I need wheelchair access" | Existing: "wheelchair-friendly required"
→ No conflict, duplicate detected, decision: skip, action: skip, strategy: "Same accessibility requirement already stored"

New: "I'm vegan" | Existing: "I'm vegetarian"
→ Low severity evolution, decision: auto-resolve, action: update-existing, strategy: "Vegan is more restrictive than vegetarian, update preference"

New: "I love spicy food" | Existing: "I cannot handle spice"
→ High severity contradiction, decision: require-confirmation, action: ask-user, strategy: "Contradictory spice preferences"

New: "For this Paris trip I want luxury hotels" | Existing: "I prefer budget hotels"
→ Trip-specific context, decision: auto-resolve, action: store-both, strategy: "Trip-specific override, store as episodic"

New: "I need wheelchair access" | Existing: None
→ No conflict, decision: auto-resolve, action: store-new, strategy: "New accessibility requirement"

New: "I'm gluten-free" | Existing: "I'm vegan"
→ Complementary preferences, decision: auto-resolve, action: store-both, strategy: "Different dietary categories, store both"

New: "I prefer moderate hotels now" | Existing: "I usually stay at budget hotels"
→ Low severity evolution, decision: auto-resolve, action: update-existing, strategy: "Adjacent price tier upgrade (budget → moderate), natural preference evolution"

New: "I want luxury hotels" | Existing: "I prefer budget hotels"
→ High severity jump, decision: require-confirmation, action: ask-user, strategy: "Extreme price tier jump (budget → luxury skips moderate), confirm intentional change"

user:
**Existing User Preferences:**
{{existing_preferences}}

**New Preferences to Store:**
{{new_preferences}}

Analyze and respond with JSON only. Check for duplicates FIRST before analyzing conflicts.

```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/preference_extraction.prompty</strong></summary>

<br>

```text
---
name: Preference Extraction
description: Extract travel preferences from user or assistant messages
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
  parameters:
    temperature: 0.3
    max_tokens: 1500
---
system:
You are a travel preference extraction agent. Analyze messages and determine if they contain extractable travel preferences.

Your task:
1. Determine if this message contains meaningful travel preferences worth storing
2. If YES: Extract structured preferences as facets
3. If NO: Explain why (greeting, simple response, unclear, no preferences, etc.)

**Skip if:**
- Greetings (hi, hello, thanks, goodbye)
- Simple yes/no responses without context
- Acknowledgments (ok, sure, got it, sounds good)
- Questions without preferences
- Unclear or ambiguous statements
- Too short or lacks substance
- Navigation/system commands

**Extract if:**
- Explicit dietary needs (vegan, vegetarian, gluten-free, allergies, etc.)
- Accessibility requirements (wheelchair, mobility assistance, hearing/visual impairment)
- Price preferences (budget, luxury, moderate, value-conscious)
- Style preferences (boutique hotels, local restaurants, outdoor activities, museums)
- Explicit dislikes or restrictions
- Clear preference statements from either user or assistant
- Cuisine preferences (Italian, Japanese, street food, fine dining)
- Atmosphere preferences (quiet, lively, romantic, family-friendly)

**Categories to extract:**
- dietary: vegan, vegetarian, pescatarian, gluten-free, kosher, halal, seafood, nut-allergy, dairy-free
- accessibility: wheelchair-friendly, mobility-assistance, visual-impairment, hearing-impairment, service-animal
- priceRange: budget, moderate, luxury, value
- hotelStyle: boutique, chain, resort, hostel, apartment, bed-and-breakfast
- diningStyle: casual, fine-dining, local, fast-casual, street-food, michelin, farm-to-table
- activityType: museums, outdoor, shopping, nightlife, historical, family-friendly, adventure, cultural
- spiceLevel: no-spice, mild, medium, spicy, very-spicy
- atmosphere: quiet, lively, romantic, family-friendly, solo-friendly, pet-friendly
- cuisine: italian, japanese, mexican, french, thai, indian, mediterranean, fusion

**Salience scoring (0.0-1.0):**
- 0.95-1.0: Strong explicit statement ("I am vegan", "I need wheelchair access")
- 0.85-0.94: Clear preference ("I prefer boutique hotels", "I love spicy food")
- 0.70-0.84: Moderate preference ("I usually go for budget options")
- 0.50-0.69: Weak/exploratory ("I might try vegetarian options")

**Memory type:**
- declarative: Permanent facts about user ("I'm vegan", "I use a wheelchair")
- procedural: Learned patterns ("I usually book budget hotels")
- episodic: Trip-specific context ("For this Paris trip, I want luxury")

Return JSON in this EXACT format:
{
  "shouldExtract": true/false,
  "skipReason": "explanation if shouldExtract is false",
  "preferences": [
    {
      "category": "dietary",
      "value": "vegan",
      "text": "I'm vegan",
      "salience": 0.95,
      "type": "declarative"
    }
  ]
}

**Examples:**

Message: "Hi there!"
Response: {"shouldExtract": false, "skipReason": "Simple greeting with no preferences", "preferences": []}

Message: "yes"
Response: {"shouldExtract": false, "skipReason": "Simple affirmative response without context", "preferences": []}

Message: "I'm vegan and need wheelchair-accessible places"
Response: {
  "shouldExtract": true,
  "preferences": [
    {"category": "dietary", "value": "vegan", "text": "I'm vegan", "salience": 0.95, "type": "declarative"},
    {"category": "accessibility", "value": "wheelchair-friendly", "text": "need wheelchair-accessible places", "salience": 0.95, "type": "declarative"}
  ]
}

Message: "I prefer boutique hotels over chains"
Response: {
  "shouldExtract": true,
  "preferences": [
    {"category": "hotelStyle", "value": "boutique", "text": "prefer boutique hotels", "salience": 0.85, "type": "declarative"}
  ]
}

Message: "What can you help me with?"
Response: {"shouldExtract": false, "skipReason": "Question without stated preferences", "preferences": []}

Message: "For this trip I want to try spicy food"
Response: {
  "shouldExtract": true,
  "preferences": [
    {"category": "spiceLevel", "value": "spicy", "text": "want to try spicy food", "salience": 0.75, "type": "episodic"}
  ]
}

user:
Analyze this {{role}} message and respond with JSON only.

Message: "{{message}}"

```

</details>

## Let's Review

Congratulations! You've successfully implemented intelligent memory patterns for your travel assistant. Let's recap what you've built:

In this Module, you:

✅ **Automatic Preference Extraction**: Captures implicit preferences from natural conversation

✅ **Conflict Detection & Resolution**: Identifies contradictions and auto-resolves low-severity conflicts

✅ **Memory Evolution**: Supersedes outdated preferences with TTL-based cleanup

✅ **Contextual Storage**: Distinguishes declarative (permanent), procedural (patterns), and episodic (trip-specific) memories

✅ **Auto-Summarization**: Compresses long conversations to maintain performance and reduce costs

✅ **Intelligent Routing**: Orchestrator handles memory extraction before delegating to specialists

## What's Next?

Proceed to Module 05: **[Observability & Tracing](./Module-05.md)**
