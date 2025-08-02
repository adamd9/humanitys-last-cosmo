from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import httpx
import openai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

SCORING_PROMPT = """You are an expert at analyzing personality quiz results and determining outcomes.

Given a quiz definition and a model's responses, determine which outcome/personality the model achieved.

Quiz Definition:
{quiz_definition}

Model Responses:
{model_responses}

Instructions:
1. Analyze the quiz structure and scoring mechanism
2. Look at the model's choices for each question
3. Apply the quiz's scoring rules to determine the outcome
4. Return the result as a simple string (the personality/outcome name)

If the quiz uses:
- "mostly" scoring: Count which choice letter (A/B/C/D/E/F) appears most frequently
- Tag-based scoring: Look at option tags and count frequencies
- Point-based scoring: Sum up scores from chosen options
- Custom logic: Apply any other scoring mechanism described

Return ONLY the outcome name/text, nothing else."""


def score_quiz_with_llm(
    quiz_def: dict,
    model_responses: List[Dict[str, Any]],
    model_name: str = "gpt-4o",
    api_key_env: str = "OPENAI_API_KEY"
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
