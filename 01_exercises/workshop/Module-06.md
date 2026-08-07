# Module 06 - Evaluating Your Multi-Agent Application (Bonus Module)

**[< Observability & Experimentation](./Module-05.md#module-05---observability-tracing)** - **[Agent Analytics >](./Module-07.md#module-07---agent-analytics-visibility-insight)**

## Introduction

You've built a travel assistant that combines a LangGraph supervisor, three tool wrappers (`find_places`, `create_or_update_itinerary`, `recall_memories`), an MCP server, and the Cosmos DB Agent Memory Toolkit. But how do you know it's working correctly? How do you catch bugs before they reach users? How do you measure improvements when you make changes?

Evaluation matters for agentic systems because they have many moving parts: tool selection by the supervisor, sub-agent execution, memory retrieval, and response generation. A bug in any component can cascade through the system. Without systematic testing, you're flying blind.

In this module, you'll learn how to create comprehensive evaluations for your multi-agent application. You'll build datasets, implement evaluators using both LLM-as-judge and heuristic methods, and learn to interpret results in LangSmith.

## Learning Objectives and Activities

In this module, you will:

- Understand why evaluating multi-agent systems is critical and challenging
- Review the evaluation infrastructure already created in the `evaluation/` folder
- Create evaluation datasets for different test scenarios
- Implement LLM-as-judge evaluators for response quality assessment
- Build heuristic evaluators for tool-routing accuracy and tool usage
- Run evaluations and interpret results in LangSmith
- Learn how to expand your evaluation coverage for production systems

## Module Exercises

1. [Activity 1: Understanding Multi-Agent Evaluation](#activity-1-understanding-multi-agent-evaluation)
2. [Activity 2: Setting Up Your Evaluation Infrastructure](#activity-2-setting-up-your-evaluation-infrastructure)
3. [Activity 3: Running End-to-End Evaluation](#activity-3-running-end-to-end-evaluation)
4. [Activity 4: Running Tool Routing Evaluation](#activity-4-running-tool-routing-evaluation)
5. [Activity 5: Running Tool Usage Evaluation](#activity-5-running-tool-usage-evaluation)
6. [Activity 6: Next Steps - Expanding Your Evaluation Coverage](#activity-6-next-steps---expanding-your-evaluation-coverage)

---

## Activity 1: Understanding Agentic Evaluation

### Why Evaluate Agentic Systems?

Agentic systems are complex. Unlike single-model applications, they have multiple points of failure:

- **Tool Selection**: Does the supervisor pick the right tool for each request?
- **Tool Usage**: Are the right MCP tools called with the right parameters?
- **Memory**: Are preferences captured by the toolkit and recalled correctly?
- **Response Quality**: Are responses accurate, helpful, and natural?

A traditional unit test can check if a function returns the right type, but it can't tell you if your travel assistant's response sounds robotic or if it hallucinated a hotel name. You need a different approach.

### Types of Evaluations

**1. End-to-End Response Quality**

- Measures the overall quality of responses to user questions
- Evaluates accuracy, helpfulness, and conversational tone
- Uses LLM-as-judge to assess subjective qualities

**2. Tool Routing Accuracy**

- Verifies the supervisor picks the correct top-level tool wrapper (`find_places`, `create_or_update_itinerary`, or `recall_memories`)
- Ensures "Find hotels in Paris" routes to `find_places`, not `create_or_update_itinerary`
- Uses simple comparisons (heuristic evaluation)

**3. Tool Usage Correctness**

- Checks if the supervisor and its sub-agents call the expected tools
- Verifies tools like `discover_places`, `create_new_trip`, or `recall_memories` are invoked
- Measures both precision (no unexpected tools) and recall (all required tools called)

### Evaluation Approaches

**LLM-as-Judge**

- Uses an LLM to evaluate another LLM's output
- Good for subjective criteria like "Is this response helpful?"
- Requires clear grading instructions and structured output
- Example: Evaluating if a response sounds natural and friendly

**Heuristic Evaluators**

- Fast, deterministic checks based on rules
- Good for objective criteria like "Was this tool called?"
- No LLM costs, instant results
- Example: Checking if `actual_tool == expected_tool`

### Challenges Specific to Agentic Systems

**Non-Determinism**

- Agents may phrase responses differently each time
- Temperature > 0 means variation in outputs
- Solution: Evaluate criteria (correctness, helpfulness) rather than exact text match

**Memory Interference**

- Tests can affect each other through shared memory
- Solution: Use unique tenant/user IDs per test to isolate memory

**Multiple Execution Paths**

- Same question might take different valid paths through the supervisor and its sub-agents
- Solution: Define acceptable variations in your test cases

---

## Activity 2: Setting Up Your Evaluation Infrastructure

The evaluation infrastructure has already been created in the `evaluation/` folder. Let's review its structure.

### Evaluation Folder Structure

```
01_exercises/evaluation/
├── datasets/                    # Test datasets in JSON format
│   ├── e2e_dataset.json         # End-to-end response quality tests (6 cases)
│   ├── routing_dataset.json     # Supervisor tool-routing tests (8 cases)
│   └── tool_usage_dataset.json  # Tool calling pattern tests (4 cases)
├── evaluators/                  # Evaluation functions
│   ├── __init__.py
│   ├── llm_judges.py            # LLM-as-judge evaluators
│   └── heuristic_evaluators.py  # Fast heuristic checks
├── e2e_evaluation.py            # End-to-end evaluation script
├── routing_evaluation.py        # Tool routing evaluation script
├── tool_usage_evaluation.py     # Tool usage evaluation script
```

### Understanding the Datasets

Each dataset is a JSON file containing test cases with inputs and expected outputs.

**Example from `e2e_dataset.json`:**

```json
{
  "inputs": {
    "question": "Find me hotels in Barcelona"
  },
  "outputs": {
    "answer": "Before I search for hotels in Barcelona, I'd love to personalize my recommendations for you. Do you have any preferences or requirements?"
  }
}
```

This test case checks the response quality — does the supervisor appropriately ask for preferences before searching? The LLM-as-judge evaluators compare the actual response to this reference behavior.

### Understanding the Evaluators

**LLM Judges** (`evaluators/llm_judges.py`):

1. **`answer_quality`**: Evaluates overall response quality

   - Relevance, helpfulness, accuracy, completeness
   - Returns: Boolean (True if quality meets criteria)

2. **`correctness`**: Evaluates factual accuracy only

   - No hallucinations, consistent information
   - Returns: Boolean (True if factually correct)

3. **`humanness`**: Evaluates conversational quality
   - Natural language, appropriate tone, empathy
   - Returns: Integer score 1-5 (5 = exceptionally natural)

**Heuristic Evaluators** (`evaluators/heuristic_evaluators.py`):

1. **`correct_tool_routing`**: Verifies the supervisor picked the right top-level tool wrapper
2. **`required_tools_called`**: Confirms all required tools were invoked
3. **`tool_call_accuracy`**: Calculates precision/recall of tool usage (0.0-1.0)

### Understanding the Evaluation Scripts

Each script follows this pattern:

1. Load environment variables
2. Initialize Cosmos DB and the supervisor agent
3. Load dataset from JSON file
4. Create/update LangSmith dataset
5. Define target function (runs the supervisor and captures outputs)
6. Run evaluation with appropriate evaluators
7. Results automatically logged to LangSmith

---

## Activity 3: Running End-to-End Evaluation

Open the **.env** file in the **python** folder of your codebase.

Add these three lines at the end of your **.env** file:

```bash
LANGCHAIN_API_KEY="<your_langsmith_api_key>"
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_PROJECT="multi-agent-travel-app"
```

Your complete **.env** file should now look like this:

```bash
COSMOSDB_ENDPOINT="<your_cosmos_db_uri>"
AZURE_OPENAI_ENDPOINT="<your_azure_open_ai_uri>"
AZURE_OPENAI_EMBEDDINGDEPLOYMENTID="text-embedding-3-small"
AZURE_OPENAI_COMPLETIONSDEPLOYMENTID="gpt-5.1"
LANGCHAIN_API_KEY="<your_langsmith_api_key>"
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_PROJECT="multi-agent-travel-app"
```

End-to-end evaluation tests the complete user journey from question to final answer.

### Step 1: Review the E2E Dataset

Open `evaluation/datasets/e2e_dataset.json` and review the test cases.

You'll see 6 examples covering different scenarios:

- Hotel searches
- Vegetarian restaurant requests
- Itinerary creation
- Preference recall
- Open-ended trip planning
- Dietary preference statements

Each test case has:

- `question`: The user's input
- `answer`: The expected response pattern (not exact match — the LLM-as-judge evaluators compare against it)

### Step 2: Understand the Evaluators

The E2E evaluation uses three LLM-as-judge evaluators:

**`answer_quality`**

- Compares student response to reference response
- Checks relevance, helpfulness, accuracy, completeness
- Allows responses with MORE detail than reference
- Encourages clarifying questions

**`correctness`**

- Focuses purely on factual accuracy
- Ensures no hallucinations or made-up information
- Allows appropriate follow-up questions

**`humanness`**

- Scores conversational quality on 1-5 scale
- Evaluates natural language, tone, empathy, clarity
- 5 = exceptionally natural, 1 = robotic

### Step 3: Run the Evaluation Script

**Make sure your MCP server is running:**

```powershell
cd mcp_server
$env:PYTHONPATH="..\python"; python mcp_http_server.py
```

**Important**: Always ensure your virtual environment is activated before starting the server!

You must be in **multi-agent-workshop\01_exercises** folder and then use the below commands to activate the virtual environment. And after activating the environment, follow the above commands to re-start the mcp server.  

```powershell
cd multi-agent-workshop\01_exercises
.\.venv-travel\Scripts\Activate.ps1
```

**Now run the E2E evaluation, Open a new terminal tab**

```powershell
cd multi-agent-workshop\01_exercises\evaluation
.\.venv-travel\Scripts\Activate.ps1
$env:PYTHONPATH="..\python"; python e2e_evaluation.py
```

You'll see output like:

```
============================================================
🧪 END-TO-END EVALUATION - Travel Assistant
============================================================

🔄 Initializing Cosmos DB...
✅ Cosmos DB initialized
🔄 Setting up agents...
✅ Agents initialized
🔄 Building agent graph...
✅ Agent graph ready

📊 Loading dataset from evaluation/datasets/e2e_dataset.json...
✅ Loaded 6 examples
🔄 Creating dataset 'travel-assistant-e2e-eval'...
✅ Dataset created with 6 examples

============================================================
🚀 RUNNING EVALUATION
============================================================

[Progress indicators as each test runs...]

============================================================
✅ EVALUATION COMPLETE
============================================================
```

### Step 4: What Happened?

The evaluation script:

1. Initialized your multi-agent system
2. Loaded 6 test cases from the JSON file
3. Created a LangSmith dataset
4. For each test case:
   - Ran the question through your agent graph
   - Captured the response
   - Applied all three LLM-as-judge evaluators
   - Logged results to LangSmith
5. Generated an experiment in LangSmith with all results

### Step 5: Viewing Results in LangSmith

Navigate to the LangSmith dashboard at https://smith.langchain.com

Click on "Datasets & Experiments" in the left sidebar, you would see the list of experiments you ran.

![Test1](./media/Module-06/Test1.png)

You should see the **travel-assistant-comprehensive-e2e** experiment.

![Test2](./media/Module-06/Test2.png)

Click on the experiment to see detailed results.

![Test3](./media/Module-06/Test3.png)

You'll see:

- Overall statistics (how many passed/failed)
- Individual test case results
- Scores for each evaluator (answer_quality, correctness, humanness)

Click on any individual test case to see full details.

![Test4](./media/Module-06/Test4.png)

You can see:

- The input question
- Your agent's actual response
- The expected reference response
- Each evaluator's score and reasoning

### Step 6: Viewing the Dataset

Go back to the "Datasets & Experiments", and click on the **travel-assistant-comprehensive-e2e** experiment. Now go the to tab **examples** next to the **experiments** tab.

![Test5](./media/Module-06/Test5.png)

You can:

- View all test examples
- Add new examples directly in the UI
- Edit existing examples
- Delete examples
- Export the dataset

This is useful for managing your test cases without editing JSON files directly.

---

## Activity 4: Running Tool Routing Evaluation

Tool routing evaluation verifies that the supervisor picks the correct top-level tool wrapper for each request.

### Step 1: Review the Routing Dataset

Open `evaluation/datasets/routing_dataset.json` and review the 8 test cases.

Examples:

- "Find hotels in Barcelona" → Expected tool: `find_places`
- "Create a 3-day itinerary for Paris" → Expected tool: `create_or_update_itinerary`
- "What are my hotel preferences?" → Expected tool: `recall_memories`
- "Hi, I'm planning a trip" → Expected tool: `none` (supervisor answers directly)

### Step 2: Understand the Routing Evaluator

The routing evaluation uses one heuristic evaluator:

**`correct_tool_routing`**

- Compares `actual_tool` to `expected_tool`
- Returns True if they match, False otherwise
- Fast, deterministic check

How the actual tool is determined:

- The script streams events from the supervisor graph and watches for `on_tool_start` events
- It filters for the three supervisor wrappers — `find_places`, `create_or_update_itinerary`, and `recall_memories`
- The first matching wrapper is the routing decision
- If no wrapper fires (the supervisor answers directly), `actual_tool` is `"none"`

### Step 3: Run the Routing Evaluation
In the same terminal window, where you ran the e2e evaluation, run the below command to start the tool routing evaluations.

```powershell
$env:PYTHONPATH="..\python"; python routing_evaluation.py
```

You'll see similar output to the E2E evaluation, but focused on tool-routing accuracy.

### Step 4: Brief Explanation

The routing evaluation:

1. Runs each question through the supervisor graph
2. Tracks which top-level tool wrapper is invoked first using event streaming
3. Returns the wrapper name (or `"none"` if no wrapper fired)
4. Compares to the expected tool
5. Logs pass/fail for each test case

### Step 5: Viewing Results in LangSmith

Click on "Datasets & Experiments" in the left sidebar, you would see the list of experiments you ran.

![Test6](./media/Module-06/Test1.png)

You should see the **travel-assistant-routing** experiment.

![Test7](./media/Module-06/Test6.png)

Click on the experiment to see detailed results.

![Test8](./media/Module-06/Test7.png)

You'll see:

- Which test cases passed (correct tool chosen)
- Which test cases failed (wrong tool chosen)
- For failures, you can see what tool was invoked vs expected

Click on any individual test case to see full details.

![Test9](./media/Module-06/Test8.png)

You can see:

- The input question
- Your agent's actual response
- The expected reference response
- Each evaluator's score and reasoning

This helps identify routing bugs, like the supervisor calling `find_places` when the user only asked about their stored preferences.

### Step 6: Viewing the Dataset

Go back to the "Datasets & Experiments", and click on the **travel-assistant-routing** experiment. Now go the to tab **examples** next to the **experiments** tab.

![Test10](./media/Module-06/Test9.png)

Review the test cases and their expected tool selections. You can add more routing scenarios here to expand coverage.

---

## Activity 5: Running Tool Usage Evaluation

Tool usage evaluation ensures agents call the correct tools for different scenarios.

### Step 1: Review the Tool Usage Dataset

Open `evaluation/datasets/tool_usage_dataset.json` and review the 4 test cases.

Examples:

- "Find hotels in Barcelona" → Required tools: `find_places`, `discover_places`
- "Create a 3-day itinerary for Rome" → Required tools: `create_or_update_itinerary`, `create_new_trip`
- "What are my hotel preferences?" → Required tools: `recall_memories`

### Step 2: Understand the Tool Evaluators

The tool usage evaluation uses two heuristic evaluators:

**`required_tools_called`**

- Checks if ALL required tools were called
- Returns True only if every required tool appears in the tools_called list
- Returns False if any required tool is missing

**`tool_call_accuracy`**

- Calculates a score from 0.0 to 1.0
- Measures both precision (no unexpected tools) and recall (all required tools)
- Formula: (correct_calls / total_calls) - (missing_required \* 0.2)
- Penalizes missing required tools

### Step 3: Run the Tool Usage Evaluation

In the same terminal window, where you ran the agent routing evaluation, run the below command to start the tool usage evaluations.

```powershell
$env:PYTHONPATH="..\python"; python tool_usage_evaluation.py
```

The script will run all 4 test cases and evaluate tool calling patterns.

### Step 4: Brief Explanation

The tool usage evaluation:

1. Runs each question through the agent graph
2. Tracks which tools are called using event streaming
3. Compares the tools_called list to required_tools
4. Calculates both boolean (all required called?) and accuracy score
5. Logs results to LangSmith

### Step 5: Viewing Results in LangSmith

Click on "Datasets & Experiments" in the left sidebar, you would see the list of experiments you ran.

![Test11](./media/Module-06/Test1.png)

You should see the **travel-assistant-tools** experiment.

![Test12](./media/Module-06/Test10.png)

Click on the experiment to see detailed results.

![Test13](./media/Module-06/Test11.png)

You'll see:

- Which test cases passed (all required tools called)
- Tool call accuracy scores (0.0 - 1.0)
- For each case, the list of tools that were called

Click on any individual test case to see full details.

![Test14](./media/Module-06/Test12.png)

You can see:

- The input question
- Your agent's actual response
- The expected reference response
- Each evaluator's score and reasoning

This helps identify when the supervisor or sub-agents skip important tools or call unnecessary ones.

### Step 6: Viewing the Dataset

Go back to the "Datasets & Experiments", and click on the **travel-assistant-tools** experiment. Now go the to tab **examples** next to the **experiments** tab.

![Test15](./media/Module-06/Test13.png)

Review the required tools for each scenario. You can add more tool usage patterns to test edge cases.

---

## Activity 6: Next Steps - Expanding Your Evaluation Coverage

Now that you have a working evaluation infrastructure, here are ways to expand and improve your testing.

### 1. Memory Integration Testing

Test if preferences are correctly captured by the toolkit, retrieved by `recall_memories`, and applied to downstream searches:

**Preference Capture**

- After a few turns mentioning "I prefer budget hotels", check that a matching fact appears in the `memories` container in Cosmos DB
- Verify the preference is returned the next time `recall_memories` is called for that user

**Preference Recall**

- Pre-seed (or chat) a "vegetarian" preference for a user, then ask "Show me restaurants in Paris"
- Verify the supervisor calls `recall_memories` first and that the recalled fact biases the `find_places` results
- Check if the returned restaurants are vegetarian-friendly

**Conflicting Preferences**

- Say "I prefer budget hotels" in one session, then "Show me luxury hotels" in another
- The toolkit's dedup pipeline updates the stored preference automatically — verify by inspecting the `memories` container after both runs
- Confirm subsequent `recall_memories` calls reflect the most recent preference

Example test case for a recall-aware search:

```json
{
  "inputs": {
    "question": "Show me restaurants in Paris",
    "seeded_preferences": ["vegetarian"]
  },
  "outputs": {
    "answer": "Here are some great vegetarian restaurants in Paris.",
    "expected_tools": [
      "recall_memories",
      "find_places"
    ]
  }
}
```

### 2. Conversation Flow Testing

Test multi-turn conversations and context retention:

**Context Retention**

- Turn 1: "Find hotels in Paris"
- Turn 2: "What about restaurants?" (should remember Paris context)
- Verify the supervisor calls `find_places` with `city="Paris"` on turn 2 even though Paris wasn't repeated

**Toolkit Summarization**

- Hold a long conversation (20+ turns) with the same `thread_id`
- Verify that thread summaries appear in the `memories_summaries` container (the Cosmos DB Agent Memory Toolkit produces these on its own cadence)
- Check that recalled summaries surface during later turns when the user references earlier context

Example multi-turn test:

```json
{
  "inputs": {
    "conversation": [
      "Find me hotels in Barcelona",
      "I prefer something near the beach",
      "What about restaurants nearby?"
    ]
  },
  "outputs": {
    "final_answer_should_mention": ["Barcelona", "beach", "restaurants"],
    "expected_tools": ["recall_memories", "find_places"],
    "context_retained": true
  }
}
```

### 3. Edge Cases

Test unusual or problematic scenarios:

**Ambiguous Queries**

- "Find me a place" → Should ask for clarification
- "I need something nice" → Should ask what type (hotel, restaurant, activity)

**Invalid Locations**

- "Hotels in Atlantis" → Should handle gracefully, not hallucinate
- "Restaurants on Mars" → Should explain the location doesn't exist

**Conflicting Preferences**

- "Cheap luxury hotels" → Should detect the contradiction
- "Budget 5-star restaurants" → Should ask for clarification

**Empty Results**

- Search that returns no results → Should explain and offer alternatives
- "Vegan steakhouse" → Should handle the contradiction gracefully

Example edge case test:

```json
{
  "inputs": {
    "question": "Find me a cheap luxury hotel in Atlantis"
  },
  "outputs": {
    "should_ask_for_clarification": true,
    "should_not_hallucinate": true,
    "should_explain_issues": ["conflicting_preferences", "invalid_location"]
  }
}
```

### 4. Performance Testing

Measure and track system performance:

**Response Latency**

- Track average response time per tool wrapper (`find_places`, `create_or_update_itinerary`, `recall_memories`)
- Identify slow tools or MCP calls
- Set acceptable thresholds (e.g., <3 seconds for a `find_places` search)

**Token Usage and Cost**

- Measure tokens consumed per query type
- Calculate cost per interaction
- Identify opportunities for optimization

**Database Query Performance**

- Count Cosmos DB queries per request
- Measure vector search latency
- Optimize slow queries

Example performance test:

```python
import time

def test_find_places_performance():
    start = time.time()
    response = await graph.ainvoke({"messages": [HumanMessage("Find hotels in Paris")]})
    duration = time.time() - start

    assert duration < 3.0, f"find_places search took {duration}s, expected <3s"
    assert count_tokens(response) < 1000, "Response used too many tokens"
```

### 5. Continuous Evaluation

Set up automated evaluation runs to catch regressions:

**On Code Changes**

- Run evaluations before merging pull requests
- Compare results to baseline
- Block merges if quality decreases

**Scheduled Runs**

- Run full evaluation suite nightly
- Track trends over time
- Alert on degradation

**Experiment Comparison**

- Use LangSmith to compare experiments
- A/B test different prompts or configurations
- Make data-driven decisions

Example CI/CD integration:

```yaml
# .github/workflows/evaluation.yml
name: Run Evaluations
on: [pull_request]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run E2E Evaluation
        run: python evaluation/e2e_evaluation.py
      - name: Check Results
        run: python scripts/check_evaluation_results.py
```

### 6. Dataset Expansion

Continuously improve your test coverage:

**Add Real User Queries**

- Collect actual user questions from production logs
- Turn common queries into test cases
- Test edge cases discovered by users

**Test Different User Personas**

- Budget travelers (focus on cost)
- Luxury seekers (focus on quality)
- Families (focus on family-friendly options)
- Business travelers (focus on location, amenities)

**Multi-Lingual Support**

- If applicable, test queries in different languages
- Verify responses maintain quality across languages

**Accessibility Scenarios**

- "Wheelchair accessible hotels"
- "Hotels with braille signage"
- "Restaurants with quiet dining areas"

**Example: Adding a New Test Case**

To add a new test case, edit `evaluation/datasets/e2e_dataset.json`:

```json
{
  "inputs": {
    "question": "Find wheelchair accessible hotels near museums in London"
  },
  "outputs": {
    "answer": "Let me find wheelchair accessible hotels near museums in London for you."
  }
}
```

Then re-run the evaluation with the **same command from [Step 3](#step-3-run-the-evaluation-script)** — venv active, in a terminal from the `evaluation` folder:

```powershell
.\.venv-travel\Scripts\Activate.ps1
$env:PYTHONPATH="..\python"; python e2e_evaluation.py
```

The new test case will be included in the next evaluation run.

---

## Summary

In this module, you learned how to systematically evaluate your multi-agent travel assistant:

- Why evaluation is critical for multi-agent systems
- How to structure evaluation datasets for different test types
- Using LLM-as-judge for subjective quality assessment
- Using heuristic evaluators for objective criteria
- Running evaluations and interpreting results in LangSmith
- Expanding evaluation coverage for production readiness

Evaluation isn't a one-time activity. As your system evolves, your test suite should grow with it. Start with basic smoke tests, then add edge cases as you discover them. Track performance over time and use data to guide improvements.

With comprehensive evaluation in place, you can make changes confidently, knowing you'll catch regressions before they reach users.

---

## Where to next?

The next three modules — **07–09** — are the **optional Agent Analytics & Optimization track**:
instrument your agents, then **detect → recommend → apply → verify** cost and quality wins, viewed
live in the web **Analytics Portal** (with Microsoft Fabric reverse-ETL in Module 09).

- **Continuing with analytics?** Head to **[Module 07 — Agent Analytics »](./Module-07.md#module-07---agent-analytics-visibility-insight)**.
- **Short on time, or skipping the analytics track?** Jump straight to **[Module 10 — Lessons Learned & The Future »](./Module-10.md#module-10---lessons-learned-the-future-of-agentic-systems)** to wrap up. You can always come back to 07–09 later.

---

**[< Observability & Experimentation](./Module-05.md#module-05---observability-tracing)** - **[Agent Analytics >](./Module-07.md#module-07---agent-analytics-visibility-insight)**
