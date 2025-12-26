from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from . import visualizer
from .llm_scorer import score_quiz_with_llm, score_quiz_fallback
from .runtime_data import build_runtime_paths, get_runtime_paths
from .sqlite_store import connect, fetch_quiz_def, fetch_results, insert_asset
from .store import write_csv


def render_outcomes_table(quiz_title: str, outcomes: Iterable[tuple[str, str]]) -> str:
    lines = ["| Model | Outcome |", "|-------|---------|"]
    for model_id, outcome in outcomes:
        lines.append(f"| {model_id} | {outcome} |")
    return "\n".join(lines)


def write_summary_csv(path: Path, rows: Iterable[dict]) -> None:
    df = pd.DataFrame(rows)
    write_csv(path, df.to_dict(orient="records"))


def load_results(run_id: str, runtime_dir: Path | None = None) -> pd.DataFrame:
    runtime_paths = get_runtime_paths() if runtime_dir is None else build_runtime_paths(runtime_dir)
    conn = connect(runtime_paths.db_path)
    rows = fetch_results(conn, run_id)
    conn.close()
    return pd.DataFrame(rows)


def render_questions_and_answers(quiz_def: dict) -> str:
    """Render detailed questions and all possible answers for interpretability."""
    if not quiz_def or "questions" not in quiz_def:
        return "Questions and answers not available."
    
    lines = []
    for i, question in enumerate(quiz_def["questions"], 1):
        qid = question.get("id", f"q{i}")
        qtext = question.get("text", "")
        
        lines.append(f"**{qid.upper()}: {qtext}**")
        lines.append("")
        
        # List all possible answers
        for option in question.get("options", []):
            option_id = option.get("id", "")
            option_text = option.get("text", "")
            lines.append(f"- **{option_id}**: {option_text}")
        
        lines.append("")  # Add spacing between questions
    
    return "\n".join(lines)


def render_ai_reasoning_section(df: pd.DataFrame, quiz_def: dict) -> str:
    """Render a section showing AI reasoning and additional thoughts for each question."""
    if df.empty:
        return "No AI reasoning data available."
    
    lines = []
    lines.append("Ever wondered what goes on in an AI's mind when taking a personality quiz? Here's the behind-the-scenes thinking for each question:")
    lines.append("")
    
    # Get question text and option mapping
    question_texts: dict = {}
    question_options: dict = {}
    if quiz_def and "questions" in quiz_def:
        for q in quiz_def["questions"]:
            qid = q.get("id", "")
            question_texts[qid] = q.get("text", "")

            # Build a mapping of answer choice id to its text for each question
            opts = q.get("options", []) or []
            question_options[qid] = {opt.get("id", ""): opt.get("text", "") for opt in opts}
    
    # Group by question and show reasoning for each model
    for qid, group in df.groupby("question_id"):
        question_text = question_texts.get(qid, qid)
        lines.append(f"### {question_text}")
        lines.append("")
        
        for _, row in group.iterrows():
            model_id = row.get("model_id", "")
            choice = row.get("choice", "")
            # Lookup the text associated with the chosen option, if available
            option_text = question_options.get(qid, {}).get(choice, "")
            reason = row.get("reason", "")
            additional_thoughts = row.get("additional_thoughts", "")

            if option_text:
                lines.append(f"**{model_id.title()}** chose **{choice}: {option_text}**")
            else:
                lines.append(f"**{model_id.title()}** chose **{choice}**")
            
            if reason:
                lines.append(f"- *Reasoning*: {reason}")
            
            if additional_thoughts:
                lines.append(f"- *Additional thoughts*: {additional_thoughts}")
            
            if not reason and not additional_thoughts:
                lines.append("- *No reasoning provided*")
            
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    return "\n".join(lines)


def render_results_interpretation(df: pd.DataFrame, outcomes: list, quiz_def: dict, affinity_scores: dict = None) -> str:
    """Generate an engaging interpretation of the quiz results using LLM-powered analysis."""
    if not outcomes:
        return "No results to interpret."
    
    # Import the LLM summary generator
    from .llm_scorer import generate_summary_with_llm
    
    # Prepare model results dictionary
    model_outcomes = {o["model_id"]: o["outcome"] for o in outcomes}
    
    # Generate LLM-powered summary
    try:
        summary = generate_summary_with_llm(
            quiz_def=quiz_def,
            model_results=model_outcomes,
            affinity_scores=affinity_scores
        )
        return summary
    except Exception as e:
        # Fallback to basic summary if LLM generation fails
        print(f"Warning: LLM summary generation failed, using fallback: {e}")
        return _render_fallback_summary(model_outcomes)


def _render_fallback_summary(model_outcomes: dict) -> str:
    """Fallback summary when LLM generation is unavailable."""
    lines = []
    lines.append("## 🤖 Quiz Results Summary")
    lines.append("")
    lines.append(f"Analysis of {len(model_outcomes)} AI model{'s' if len(model_outcomes) > 1 else ''} taking a personality quiz:")
    lines.append("")
    
    for model, outcome in model_outcomes.items():
        lines.append(f"- **{model}**: {outcome}")
    
    lines.append("")
    lines.append("*Note: Detailed LLM-powered analysis unavailable.*")
    
    return "\n".join(lines)


def render_method_section(quiz_def: dict) -> str:
    """Render method section explaining how answers map to outcomes."""
    if not quiz_def:
        return "Method information not available."
    
    lines = []
    lines.append("This quiz uses a personality scoring system where each answer choice corresponds to different personality traits. The final outcome is determined by analyzing the pattern of choices across all questions.")
    lines.append("")
    
    # Explain outcome mapping if available
    if "outcomes" in quiz_def:
        lines.append("**Outcome Mapping:**")
        lines.append("")
        
        for outcome in quiz_def["outcomes"]:
            outcome_text = outcome.get("text", outcome.get("id", ""))
            outcome_mostly = outcome.get("mostly", "")
            outcome_desc = outcome.get("description", "")
            
            if outcome_mostly:
                lines.append(f"- **{outcome_text}**: Primarily associated with choice '{outcome_mostly}'")
                if outcome_desc:
                    lines.append(f"  - {outcome_desc}")
            else:
                lines.append(f"- **{outcome_text}**: {outcome_desc}")
        
        lines.append("")
        lines.append("**Scoring Method:**")
        lines.append("The system analyzes each model's choice distribution across all questions and uses intelligent LLM-based scoring to determine which personality profile best matches the response pattern. This approach allows for nuanced personality assessment beyond simple letter counting.")
    
    return "\n".join(lines)


def render_question_table(df: pd.DataFrame, quiz_def: dict = None) -> str:
    """Render a markdown table showing model choices with actual question text and answers."""
    pivot = df.pivot(index="question_id", columns="model_id", values="choice")
    cols = list(pivot.columns)
    
    # Create proper markdown table header
    lines = ["| Question | " + " | ".join(cols) + " |"]
    lines.append("|" + "|".join(["-" * 10 for _ in range(len(cols) + 1)]) + "|")
    
    # Get question and choice text from quiz definition if available
    question_texts = {}
    choice_texts = {}
    if quiz_def and "questions" in quiz_def:
        for q in quiz_def["questions"]:
            qid = q.get("id", "")
            question_texts[qid] = q.get("text", qid)
            # Build choice text mapping
            for choice in q.get("choices", []):
                choice_id = choice.get("id", "")
                choice_text = choice.get("text", choice_id)
                choice_texts[f"{qid}_{choice_id}"] = f"{choice_id}: {choice_text[:50]}{'...' if len(choice_text) > 50 else ''}"
    
    for qid, row in pivot.iterrows():
        # Use question text if available, otherwise use question ID
        question_display = question_texts.get(qid, qid)
        if len(question_display) > 80:
            question_display = question_display[:80] + "..."
        
        # Get model choices with answer text if available
        vals = []
        for c in cols:
            choice = str(row.get(c, ""))
            if choice and f"{qid}_{choice}" in choice_texts:
                choice_display = choice_texts[f"{qid}_{choice}"]
            else:
                choice_display = choice
            vals.append(choice_display)
        
        lines.append("| " + question_display + " | " + " | ".join(vals) + " |")
    
    return "\n".join(lines)


def compute_model_outcomes(df: pd.DataFrame, quiz_def: dict) -> list[dict[str, str]]:
    """Compute quiz outcomes using LLM-based intelligent scoring."""
    outcomes = []
    
    for model_id, g in df.groupby("model_id"):
        # Prepare model responses for LLM scoring
        model_responses = []
        for _, row in g.iterrows():
            model_responses.append({
                "question_id": row["question_id"],
                "choice": row["choice"],
                "reason": row.get("reason", "")
            })
        
        # Try LLM-based scoring first
        result = score_quiz_with_llm(quiz_def, model_responses)
        
        # If LLM scoring fails or returns empty, use fallback
        if not result:
            result = score_quiz_fallback(quiz_def, model_responses)
        
        outcomes.append({"model_id": model_id, "outcome": result})
    
    return outcomes


def generate_charts(
    df: pd.DataFrame,
    out_dir: Path,
    run_id: str,
    quiz_id: str,
    quiz_def: dict,
    outcome_csv_path: Path | None = None,
) -> dict[str, Path]:
    """Generate unified comparative charts showing all models together."""
    import numpy as np
    from math import pi
    
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    
    # Load outcome-focused data if available
    outcome_df = None
    if outcome_csv_path and outcome_csv_path.exists():
        try:
            import pandas as pd
            outcome_df = pd.read_csv(outcome_csv_path)
            print(f"✅ Using outcome-focused data from {outcome_csv_path.name}")
        except Exception as e:
            print(f"⚠️  Could not load outcome CSV: {e}")
    
    # Get all unique choices and models
    all_choices = sorted(df["choice"].unique())
    models = sorted(df["model_id"].unique())
    
    # Load quiz definition to get meaningful labels and outcomes
    choice_labels = {}
    outcome_labels = {}
    if quiz_def:
        # Build mapping from choice ID to meaningful text (for choice-level charts)
        for question in quiz_def.get("questions", []):
            for option in question.get("options", []):
                choice_id = option.get("id")
                choice_text = option.get("text", choice_id)
                if choice_id and choice_id not in choice_labels:
                    # Truncate long text for better chart readability
                    if len(choice_text) > 25:
                        choice_text = choice_text[:22] + "..."
                    choice_labels[choice_id] = choice_text

        # Build mapping of outcomes (personalities/results)
        for outcome in quiz_def.get("outcomes", []):
            outcome_id = outcome.get("id")
            outcome_text = outcome.get("text", outcome_id)
            if outcome_id:
                outcome_labels[outcome_id] = outcome_text
    
    # Create display labels for choices
    choice_display_labels = [choice_labels.get(choice, choice) for choice in all_choices]
    
    # Determine if this is an outcome-based quiz (has outcomes defined)
    is_outcome_quiz = bool(outcome_labels)
    
    # For outcome-based quizzes, compute outcomes for each model
    model_outcomes = {}
    if is_outcome_quiz and quiz_def:
        from .llm_scorer import score_quiz_with_llm, score_quiz_fallback
        
        for model in models:
            model_df = df[df["model_id"] == model]
            model_responses = []
            for _, row in model_df.iterrows():
                model_responses.append({
                    "question_id": row["question_id"],
                    "choice": row["choice"],
                    "reason": row.get("reason", "")
                })
            
            # Try LLM-based scoring first, fallback to basic scoring
            try:
                outcome = score_quiz_with_llm(quiz_def, model_responses)
                # Extract just the outcome name if it's in the format "outcome_name" or "Outcome Name"
                for outcome_id, outcome_text in outcome_labels.items():
                    if outcome_text.lower() in outcome.lower() or outcome_id.lower() in outcome.lower():
                        outcome = outcome_text
                        break
            except Exception:
                outcome = score_quiz_fallback(quiz_def, model_responses)
                # Map to outcome text if possible
                if outcome in outcome_labels:
                    outcome = outcome_labels[outcome]
            
            model_outcomes[model] = outcome
    
    if len(models) == 1:
        # Single model - create a simple bar chart
        model_data = df[df["model_id"] == models[0]]["choice"].value_counts().sort_index()
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Create bar chart with meaningful labels
        x_pos = range(len(model_data))
        bars = ax.bar(x_pos, model_data.values, color='steelblue', alpha=0.8)
        
        # Set meaningful labels
        meaningful_labels = [choice_labels.get(choice, choice) for choice in model_data.index]
        ax.set_xticks(x_pos)
        ax.set_xticklabels(meaningful_labels, rotation=45, ha='right')
        
        ax.set_xlabel("Quiz Choices")
        ax.set_ylabel("Count")
        ax.set_title(f"Quiz Choices - {models[0]}")
        ax.grid(axis='y', alpha=0.3)
        
        img_path = out_dir / f"{run_id}.{quiz_id}.choices.png"
        fig.tight_layout()
        fig.savefig(img_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        paths["choices"] = img_path
        return paths
    
    # Multi-model visualizations
    
    # For outcome-based quizzes, create outcome-focused charts
    if outcome_df is not None and not outcome_df.empty:
        print(f"📊 Generating outcome-focused charts from CSV data")
        
        # Extract outcome data from CSV
        model_outcomes = {}
        for _, row in outcome_df.iterrows():
            model_outcomes[row['model_id']] = row['outcome_text']
        
        # 1. Outcome Bar Chart - Show which models got which outcomes
        unique_outcomes = list(set(model_outcomes.values()))
        outcome_counts = {outcome: 0 for outcome in unique_outcomes}
        
        for outcome in model_outcomes.values():
            outcome_counts[outcome] += 1
        
        fig, ax = plt.subplots(figsize=(10, 6))
        outcomes = list(outcome_counts.keys())
        counts = list(outcome_counts.values())
        
        bars = ax.bar(outcomes, counts, color='steelblue', alpha=0.8)
        ax.set_xlabel("Quiz Outcomes")
        ax.set_ylabel("Number of Models")
        ax.set_title("Model Outcome Distribution")
        ax.grid(axis='y', alpha=0.3)
        
        # Add value labels on bars
        for bar, count in zip(bars, counts):
            if count > 0:
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                       str(count), ha='center', va='bottom', fontweight='bold')
        
        # Add model names as annotations
        y_offset = 0.1
        for outcome in outcomes:
            models_with_outcome = [model for model, out in model_outcomes.items() if out == outcome]
            if models_with_outcome:
                outcome_idx = outcomes.index(outcome)
                ax.text(outcome_idx, outcome_counts[outcome] + y_offset,
                       ', '.join(models_with_outcome), ha='center', va='bottom',
                       fontsize=9, style='italic')
        
        img_path = out_dir / f"{run_id}.{quiz_id}.outcomes.png"
        fig.tight_layout()
        fig.savefig(img_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        paths["outcomes"] = img_path
        
        # 2. Model-Outcome Matrix (if multiple models)
        if len(models) > 1:
            fig, ax = plt.subplots(figsize=(8, 6))
            
            # Create matrix showing model -> outcome mapping
            matrix_data = []
            for model in models:
                row = []
                for outcome in unique_outcomes:
                    row.append(1 if model_outcomes.get(model) == outcome else 0)
                matrix_data.append(row)
            
            matrix = np.array(matrix_data)
            im = ax.imshow(matrix, cmap='RdYlGn', aspect='auto', vmin=0, vmax=1)
            
            # Set ticks and labels
            ax.set_xticks(np.arange(len(unique_outcomes)))
            ax.set_yticks(np.arange(len(models)))
            ax.set_xticklabels(unique_outcomes, rotation=45, ha='right')
            ax.set_yticklabels(models)
            
            # Add text annotations
            for i in range(len(models)):
                for j in range(len(unique_outcomes)):
                    text = "✓" if matrix[i, j] == 1 else ""
                    ax.text(j, i, text, ha="center", va="center", 
                           color="black", fontsize=16, fontweight="bold")
            
            ax.set_title("Model → Outcome Mapping")
            ax.set_xlabel("Quiz Outcomes")
            ax.set_ylabel("Models")
            
            img_path = out_dir / f"{run_id}.{quiz_id}.model_outcomes.png"
            fig.tight_layout()
            fig.savefig(img_path, dpi=300, bbox_inches='tight')
            plt.close(fig)
            paths["model_outcomes"] = img_path
        
        # 3. Outcome-Dimension Radar Chart - Show model affinity across all outcome dimensions
        outcome_affinity_scores = calculate_outcome_affinities(outcome_df, quiz_def)
        
        if outcome_affinity_scores and len(outcome_affinity_scores) > 0:
            # Check if we have multiple possible outcomes in quiz definition (not just final outcomes)
            all_quiz_outcomes = [outcome.get("text", outcome.get("id", "")) for outcome in quiz_def.get("outcomes", [])]
            if len(all_quiz_outcomes) >= 3:
                radar_path = create_outcome_radar_chart(outcome_affinity_scores, out_dir, run_id, quiz_id)
                if radar_path:
                    paths["outcome_radar"] = radar_path
        
        # 4. Outcome-Dimension Heatmap - Model vs All Outcome Dimensions
        if outcome_affinity_scores and len(models) >= 1:
            # Generate heatmap even with single model to show affinity distribution
            all_quiz_outcomes = [outcome.get("text", outcome.get("id", "")) for outcome in quiz_def.get("outcomes", [])]
            if len(all_quiz_outcomes) > 1:
                heatmap_path = create_outcome_heatmap(outcome_df, quiz_def, out_dir, run_id, quiz_id)
                if heatmap_path:
                    paths["outcome_heatmap"] = heatmap_path
        
        return paths
    
    # For non-outcome quizzes, generate choice-level charts
    print(f"📊 Generating choice-level charts (no outcome data available)")
    
    # 1. Grouped Bar Chart - Choice Distribution Comparison
    choice_data = []
    for choice in all_choices:
        choice_counts = []
        for model in models:
            count = len(df[(df["model_id"] == model) & (df["choice"] == choice)])
            choice_counts.append(count)
        choice_data.append(choice_counts)
    
    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(all_choices))
    width = 0.8 / len(models)
    colors = plt.cm.Set3(np.linspace(0, 1, len(models)))
    
    for i, model in enumerate(models):
        counts = [choice_data[j][i] for j in range(len(all_choices))]
        ax.bar(x + i * width, counts, width, label=model, color=colors[i], alpha=0.8)
    
    ax.set_xlabel("Quiz Choices")
    ax.set_ylabel("Number of Selections")
    ax.set_title("Choice Distribution Comparison Across Models")
    ax.set_xticks(x + width * (len(models) - 1) / 2)
    ax.set_xticklabels(choice_display_labels, rotation=45, ha='right')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    
    img_path = out_dir / f"{run_id}.{quiz_id}.comparison.png"
    fig.tight_layout()
    fig.savefig(img_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    paths["comparison"] = img_path
    
    # 2. Radar Chart - Choice Profile Comparison (if we have enough choices)
    if len(all_choices) >= 3:
        fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(projection='polar'))
        
        # Calculate angles for each choice
        angles = [n / float(len(all_choices)) * 2 * pi for n in range(len(all_choices))]
        angles += angles[:1]  # Complete the circle
        
        for i, model in enumerate(models):
            # Get choice percentages for this model
            model_df = df[df["model_id"] == model]
            total_choices = len(model_df)
            
            if total_choices > 0:
                values = []
                for choice in all_choices:
                    count = len(model_df[model_df["choice"] == choice])
                    percentage = (count / total_choices) * 100
                    values.append(percentage)
                values += values[:1]  # Complete the circle
                
                ax.plot(angles, values, 'o-', linewidth=2, label=model, color=colors[i])
                ax.fill(angles, values, alpha=0.25, color=colors[i])
        
        # Customize the radar chart
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(choice_display_labels, fontsize=10)
        ax.set_ylim(0, 100)
        ax.set_ylabel("Percentage of Choices", labelpad=20)
        ax.set_title("Choice Profile Comparison (Radar Chart)", pad=20)
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.0))
        ax.grid(True)
        
        img_path = out_dir / f"{run_id}.{quiz_id}.radar.png"
        fig.tight_layout()
        fig.savefig(img_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        paths["radar"] = img_path
    
    # 3. Heatmap - Model vs Choice Matrix
    if len(models) > 1 and len(all_choices) > 1:
        # Create matrix of choice counts
        matrix = np.zeros((len(models), len(all_choices)))
        for i, model in enumerate(models):
            for j, choice in enumerate(all_choices):
                count = len(df[(df["model_id"] == model) & (df["choice"] == choice)])
                matrix[i, j] = count
        
        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto')
        
        # Set ticks and labels
        ax.set_xticks(np.arange(len(all_choices)))
        ax.set_yticks(np.arange(len(models)))
        ax.set_xticklabels(choice_display_labels, rotation=45, ha='right')
        ax.set_yticklabels(models)
        
        # Add text annotations
        for i in range(len(models)):
            for j in range(len(all_choices)):
                text = ax.text(j, i, int(matrix[i, j]), ha="center", va="center", color="black", fontweight="bold")
        
        ax.set_title("Choice Selection Heatmap")
        ax.set_xlabel("Quiz Choices")
        ax.set_ylabel("Models")
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label("Number of Selections")
        
        img_path = out_dir / f"{run_id}.{quiz_id}.heatmap.png"
        fig.tight_layout()
        fig.savefig(img_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        paths["heatmap"] = img_path
    
    return paths


def calculate_outcome_affinities(outcome_df: pd.DataFrame, quiz_def: dict) -> dict:
    """Calculate each model's affinity scores across all possible outcome dimensions."""
    try:
        # Get all possible outcomes from quiz definition
        all_outcomes = []
        outcome_rules = {}
        for outcome in quiz_def.get("outcomes", []):
            outcome_text = outcome.get("text", outcome.get("id", ""))
            outcome_mostly = outcome.get("mostly", "")
            if outcome_text:
                all_outcomes.append(outcome_text)
                outcome_rules[outcome_text] = outcome_mostly
        
        if not all_outcomes:
            return {}
        
        # Calculate affinity scores for each model
        model_affinities = {}
        
        for _, row in outcome_df.iterrows():
            model_id = row['model_id']
            choice_distribution = eval(row['choice_distribution'])  # Convert string dict back to dict
            
            # Calculate affinity to each outcome based on choice patterns
            affinities = {}
            total_score = 0
            
            for outcome in all_outcomes:
                outcome_letter = outcome_rules.get(outcome, "")
                # Score based on how many choices align with this outcome's "mostly" letter
                score = choice_distribution.get(outcome_letter, 0)
                affinities[outcome] = score
                total_score += score
            
            # Normalize to percentages
            if total_score > 0:
                for outcome in affinities:
                    affinities[outcome] = (affinities[outcome] / total_score) * 100
            
            model_affinities[model_id] = affinities
        
        return model_affinities
        
    except Exception as e:
        print(f"Warning: Could not calculate outcome affinities: {e}")
        return {}


def create_outcome_radar_chart(affinity_scores: dict, out_dir: Path, run_id: str, quiz_id: str) -> Path:
    """Create radar chart showing model affinities across all outcome dimensions."""
    try:
        import numpy as np
        from math import pi
        import matplotlib.pyplot as plt
        
        if not affinity_scores:
            return None
        
        # Get all outcomes and models
        all_outcomes = list(next(iter(affinity_scores.values())).keys())
        models = list(affinity_scores.keys())
        
        if len(all_outcomes) < 3:
            return None
        
        fig, ax = plt.subplots(figsize=(12, 12), subplot_kw=dict(projection='polar'))
        
        # Calculate angles for each outcome dimension
        angles = [n / float(len(all_outcomes)) * 2 * pi for n in range(len(all_outcomes))]
        angles += angles[:1]  # Complete the circle
        
        colors = plt.cm.Set3(np.linspace(0, 1, len(models)))
        
        for i, model in enumerate(models):
            # Get affinity scores for this model
            values = [affinity_scores[model][outcome] for outcome in all_outcomes]
            values += values[:1]  # Complete the circle
            
            ax.plot(angles, values, 'o-', linewidth=2, label=model, color=colors[i])
            ax.fill(angles, values, alpha=0.25, color=colors[i])
        
        # Customize the radar chart
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(all_outcomes, fontsize=11)
        ax.set_ylim(0, 100)
        ax.set_ylabel("Affinity Percentage", labelpad=30)
        ax.set_title("Model Affinity Across Outcome Dimensions", pad=30, fontsize=14)
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.0))
        ax.grid(True)
        
        img_path = out_dir / f"{run_id}.{quiz_id}.outcome_radar.png"
        fig.tight_layout()
        fig.savefig(img_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        return img_path
        
    except Exception as e:
        print(f"Warning: Could not create outcome radar chart: {e}")
        return None


def create_outcome_heatmap(outcome_df: pd.DataFrame, quiz_def: dict, out_dir: Path, run_id: str, quiz_id: str) -> Path:
    """Create heatmap showing model affinities across all outcome dimensions."""
    try:
        import numpy as np
        import matplotlib.pyplot as plt
        
        # Calculate affinity scores
        affinity_scores = calculate_outcome_affinities(outcome_df, quiz_def)
        if not affinity_scores:
            return None
        
        # Get all outcomes and models
        all_outcomes = list(next(iter(affinity_scores.values())).keys())
        models = list(affinity_scores.keys())
        
        # Create matrix of affinity scores
        matrix = np.zeros((len(models), len(all_outcomes)))
        for i, model in enumerate(models):
            for j, outcome in enumerate(all_outcomes):
                matrix[i, j] = affinity_scores[model][outcome]
        
        fig, ax = plt.subplots(figsize=(10, 6))
        im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto')
        
        # Set ticks and labels
        ax.set_xticks(np.arange(len(all_outcomes)))
        ax.set_yticks(np.arange(len(models)))
        ax.set_xticklabels(all_outcomes, rotation=45, ha='right')
        ax.set_yticklabels(models)
        
        # Add text annotations
        for i in range(len(models)):
            for j in range(len(all_outcomes)):
                text = f"{matrix[i, j]:.1f}%"
                ax.text(j, i, text, ha="center", va="center", 
                       color="black" if matrix[i, j] < 50 else "white", 
                       fontweight="bold", fontsize=10)
        
        ax.set_title("Model Affinity Across Outcome Dimensions")
        ax.set_xlabel("Outcome Dimensions")
        ax.set_ylabel("Models")
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label("Affinity Percentage")
        
        img_path = out_dir / f"{run_id}.{quiz_id}.outcome_heatmap.png"
        fig.tight_layout()
        fig.savefig(img_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        return img_path
        
    except Exception as e:
        print(f"Warning: Could not create outcome heatmap: {e}")
        return None


def create_outcome_summary(df: pd.DataFrame, quiz_def: dict) -> list[dict]:
    """Create outcome-focused summary data for CSV export and chart generation."""
    try:
        if not quiz_def or not quiz_def.get("outcomes"):
            return []
        
        # Build outcome mapping
        outcome_labels = {}
        for outcome in quiz_def.get("outcomes", []):
            outcome_id = outcome.get("id")
            outcome_text = outcome.get("text", outcome_id)
            if outcome_id:
                outcome_labels[outcome_id] = outcome_text
        
        # Compute outcomes for each model
        from .llm_scorer import score_quiz_with_llm, score_quiz_fallback
        
        outcome_summary = []
        models = sorted(df["model_id"].unique())
        
        for model in models:
            model_df = df[df["model_id"] == model]
            model_responses = []
            
            # Collect all responses for this model
            for _, row in model_df.iterrows():
                model_responses.append({
                    "question_id": row["question_id"],
                    "choice": row["choice"],
                    "reason": row.get("reason", "")
                })
            
            # Compute outcome using LLM-based scoring
            try:
                outcome = score_quiz_with_llm(quiz_def, model_responses)
                # Extract just the outcome name if it's in the format "outcome_name" or "Outcome Name"
                for outcome_id, outcome_text in outcome_labels.items():
                    if outcome_text.lower() in outcome.lower() or outcome_id.lower() in outcome.lower():
                        outcome = outcome_text
                        break
            except Exception:
                outcome = score_quiz_fallback(quiz_def, model_responses)
                # Map to outcome text if possible
                if outcome in outcome_labels:
                    outcome = outcome_labels[outcome]
            
            # Add to summary
            outcome_summary.append({
                "run_id": df["run_id"].iloc[0],
                "quiz_id": quiz_def.get("id", ""),
                "model_id": model,
                "outcome_id": outcome,
                "outcome_text": outcome,
                "total_questions": len(model_responses),
                "choice_distribution": model_df["choice"].value_counts().to_dict()
            })
        
        return outcome_summary
        
    except Exception as e:
        quiz_id = quiz_def.get("id", "unknown")
        print(f"Warning: Could not create outcome summary for {quiz_id}: {e}")
        return []


def generate_markdown_report(run_id: str, runtime_dir: Path | None = None) -> None:
    df = load_results(run_id, runtime_dir)
    if df.empty:
        raise ValueError(f"No results for run {run_id}")

    runtime_paths = get_runtime_paths() if runtime_dir is None else build_runtime_paths(runtime_dir)
    run_assets_dir = runtime_paths.assets_dir / run_id
    summary_dir = run_assets_dir / "reports"
    charts_dir = run_assets_dir / "charts"
    summary_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    raw_choices_path = summary_dir / f"{run_id}_raw_choices.csv"
    write_summary_csv(raw_choices_path, df.to_dict(orient="records"))

    conn = connect(runtime_paths.db_path)
    insert_asset(conn, run_id, "csv_raw_choices", raw_choices_path)

    for quiz_id, qdf in df.groupby("quiz_id"):
        quiz_def = fetch_quiz_def(conn, quiz_id)
        if not quiz_def:
            raise ValueError(f"Quiz definition not found for quiz ID: {quiz_id}")

        # Create outcome-focused CSV for this quiz
        outcome_summary_data = create_outcome_summary(qdf, quiz_def)
        outcome_csv_path = summary_dir / f"{run_id}_{quiz_id}_outcomes.csv"
        if outcome_summary_data:
            write_summary_csv(outcome_csv_path, outcome_summary_data)
            insert_asset(conn, run_id, "csv_outcomes", outcome_csv_path)

        outcomes = compute_model_outcomes(qdf, quiz_def)
        md_lines = [f"# {quiz_def['title']}", f"Source: {quiz_def['source']['url']}"]
        md_lines.append("\n## Outcomes")
        md_lines.append(
            render_outcomes_table(
                quiz_def["title"], [(o["model_id"], o["outcome"]) for o in outcomes]
            )
        )
        md_lines.append("\n## Choices by Question")
        md_lines.append(render_question_table(qdf, quiz_def))

        # Generate charts using outcome-focused data if available
        chart_paths = generate_charts(qdf, charts_dir, run_id, quiz_id, quiz_def, outcome_csv_path)
        for chart_type, chart_path in chart_paths.items():
            if chart_path and chart_path.exists():
                relative_path = f"../charts/{chart_path.name}"
                md_lines.append(f"\n![{chart_path.stem}]({relative_path})\n")
                insert_asset(conn, run_id, f"chart_{chart_type}", chart_path)

        # Add fun results interpretation section
        md_lines.append("\n## Results Summary and Interpretation")

        # Calculate affinity scores for interpretation if we have outcome data
        affinity_scores = None
        if outcome_csv_path.exists():
            try:
                outcome_df = pd.read_csv(outcome_csv_path)
                affinity_scores = calculate_outcome_affinities(outcome_df, quiz_def)
            except Exception:
                pass

        interpretation = render_results_interpretation(qdf, outcomes, quiz_def, affinity_scores)
        md_lines.append(interpretation)

        # Add AI reasoning section
        md_lines.append("\n## AI Reasoning and Insights")
        reasoning_section = render_ai_reasoning_section(qdf, quiz_def)
        md_lines.append(reasoning_section)

        # Add reference sections at the end
        md_lines.append("\n---")
        md_lines.append("\n# Reference")

        md_lines.append("\n## Questions and Answer Options")
        md_lines.append(render_questions_and_answers(quiz_def))

        md_lines.append("\n## Method")
        md_lines.append(render_method_section(quiz_def))

        try:
            vis_paths = visualizer.generate_visualizations(
                qdf,
                outcomes,
                quiz_def,
                run_assets_dir / "pandasai_charts",
                run_id,
                quiz_id,
            )
            for path in vis_paths.values():
                rel = path.relative_to(summary_dir.parent)
                md_lines.append(f"\n![{path.stem}]({rel.as_posix()})")
                insert_asset(conn, run_id, "chart_pandasai", path)
        except Exception:
            pass

        md_content = "\n".join(md_lines)
        md_file = summary_dir / f"{run_id}.{quiz_id}.md"
        md_file.write_text(md_content, encoding="utf-8")
        insert_asset(conn, run_id, "report_markdown", md_file)

    conn.close()
