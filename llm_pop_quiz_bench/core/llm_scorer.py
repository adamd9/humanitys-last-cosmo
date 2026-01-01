from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import httpx
import openai
from dotenv import load_dotenv

from .llm_task_config import llm_task_config
from .prompt_loader import load_prompt

# Load environment variables
load_dotenv()

SCORING_PROMPT = load_prompt("quiz_scoring")
SUMMARY_PROMPT = load_prompt("summary_generation")


def score_quiz_with_llm(
    quiz_def: dict,
    model_responses: List[Dict[str, Any]],
    model_name: str | None = None,
    api_key_env: str | None = None,
) -> str:
    """
    Use an LLM to intelligently score a quiz and determine the outcome.
    
    Args:
        quiz_def: The quiz definition (YAML structure)
        model_responses: List of model responses with question_id and choice
        model_name: LLM model to use for scoring
        api_key_env: Environment variable name for API key
        
    Returns:
        The determined outcome/personality as a string
    """
    task_config = llm_task_config.get_task("quiz_scoring")
    model_name = model_name or task_config.get("model", "gpt-4o")
    api_key_env = api_key_env or task_config.get("api_key_env", "OPENAI_API_KEY")

    api_key = os.environ.get(api_key_env)
    if not api_key:
        # Fallback to empty result if no API key
        return ""
    
    try:
        # Format the data for the LLM
        quiz_json = json.dumps(quiz_def, indent=2, ensure_ascii=False)
        responses_json = json.dumps(model_responses, indent=2, ensure_ascii=False)
        
        prompt = SCORING_PROMPT.format(
            quiz_definition=quiz_json,
            model_responses=responses_json
        )
        
        # Set up OpenAI client
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        http_client = httpx.Client(proxies=proxy) if proxy else None
        client = openai.OpenAI(api_key=api_key, http_client=http_client)
        
        # Make the API call
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a quiz scoring expert."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,  # Low temperature for consistent scoring
            max_tokens=50     # Short response expected
        )
        
        result = response.choices[0].message.content.strip()
        return result
        
    except Exception as e:
        # Log error but don't crash - return empty result
        print(f"Warning: LLM scoring failed: {e}")
        return ""


def generate_summary_with_llm(
    quiz_def: dict,
    model_results: dict,
    affinity_scores: dict = None,
    model_name: str | None = None,
) -> str:
    """
    Generate an engaging summary of quiz results using an LLM.
    
    Args:
        quiz_def: The quiz definition with questions and outcomes
        model_results: Dictionary mapping model_id to outcome
        affinity_scores: Optional affinity scores across outcome dimensions
        model_name: OpenAI model to use for generation
    
    Returns:
        Generated markdown summary text
    """
    task_config = llm_task_config.get_task("summary_generation")
    model_name = model_name or task_config.get("model", "gpt-4o-mini")
    api_key_env = task_config.get("api_key_env", "OPENAI_API_KEY")

    api_key = os.environ.get(api_key_env)
    if not api_key:
        return "**Summary Generation Unavailable**\n\nOpenAI API key not configured."
    
    try:
        # Format the data for the LLM
        quiz_json = json.dumps(quiz_def, indent=2, ensure_ascii=False)
        results_json = json.dumps(model_results, indent=2, ensure_ascii=False)
        affinity_json = json.dumps(affinity_scores, indent=2, ensure_ascii=False) if affinity_scores else "Not available"
        
        prompt = SUMMARY_PROMPT.format(
            quiz_definition=quiz_json,
            model_results=results_json,
            affinity_scores=affinity_json
        )
        
        # Set up OpenAI client
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        http_client = httpx.Client(proxies=proxy) if proxy else None
        client = openai.OpenAI(api_key=api_key, http_client=http_client)
        
        # Make the API call
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are an expert analyst specializing in AI model behavior and personality assessment."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # Some creativity but still focused
            max_tokens=1500   # Longer response for comprehensive summary
        )
        
        result = response.choices[0].message.content.strip()
        return result
        
    except Exception as e:
        # Log error but provide fallback
        print(f"Warning: LLM summary generation failed: {e}")
        return f"**Summary Generation Failed**\n\nUnable to generate LLM-powered summary: {str(e)[:100]}..."


def score_quiz_fallback(
    quiz_def: dict,
    model_responses: List[Dict[str, Any]]
) -> str:
    """
    Fallback scoring logic for when LLM scoring is unavailable.
    Implements basic "mostly" letter counting.
    """
    if not model_responses:
        return ""
    
    # Count choice frequencies
    choice_counts = {}
    for response in model_responses:
        choice = response.get("choice", "")
        if choice:
            choice_counts[choice] = choice_counts.get(choice, 0) + 1
    
    if not choice_counts:
        return ""
    
    # Find most frequent choice
    most_frequent_choice = max(choice_counts.items(), key=lambda x: x[1])[0]
    
    # Look for outcome matching this choice
    for outcome in quiz_def.get("outcomes", []):
        # Handle direct format (mostly: A, text: Kim)
        if outcome.get("mostly") == most_frequent_choice:
            return outcome.get("text", outcome.get("id", ""))
        
        # Handle condition-based format
        condition = outcome.get("condition", {})
        if condition.get("mostly") == most_frequent_choice:
            return outcome.get("result", "")
    
    return ""
