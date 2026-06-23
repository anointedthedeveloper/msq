"""
Question Counter
Scans the questions folder and counts total questions per subject.
"""

import json
import os
from pathlib import Path
from collections import defaultdict


def count_questions(questions_dir: str = "questions") -> dict:
    """
    Count questions in all JSON files in the questions directory.
    
    Returns:
        dict: Mapping of subject slug to question count
    """
    questions_path = Path(questions_dir)
    
    if not questions_path.exists():
        print(f"Error: Directory '{questions_dir}' does not exist.")
        return {}
    
    counts = {}
    total = 0
    
    # Get all JSON files
    json_files = sorted(questions_path.glob("*.json"))
    
    print(f"\n{'='*60}")
    print(f"  Question Count Report")
    print(f"{'='*60}\n")
    
    for json_file in json_files:
        subject_slug = json_file.stem
        
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                questions = json.load(f)
            
            count = len(questions)
            counts[subject_slug] = count
            total += count
            
            print(f"  {subject_slug:<45} {count:>6} questions")
        except (json.JSONDecodeError, IOError) as e:
            print(f"  {subject_slug:<45} ERROR: {e}")
            counts[subject_slug] = 0
    
    print(f"\n{'='*60}")
    print(f"  Total: {total} questions across {len(counts)} subjects")
    print(f"{'='*60}\n")
    
    return counts


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Count questions in the questions folder"
    )
    parser.add_argument(
        "--dir",
        default="questions",
        help="Directory containing question JSON files (default: questions)"
    )
    
    args = parser.parse_args()
    
    counts = count_questions(args.dir)
    
    # Optionally save to a file
    if counts:
        output_file = "question_counts.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(counts, f, ensure_ascii=False, indent=2)
        print(f"Counts saved to: {output_file}")


if __name__ == "__main__":
    main()
