"""
Heuristic Evaluators for Travel Assistant

Fast, deterministic evaluators that check specific criteria without LLM calls.
"""

def correct_routing(outputs: dict, reference_outputs: dict) -> bool:
    """
    Check if orchestrator routed to the correct specialist agent.
    
    Args:
        outputs: Contains actual_route from the system
        reference_outputs: Contains expected_route
        
    Returns:
        Boolean indicating if routing was correct
    """
    return outputs.get("actual_route", "") == reference_outputs.get("expected_route", "")


def required_tools_called(outputs: dict, reference_outputs: dict) -> bool:
    """
    Check if all required tools were called during execution.
    
    Args:
        outputs: Contains tools_called list
        reference_outputs: Contains required_tools list
        
    Returns:
        Boolean indicating if all required tools were called
    """
    tools_called = outputs.get("tools_called", [])
    required_tools = reference_outputs.get("required_tools", [])
    
    # All required tools must be called
    return all(tool in tools_called for tool in required_tools)


def tool_call_accuracy(outputs: dict, reference_outputs: dict) -> float:
    """
    Calculate accuracy of tool calls (0.0 to 1.0).
    
    Measures both precision (no unexpected tools) and recall (all required tools called).
    
    Args:
        outputs: Contains tools_called list
        reference_outputs: Contains required_tools and optional optional_tools lists
        
    Returns:
        Float score from 0.0 to 1.0 indicating tool usage accuracy
    """
    tools_called = set(outputs.get("tools_called", []))
    required_tools = set(reference_outputs.get("required_tools", []))
    optional_tools = set(reference_outputs.get("optional_tools", []))
    
    # Expected tools = required + optional
    expected_tools = required_tools | optional_tools
    
    if not expected_tools:
        return 1.0 if not tools_called else 0.0
    
    # Calculate overlap
    correct_calls = len(tools_called & expected_tools)
    total_calls = len(tools_called)
    
    if total_calls == 0:
        return 0.0
    
    # Score: correct calls / total calls, penalize missing required tools
    missing_required = len(required_tools - tools_called)
    score = (correct_calls / total_calls) - (missing_required * 0.2)
    
    return max(0.0, min(1.0, score))
